# LiveCodeBench 严格 Think-only Inference Scaling 方案

本文定义 Qwen3.8-27B 在 LiveCodeBench code-generation 场景上的首版实验。目标是只对显式
thinking 区间执行 conditional importance sampling（IS），最终 Python 答案由选中的 reasoning
前缀继续普通采样一次。本文是实现规范和实验预注册，不包含结果。

## 1. 实验问题

比较三类方法在相同模型、题目、prompt、sampling policy 和总输出预算下的 pass@1：

| Family | Scaling 区间 | Reward 输入 | 答案生成 |
| --- | --- | --- | --- |
| `base` | 无 | 无 | 一次普通完整生成 |
| `full-is` | thinking + 正文 | 完整 sampled output | 属于 IS 序列 |
| `think-is` | 仅 thinking，含 `</think>` | 仅完整 thinking | 选中后普通采样一次 |

主问题是 strict think-only 相比 Base 和原 full-output IS 是否提高功能正确率，以及收益是否值得额外
forward token slots。结论只适用于具有可见 `<think>...</think>` token 流的模型，不推广到隐藏
reasoning 或无 think 模式模型。

## 2. 数据与官方评测

- 数据仓库：`livecodebench/code_generation_lite`；
- 固定版本：`release_v6`，预期 1055 题；
- 场景：code generation；
- 语言/输出：Python，使用题目自带 starter code 或 stdin/stdout 格式；
- 主指标：官方执行器对 public + private tests 得到的 pass@1；
- 官方 runner 固定 revision：`28fef95ea8c9f7a547c8329f2cd3d32b92c1fa24`。

准备脚本把远端 release 物化为本地 JSONL，并在 manifest 中记录快照 SHA-256。后续生成和评测都只
读取该快照，不能在实验中自动追随 `release_latest`。数据 release tag 与本地 SHA 同时构成数据身份。

模型输出按官方 generic/chat 规则抽取最后一对代码 fence 中的内容。无完整 fence 时 extracted code
为空，pass@1 计错，不进行启发式修复。运行评测前还会断言本地预览与固定官方 extractor 完全一致。

## 3. 严格 Think-only 目标

记渲染后的 prompt 为 $`x`$，含结束标记的 sampled reasoning 为 $`r`$，最终正文为 $`a`$：

```text
prompt | <think> reasoning </think> | final answer/code | EOS
       |<------ scaling 区间 ------>|<--- base sample --->|
```

共享总输出上限固定为 $`L=1024`$。有效 reasoning 必须在该上限内以 reasoning-end token 结束，
且结束前没有模型 EOS。对有效 $`r`$：

```math
\ell_r(x,r)=\sum_{t=1}^{|r|}\log p(r_t\mid x,r_{\lt t}),
\qquad R_r(x,r)=c\ell_r(x,r).
```

strict think-only 联合目标为：

```math
\pi_\alpha(r,a\mid x)
=\frac{\mathbf 1[r\in\mathcal D_L]p(r\mid x)^\alpha}{Z_\alpha(x)}
\,p(a\mid x,r),
\qquad \alpha=1+\frac{c}{\tau}.
```

初版固定 $`c=1`$、$`\tau=10`$、$`\alpha=1.1`$。reward 类型与原实验相同，仍是
`SequenceLogProbabilityReward`；改变的只是 reward 的 token 所有权：它只能看到完整 reasoning，不能
看到答案 token、代码执行结果或 gold tests。

候选和 rollout 同时把模型 EOS 与 reasoning-end token 作为终止事件。reasoning-end token 被保留在
序列中并覆盖其生成 logprob。v1 要求它是单 token 且不同于 EOS。

未闭合、EOS-before-close 或 logprob 非有限的 rollout 目标质量为零。每个候选仍以固定 $`K`$ 为 Monte
Carlo 分母，不补采样、不只对有效项重新平均。一步中所有候选都为零质量时记录
`no_valid_reasoning_rollout`，不回退 Base，也不生成答案。
这类算法失败以及 `reasoning_length`、`answer_budget_exhausted` 都固定计错；即使不完整 reasoning 中
偶然包含代码 fence，也不能送去执行并获得 pass。

## 4. 答案阶段与 1024 共享预算

reasoning 闭合后只发起一次答案请求：

```text
answer_prefix = rendered_prompt_tokens + selected_reasoning_tokens
answer_max_new_tokens = 1024 - len(selected_reasoning_tokens)
```

答案请求只使用真实模型 EOS，不再使用 reasoning stop token，不重新套 chat template，也不调用
reward。reasoning 已用满 1024 时记录 `answer_budget_exhausted`。最终送入官方代码 extractor 的文本是
`selected_reasoning + answer`，因此代码 fence 必须出现在答案正文中。

Base 与 full-output IS 也只有 1024 sampled tokens。think-only 不能在 reasoning 的 1024 之外再获得
独立的 1024 答案预算。

## 5. IS 配置

两类 IS 使用同一组 chunk ratio：

| Ratio | Chunk tokens | 名义最大步数 |
| ---: | ---: | ---: |
| 0.125 | 128 | 8 |
| 0.25 | 256 | 4 |
| 0.5 | 512 | 2 |
| 1.0 | 1024 | 1 |

固定参数为 $`M=4`$ candidates、$`K=2`$ iid on-policy rollouts、temperature 1、top-p 1、无
top-k、无 reward clipping、无 exact early stop。on-policy correction 恒等，但保留原 correction 配置以
审计目标。初版不实现 MH、proposal model 或隐藏 reasoning API。

## 6. 数据分区与冻结

使用 `platform x difficulty` 九个 strata 做 seeded round-robin 抽样，stratum 内按
`SHA256(dataset_seed, phase, question_id)` 排序。三个分区互斥：

| Phase | 题数 | Arms | 用途 |
| --- | ---: | ---: | --- |
| `probe` | 8 | 1 | Base reasoning closure gate |
| `screen` | 12 | 9 | Base + full-is 四 ratio + think-is 四 ratio |
| `confirm` | 8 | 5 | Base + 两个 family 各自冻结 top-2 |

`smoke` 默认取 screen 的第一题并运行全部 9 arms，只验证端到端结构，不参与选择。

### Closure gate

probe 中至少 7/8 个 Base 输出必须在 1024 内出现有效 `</think>`，才能运行 screen/confirm。失败时不
自动增大预算。修改总上限必须换实验 tag 并重新跑 probe。

### Screen 与 blind confirm

screen 分别在 `full-is` 和 `think-is` family 内冻结 top-2。排序依次使用：pass@1、较少总 forward
token slots、较短总墙钟、较高 `ESS/M`。冻结文件记录数据/模型/协议/边界 fingerprint。

confirm 只能读取冻结文件并运行 Base + 4 个冻结 arms。每个 family 内先看 confirm 正确数；相同则看
screen+confirm pooled 正确数；仍相同再按成本和离 0.25 最近的预注册规则决胜。两个 family 的赢家
最后与 Base 做题目级配对比较。

8/12/8 是工程验证规模，置信区间会很宽。若用于正式论文结论，应在不看结果的前提下预先扩大
confirm_count 或跑完整 release_v6，并使用新的 tag；不能把 screen 样本当 blind confirm。

## 7. 生成与评测隔离

GPU 生成进程不会执行模型代码，只写 `records.jsonl` 和 `generation_summary.json`。CPU 评测入口再用
固定官方 checker 生成 `evaluated_records.jsonl` 与 `summary.json`。

LiveCodeBench checker 会执行不可信 Python。它必须运行在无凭据、无宿主敏感挂载、限制网络/CPU/内存/
进程数的隔离 worker 或容器中。评测命令要求显式传入 `--allow-code-execution`；该 flag 只是确认，不是
额外 sandbox。

## 8. 产物

```text
results/livecodebench/livecodebench-qwen38-27b-strict-think-only-is-v1/<tag>/
  reasoning_closure_gate.json
  frozen_top2.json
  dataset_probe.jsonl
  dataset_screen.jsonl
  dataset_confirm.jsonl
  <phase>/manifest.json
  <phase>/records.jsonl
  <phase>/generation_summary.json
  <phase>/evaluated_records.jsonl
  <phase>/summary.json
```

每条记录保存完整输出、代码抽取预览、reasoning/answer token 计数、结束原因、reward token 覆盖、候选
权重、ESS、forward token slots、墙钟和 checkpoint fingerprint。答案 token 只能出现在诊断字段，不能
进入 reward 或 candidate log weight。

## 9. 运行顺序

安装准备依赖并物化固定数据与 evaluator：

```bash
python -m pip install -e '.[gpu,vllm,livecodebench]'
python experiments/arllm/prepare_livecodebench.py
```

先跑 smoke，再依次生成和评测 probe、screen、confirm：

```bash
python experiments/arllm/livecodebench_think_only.py --phase smoke --model /path/to/checkpoint

python experiments/arllm/livecodebench_think_only.py --phase probe --model /path/to/checkpoint
python experiments/arllm/evaluate_livecodebench.py --phase probe --allow-code-execution

python experiments/arllm/livecodebench_think_only.py --phase screen --model /path/to/checkpoint
python experiments/arllm/evaluate_livecodebench.py --phase screen --allow-code-execution

python experiments/arllm/livecodebench_think_only.py --phase confirm --model /path/to/checkpoint
python experiments/arllm/evaluate_livecodebench.py --phase confirm --allow-code-execution
```

相同配置和 tag 可断点续跑；manifest fingerprint 不一致时必须使用新 tag。所有生成阶段必须使用同一个
本地 checkpoint 路径，评测阶段必须使用与生成 manifest 一致的数据快照和官方 runner revision。
