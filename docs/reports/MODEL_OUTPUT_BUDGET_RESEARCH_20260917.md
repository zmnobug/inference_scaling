# 模型与 SWE-bench 实验输出预算调研

日期：2026-09-17。本文是调研和下一轮候选建议，不修改正在运行的随机 100 题 baseline 协议。

## 1. 必须分开的上限

| 参数 | 限制对象 | 本项目当前含义 |
| --- | --- | --- |
| vLLM `max_model_len` | 单次输入与输出之和 [S1] | `133120`，包括历史和工具 observation |
| vLLM/API `max_tokens` | 单次生成的新 tokens [S2] | 当前由上下文与累计剩余预算动态限制 |
| Transformers `max_new_tokens` | 本次新生成 tokens，不含 prompt [S3] | 与单轮生成预算对应，不等于整题累计预算 |
| Transformers `max_length` | 对 decoder-only 生成限制总序列长度 | 不宜与 `max_new_tokens` 混用；官方推荐用后者控制新增输出 [S3] |
| 项目 `L` / `max_trajectory_output_tokens` | 一道题多轮选中回答的累计输出 | `131072`，不包括工具 observation 或未选候选、rollout |
| IS `chunk_tokens` | 一次候选扩展的短块 | 方案为当前阶段可用输出预算的 10%，不是模型上下文 |
| `step_limit` / wall time | Agent 步数与实际求解时间 | `250` 步、`1800` 秒，与 token 预算独立 |

特别注意：当前 baseline TOML 复用了名为 `chunk_tokens` 的字段，值为 `131072`；在 baseline 中它只是
单次请求的输出天花板，没有 IS 分块语义。下一版可把单轮上限与 IS chunk 配置分开命名，避免误读。

## 2. 官方资料说明了什么

- vLLM 把上下文定义为 prompt 与 output 总长度；单轮输出最大值另由 sampling 参数控制。[S1][S2]
- Transformers 推荐用 `max_new_tokens` 控制新增输出，不把 prompt 长度算进去。[S3]
- mini-swe-agent 固定 commit 的 SWE-bench 默认配置设 `step_limit=250`、`cost_limit=3`，
  但没有给所有模型统一规定一个单轮 `max_tokens`。不能把项目自己的 L 当作 mini-swe-agent 标准。[S4]
- Qwen3.8-27B 模型卡对内部 QwenSWEBench 公布 `max_tokens=32768`、256K 上下文、8 小时截止，
  使用 Claude Code harness。这是具体 agent 评测例子，不是 Verified + mini-swe-agent 官方复现参数。[S5]
- 同一模型卡还给出在 1M 上下文、支持分离预算的框架下使用 reasoning `262144`、final `131072`
  的超长任务建议。它与上一条用途不同，不能直接移植到本机 133120 上下文，更不能把 final 预算
  等同于本项目跨轮次累计 L。[S5]

因此不存在适用于所有模型和任务的“官方统一输出上限”；须同时固定任务、thinking 模式、agent 和硬件。

## 3. 本机实际用量

从现有 `record.json` 的请求级诊断统计，分位数使用 nearest-rank。
百题数据快照时间为 2026-09-17 23:32:24，仅纳入当时正常提交的轨迹，不包括仍在运行或报错的响应。

| 指标 | 已判题的五题 smoke | 百题实验前六个正常提交实例 |
| --- | ---: | ---: |
| API 调用数 | 158 | 157 |
| 单次输出 P50 | 127 | 112 |
| 单次输出 P95 | 822 | 467 |
| 单次输出 P99 | 1160 | 815 |
| 最长单次输出 | 1441 | 1035 |
| 最大单题累计输出 | 17371 | 7932 |
| 最大单次输入 | 32802 | 18332 |
| 单次输出超过 8192 | 0 | 0 |
| `finish_reason=length` | 0 | 0 |

这只能说明已观察到的可见 THOUGHT/XML 成功轨迹远未用到超长单轮额度，不能证明所有题或原生长 thinking
都只需要这么多 token。前六题还集中于 Astropy，不能当作全量分布。先前的独立 reasoning 无 logprobs
错误是适配问题，不是输出长度耗尽；单纯提高或降低 token 上限不能补齐缺失的 logprobs。

2026-09-18 的后续回放进一步确认：旧错误提示不能证明 logprobs 确实缺失，适配器曾无条件拒绝拆分的
reasoning 字段；完整评分存在时现已支持严格还原，详见 [兼容修复报告](QWEN38_SWEBENCH_RANDOM100_THINKING_IS_BASELINE_COMPARISON.md)。

## 4. 下一轮参数候选

以下是结合本机数据提出的工程建议，不是官方默认值或已经证实最优的配置。

| 参数 | 建议 |
| --- | --- |
| 上下文 | 先保持 `133120`，不在百题中途改变 |
| 单次完整输出 | 当前可见 THOUGHT/XML 流程下一轮先验证 `16384`；`8192` 作为节省预算的对照 |
| 原生长 thinking | 先解决 reasoning 返回和 logprobs 的一致性，再以 `32768` 作为单轮试验起点；不能保证不截断 |
| 整题累计 L | 先保持 `131072`，不要同时改动多个预算维度 |
| 单题截止与步数 | 先保持 `1800` 秒和 `250` 步，等百题用时分布出来再决定 |
| IS chunk | 保持 10% 原则，但相对于引入单轮上限后的实际阶段预算计算 |

如果采用单轮 `16384` 的候选配置，动态预算应是：

```text
round_cap = min(16384, 133120 - prompt_tokens - 256, 131072 - selected_output_tokens)
chunk_tokens = max(1, round(0.10 * stage_remaining))
```

只有 `round_cap > 0` 才能发请求；thinking 与 action 必须共享本轮剩余额度，不能每进入一个阶段
都重新领取一份 16384。开始时完整可用预算为 16384 的阶段，其 10% chunk 为约 1638；可用预算为
32768 时约为 3277。选中前缀与 rollout 补全的合计不能超过该轮/阶段剩余预算。

10% 并不保证一定做十步 IS：若 thinking 在第一个 chunk 内结束，就只发生一次选择。观察到的可见
回答较短，因此后续还需统计每轮实际 IS 步数；不能把单步重采样误称为已验证了多步长推理搜索。

## 5. 怎样确定最终值

1. 跑完冻结的 100 题，分别统计单轮输出、整题输出和上下文的 P95/P99/最大值。
2. 将真正的长度截断、时间截止、上下文耗尽、格式错误和接口错误分开，不能统称“token 不够”。
3. 用独立校准样本验证单轮 8192/16384/32768 的候选，报告通过率与截断率，不只比较速度。
4. 冻结三组相同的公共预算后再正式对比；若按本轮结果调参，本轮应标为 pilot，避免当作独立确认集。
5. IS 的未选候选与 rollout 输出另计总前向开销，不能只报告 L 便声称三组算力相同。

`max_tokens` 是上限，不是每次必须生成的长度；正常 EOS/stop 可提前停止。[S2]
据此推论，如果实际只生成几百 token，把上限从 131072 降至 16384 并不会凭空减少其解码 token 数。
降低上限主要约束异常长生成的成本；性能是否改善仍需实测，不能许诺按上限比例加速。

## 来源

- [S1] vLLM Engine Arguments：`https://docs.vllm.ai/en/latest/configuration/engine_args/`
- [S2] vLLM SamplingParams：`https://docs.vllm.ai/en/latest/api/vllm/sampling_params/`
- [S3] Transformers Generation：`https://huggingface.co/docs/transformers/main/en/main_classes/text_generation`
- [S4] mini-swe-agent 固定配置：`https://raw.githubusercontent.com/SWE-agent/mini-swe-agent/25941c89cfbc91eb40b3f8756348c91d9977d57e/src/minisweagent/config/benchmarks/swebench.yaml`
- [S5] Qwen3.8-27B 官方模型卡：`https://huggingface.co/Qwen/Qwen3.8-27B`

本机数据分别来自 `results/swebench/qwen38-verified-random5-baseline-20260917/` 与
`results/swebench/qwen38-verified-random100-baseline-20260917/` 下的逐题记录。本次未改运行代码、配置或后台服务。
