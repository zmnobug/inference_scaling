"""Token-prefix Conditional IS for thinking, followed by ordinary action sampling."""

from __future__ import annotations

import hashlib
import json
import math
import random
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from minisweagent.exceptions import FormatError
from minisweagent.models.utils.actions_text import parse_regex_actions

from inference_scaling.arllm.rewards import ConsilienceReward
from inference_scaling.swebench.baseline import BaselineDeadline, SamplingStopped
from inference_scaling.swebench.miniagent import SampledDecision
from inference_scaling.swebench.sampling import categorical_index, effective_sample_size


OPEN_ACTION = "<mswea_bash_command>"
EOS_TEXTS = ("<|im_end|>", "<|endoftext|>")


class InvalidSample(ValueError):
    """An audited response cannot be used as a scored proposal."""


@dataclass(frozen=True)
class Token:
    token_id: int
    logprob: float
    confidence: float


def decode_completion(response, prompt, requested):
    choices = response.get("choices", [])
    if len(choices) != 1:
        raise ValueError("Thinking IS requires one completion choice")
    choice = choices[0]
    usage = response["usage"]
    token_ids = choice.get("token_ids")
    scores = choice.get("logprobs") or {}
    logprobs = scores.get("token_logprobs") or []
    top_scores = scores.get("top_logprobs") or []
    if usage["prompt_tokens"] != len(prompt) or choice.get("prompt_token_ids") != list(prompt):
        raise ValueError("completion prompt token IDs/count changed")
    if not token_ids or len(token_ids) != usage["completion_tokens"]:
        raise ValueError("completion token IDs do not cover usage")
    if len(token_ids) > requested or len(logprobs) != len(token_ids) or len(top_scores) != len(token_ids):
        raise ValueError("completion scores do not cover all generated tokens")
    if scores.get("tokens") != [f"token_id:{token_id}" for token_id in token_ids]:
        raise ValueError("completion score tokens differ from generated IDs")
    if choice.get("finish_reason") not in {"stop", "length"}:
        raise ValueError("unsupported completion finish reason")
    tokens = []
    for token_id, logprob, alternatives in zip(token_ids, logprobs, top_scores, strict=True):
        values = sorted(alternatives.values(), reverse=True)
        if len(values) < 5 or not all(math.isfinite(value) and value <= 1e-5 for value in values):
            raise ValueError("Consilience requires finite top-5 processed logprobs")
        if not math.isfinite(logprob) or logprob > 1e-5:
            raise ValueError("invalid sampled logprob")
        token_key = f"token_id:{token_id}"
        if token_key in alternatives and abs(alternatives[token_key] - logprob) > 1e-5:
            raise ValueError("sampled logprob disagrees with top-logprob entry")
        tokens.append(Token(token_id, logprob, -sum(values[:5]) / 5))
    return tokens


def reward_weights(reward_groups, temperature=2.0):
    valid = [value / temperature for group in reward_groups for value in group if value is not None]
    if not valid:
        raise SamplingStopped("no_valid_thinking_rollout")
    maximum = max(valid)
    masses = [sum(math.exp(value / temperature - maximum) for value in group if value is not None) / len(group)
              for group in reward_groups]
    total = sum(masses)
    return tuple(mass / total for mass in masses)


class ThinkingISSampler:
    def __init__(self, factory, arm, seed):
        self.factory = factory
        self.arm = arm
        self.seed = seed
        self.round_index = 0
        self.request_index = 0
        self.deadline = 0.0
        self.runtime = factory.runtime
        self.model = factory.experiment.api.model_name.removeprefix("openai/")
        self.reward = ConsilienceReward(None, top_k=5, skip_fraction=0.05,
                                        window_fraction=0.2, initial_penalty=3.0, scale=1.0)
        self.rng = random.Random(self._seed("selection"))
        self.diagnostics = {"protocol": "thinking-is-token-prefix-v3", "chunk_tokens": arm.chunk_tokens,
                            "candidate_count": arm.candidate_count, "rollout_count": arm.rollout_count,
                            "reward_temperature": 2.0, "empty_thinking_policy": "uniform_if_no_scored_candidate",
                            "requests": [], "rounds": []}
        self.diagnostics["guards"] = {
            name: getattr(arm, name, 0)
            for name in ("max_steps_per_round", "max_round_seconds", "max_rollout_tokens", "fallback_to_plain")
        }
        self.cache = {}

    def _seed(self, label):
        return int(hashlib.sha256(f"{self.seed}|thinking-is|{label}".encode()).hexdigest()[:8], 16) & 0x7FFFFFFF

    def _post(self, path, payload):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise BaselineDeadline()
        base = self.runtime["base_url"].rstrip("/").removesuffix("/v1")
        request = urllib.request.Request(base + path, data=json.dumps(payload).encode(), headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {self.runtime['api_key']}",
            **self.runtime.get("extra_headers", {}),
        })
        try:
            with urllib.request.urlopen(request, timeout=min(remaining, self.factory.experiment.api.timeout_seconds)) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            raise ValueError(f"model HTTP {exc.code}: {exc.read().decode(errors='replace')[:4000]}") from exc
        except (TimeoutError, urllib.error.URLError) as exc:
            if time.monotonic() >= self.deadline:
                raise BaselineDeadline() from exc
            raise

    def _decode(self, tokens):
        key = tuple(token.token_id for token in tokens)
        if not key:
            return ""
        if key not in self.cache:
            self.cache[key] = self._post("/detokenize", {"model": self.model, "tokens": list(key)})["prompt"]
        return self.cache[key]

    def _sample(self, prompt, maximum, role):
        if maximum <= 0:
            raise SamplingStopped("trajectory_output_limit")
        self.request_index += 1
        seed = self._seed(f"request:{self.request_index}")
        entry = {"index": self.request_index, "round": self.round_index, "role": role,
                 "seed": seed, "max_tokens": maximum, "prompt_tokens": len(prompt),
                 "prompt_sha256": hashlib.sha256(json.dumps(prompt).encode()).hexdigest()}
        self.diagnostics["requests"].append(entry)
        started = time.monotonic()
        raw = None
        self.factory.ledger.start_api_request()
        try:
            raw = self._post("/v1/completions", {
                "model": self.model, "prompt": prompt, "max_tokens": maximum,
                "temperature": 1.0, "top_p": 1.0, "top_k": -1, "seed": seed,
                "logprobs": 5, "return_token_ids": True, "return_tokens_as_token_ids": True,
                "skip_special_tokens": False, "add_special_tokens": False,
                "stop": [] if role in {"action", "continuation"} else [OPEN_ACTION],
                "include_stop_str_in_output": True,
            })
            entry["response"] = raw
            try:
                tokens = decode_completion(raw, prompt, maximum)
            except ValueError as exc:
                raise InvalidSample(str(exc)) from exc
        except BaseException as exc:
            entry["error"] = {"type": type(exc).__name__, "message": str(exc)}
            entry["elapsed_seconds"] = time.monotonic() - started
            usage = (raw or {}).get("usage", {})
            self.factory.ledger.finish_api_request(usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0),
                                                  entry["elapsed_seconds"], failed=True,
                                                  raw_output_tokens=usage.get("completion_tokens", 0), dropped_hidden_tokens=0)
            raise
        entry["elapsed_seconds"] = time.monotonic() - started
        self.factory.ledger.finish_api_request(len(prompt), len(tokens), entry["elapsed_seconds"],
                                              failed=False, raw_output_tokens=len(tokens), dropped_hidden_tokens=0)
        return tokens, raw["choices"][0]["finish_reason"]

    def _token_boundary(self, tokens, character_offset):
        low, high = 0, len(tokens)
        while low < high:
            middle = (low + high) // 2
            if len(self._decode(tokens[:middle])) < character_offset:
                low = middle + 1
            else:
                high = middle
        return low

    def _boundary(self, tokens):
        text = self._decode(tokens)
        start = text.find(OPEN_ACTION)
        if start < 0:
            return None
        end = start + len(OPEN_ACTION)
        beginning = self._token_boundary(tokens, start)
        if len(self._decode(tokens[:beginning])) != start:
            beginning -= 1
        ending = self._token_boundary(tokens, end)
        prefix = self._decode(tokens[:beginning])
        inclusive = self._decode(tokens[:ending])
        if not text.startswith(prefix) or not text.startswith(inclusive):
            raise InvalidSample("action marker intersects an invalid token decoding boundary")
        if any(eos in text[:start] for eos in EOS_TEXTS):
            return None
        return beginning, ending

    def _quality(self, tokens):
        boundary = self._boundary(tokens)
        if boundary is None or boundary[0] == 0:
            return None
        score = self.reward._trajectory_score([token.confidence for token in tokens[:boundary[0]]])
        return score if math.isfinite(score) else None

    def preflight(self):
        self.deadline = time.monotonic() + 60
        prompt = self._post("/tokenize", {"model": self.model, "messages": [
            {"role": "user", "content": "Explain your plan, then provide one XML shell action."}],
            "add_generation_prompt": True})
        first, _ = self._sample(prompt["tokens"], 8, "candidate")
        second, _ = self._sample(prompt["tokens"] + [token.token_id for token in first], 2, "candidate")
        return {"exact_token_prefix": True, "top_logprobs": 5, "output_tokens": len(first) + len(second),
                "requests": self.diagnostics["requests"]}

    def __call__(self, messages, maximum, deadline):
        self.deadline = deadline
        self.round_index += 1
        self.cache = {}
        prompt = self._post("/tokenize", {"model": self.model,
            "messages": [{key: message[key] for key in ("role", "content") if key in message} for message in messages],
            "add_generation_prompt": True})
        prompt_ids = prompt["tokens"]
        if prompt["count"] != len(prompt_ids):
            raise ValueError("tokenizer count does not match prompt IDs")
        context_cap = self.factory.experiment.agent.context_window - len(prompt_ids) - self.factory.experiment.agent.context_safety_tokens
        maximum = min(maximum, context_cap)
        if maximum <= 0:
            raise SamplingStopped("context_budget_exhausted")
        round_record = {"round": self.round_index, "prompt_tokens": len(prompt_ids), "steps": []}
        self.diagnostics["rounds"].append(round_record)
        round_seconds = getattr(self.arm, "max_round_seconds", 0)
        selection_started = time.monotonic()
        if round_seconds:
            self.deadline = min(deadline, time.monotonic() + round_seconds)
        selected = []
        fallback_reason = None
        while True:
            try:
                if self._boundary(selected) is not None:
                    break
                max_steps = getattr(self.arm, "max_steps_per_round", 0)
                if max_steps and len(round_record["steps"]) >= max_steps:
                    fallback_reason = "is_step_budget"
                    break
                if time.monotonic() >= self.deadline:
                    raise BaselineDeadline()
                selected = self._select_step(prompt_ids, selected, maximum, round_record)
            except BaselineDeadline:
                if time.monotonic() >= deadline or not getattr(self.arm, "fallback_to_plain", False):
                    raise
                fallback_reason = "is_round_time_budget"
                break
            except SamplingStopped as exc:
                if str(exc) != "no_valid_thinking_rollout" or not getattr(self.arm, "fallback_to_plain", False):
                    raise
                fallback_reason = "no_valid_thinking_rollout"
                break
        self.deadline = deadline
        round_record["is_seconds"] = time.monotonic() - selection_started
        if len(selected) >= maximum:
            raise SamplingStopped("trajectory_output_limit")
        role = "continuation" if fallback_reason else "action"
        if fallback_reason:
            round_record.update(fallback_reason=fallback_reason, fallback_prefix_tokens=len(selected))
            print(json.dumps({"event": "thinking_is_fallback", "round": self.round_index,
                              "reason": fallback_reason, "prefix_tokens": len(selected)}), flush=True)
        else:
            boundary = self._boundary(selected)
            round_record["thinking_tokens"] = boundary[0]
            decoded = self._decode(selected)
            round_record["sampled_body_prefix"] = decoded.split(OPEN_ACTION, 1)[1]
        body, finish = self._sample(prompt_ids + [token.token_id for token in selected], maximum - len(selected), role)
        full = selected + body
        if fallback_reason:
            boundary = self._boundary(full)
            round_record["thinking_tokens"] = boundary[0] if boundary is not None else None
        return self._decision(full, finish, prompt_ids, round_record)

    def _select_step(self, prompt_ids, selected, maximum, round_record):
        if len(selected) >= maximum:
            raise SamplingStopped("trajectory_output_limit")
        candidates, rewards, empty_candidates = [], [], []
        step = {"prefix_tokens": len(selected), "candidates": []}
        round_record["steps"].append(step)
        for candidate_index in range(self.arm.candidate_count):
            prefix_ids = prompt_ids + [token.token_id for token in selected]
            try:
                sampled, finish = self._sample(prefix_ids, min(self.arm.chunk_tokens, maximum - len(selected)), "candidate")
                candidate = selected + sampled
                boundary = self._boundary(candidate)
            except InvalidSample as exc:
                candidates.append(selected)
                rewards.append([None] * self.arm.rollout_count)
                step["candidates"].append({"index": candidate_index, "invalid_request": self.request_index,
                                           "error": str(exc), "rewards": [None] * self.arm.rollout_count})
                continue
            if boundary is not None:
                candidate = candidate[:boundary[1]]
            empty_thinking = boundary is not None and boundary[0] == 0 and self._decode(candidate).startswith(OPEN_ACTION)
            if empty_thinking:
                empty_candidates.append(candidate_index)
            candidate_rewards = []
            request_ids = []
            for rollout_index in range(self.arm.rollout_count):
                if boundary is not None:
                    quality = self._quality(candidate)
                elif finish == "stop" or len(candidate) >= maximum:
                    quality = None
                else:
                    try:
                        rollout_maximum = maximum - len(candidate)
                        rollout_cap = getattr(self.arm, "max_rollout_tokens", 0)
                        if rollout_cap:
                            rollout_maximum = min(rollout_maximum, rollout_cap)
                        suffix, _ = self._sample(prompt_ids + [token.token_id for token in candidate], rollout_maximum, "rollout")
                        quality = self._quality(candidate + suffix)
                    except InvalidSample:
                        quality = None
                    request_ids.append(self.request_index)
                candidate_rewards.append(quality)
            candidates.append(candidate)
            rewards.append(candidate_rewards)
            step["candidates"].append({"index": candidate_index, "token_ids": [token.token_id for token in candidate],
                                       "rollout_request_ids": request_ids, "rewards": candidate_rewards,
                                       "empty_thinking": empty_thinking,
                                       "terminal_thinking": boundary is not None})
        if empty_candidates and not any(value is not None for group in rewards for value in group):
            weights = tuple(1 / len(empty_candidates) if index in empty_candidates else 0.0
                            for index in range(len(candidates)))
            step["selection_mode"] = "empty_thinking_uniform"
        else:
            weights = reward_weights(rewards)
        choice = categorical_index(weights, self.rng)
        selected = candidates[choice]
        step.update(selected=choice, weights=list(weights), ess=effective_sample_size(weights))
        print(json.dumps({"event": "thinking_is_step", "round": self.round_index,
                          "step": len(round_record["steps"]), "selected_tokens": len(selected), "ess": step["ess"]}), flush=True)
        return selected

    def _decision(self, full, finish, prompt_ids, round_record):
        text = self._decode(full)
        eos = next((ending for ending in EOS_TEXTS if text.endswith(ending)), None)
        if eos is not None:
            if self._decode(full[-1:]) != eos:
                raise ValueError("termination marker is not a complete sampled EOS token")
            text = text[:-len(eos)]
        round_record.update(selected_output_tokens=len(full), action_finish_reason=finish,
                            selected_token_ids=[token.token_id for token in full], content=text)
        model_config = self.factory.mini_config["model"]
        try:
            actions = parse_regex_actions(text, action_regex=model_config["action_regex"],
                                          format_error_template=model_config["format_error_template"],
                                          template_kwargs={"finish_reason": finish})
            selected_messages = ({"role": "assistant", "content": text,
                                  "extra": {"actions": actions, "thinking_is_round": self.round_index}},)
            kind = "action"
        except FormatError as exc:
            selected_messages = tuple(exc.messages)
            kind = "format_error"
        round_record["parser_valid"] = kind == "action"
        scored = full[:-1] if eos is not None else full
        return SampledDecision(
            kind=kind, messages=selected_messages, logprob=sum(token.logprob for token in scored),
            token_logprobs=tuple(token.logprob for token in scored), tokens=tuple(f"token_id:{token.token_id}" for token in scored),
            input_tokens=len(prompt_ids), output_tokens=len(full), raw_output_tokens=len(full), dropped_hidden_tokens=0,
            request_id=f"thinking-is:round:{self.round_index}", response_id="composite-selected-prefix",
            response_model=self.model, system_fingerprint=self.diagnostics["requests"][-1]["response"].get("system_fingerprint", ""),
            finish_reason=finish, scored_output_tokens=len(full), unscored_output_tokens=0,
            termination_logprob=full[-1].logprob if eos is not None else None,
            termination_status="scored" if eos else "deterministic_length" if finish == "length" else "unscored",
            power_target_exact=False, logprob_mode="visible_tokens", cost=0.0,
        )
