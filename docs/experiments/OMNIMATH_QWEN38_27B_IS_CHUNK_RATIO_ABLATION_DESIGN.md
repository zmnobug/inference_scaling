# Omni-MATH Qwen3.8-27B 条件 IS Chunk Ratio 消融实验设计

本文定义一个低墙钟、可复现的自回归语言模型条件重要性采样（conditional importance sampling，
conditional IS）实验。实验使用 Qwen3.8-27B、完整序列 logprob 奖励和 Omni-MATH 高难度规则评测子集，
只消融生成块占总生成预算的比例。本文只规定实验语义、数据选择、参数、统计和验收门槛，不包含实验结果。

实验沿用 [GSM8K 运行与评测协议](GSM8K_EXPERIMENT_DESIGN.md) 的以下原则：质量比较使用相同题目和生成
长度，单次消融只改变一个参数，逐题结果可续跑，IS 同时报告权重 ESS、实际前向 token 位置、FLOPs 和墙钟。

## 1. 目标与结论边界

实验回答：在固定模型、采样策略、奖励目标、候选数、每候选 rollout 数和总生成长度时，哪个
`chunk_ratio` 在最终答案质量与自然计算成本之间表现最好？

主实验只改变 `conditional_is.chunk_ratios`。最终结论表述为：

> 在固定 Qwen3.8-27B 服务版本、Omni-MATH 子集、$`M=4`$、$`K=2`$、$`L=1024`$ 和
> $`\alpha=1.1`$ 的协议下，所测试比例中的经验最优 chunk ratio。

该结论不自动推广到其他模型、奖励尺度、候选/rollout 预算、生成长度或数据难度。小样本结果用于快速工程选型，
不能表述为全局最优或显著优于所有 chunk 设置。

## 2. 数据集与难度控制

### 2.1 数据来源

使用 [Omni-MATH-Rule](https://github.com/KbsdJames/omni-math-rule) 官方规则评测子集，而不是从 4,428 题的
原始 Omni-MATH 文件自行猜测哪些题可规则判定。数据和 evaluator 固定为 commit
`4793415ef37d31c9cdb4e5b82dbe172f76f8cf08`；`omni_math_rule.jsonl` 共 2,821 行，SHA-256 为
`d566d5b5a9865a04b507fdc4c0669cf0ff391748e13f190ecc925e78b584b172`。运行时拒绝 revision、数据哈希或
tracked evaluator 文件不一致的 checkout。

候选题必须同时满足：

- 题目只包含文本，不需要图片或外部工具；
- 单一最终答案，不使用证明题；
- 可由官方 rule-based evaluator 判定；
- 难度标签位于预先选定的区间；
- 不读取参考解答构造 prompt、reward 或候选权重。

题目按以下四个领域桶分层：

1. Algebra / Precalculus；
2. Number Theory；
3. Geometry；
4. Discrete Mathematics / Combinatorics。

桶内使用 `SHA256(dataset_seed | problem_id)` 排序。难度门控完成后，依次分配 probe、screen 和 confirm，
三个分区互斥。题目 ID 清单和清单哈希写入 manifest，禁止按模型单题表现手工换题。

### 2.2 独立难度门控

先从 difficulty 8--10 的候选池中按每个领域 2 题选取 8 道 probe 题，仅运行一次 Base。probe 不进入 chunk
排名。根据 Base 正确数按预注册规则确定主实验难度：

| Probe 正确数 | Screen / confirm 难度区间 | 原因 |
| ---: | --- | --- |
| `0--1 / 8` | difficulty 6--8 | 避免所有 arm 同时触底 |
| `2--6 / 8` | difficulty 8--10 | 保留可区分的中高难区域 |
| `7--8 / 8` | difficulty 9--10 | 避免强模型准确率触顶 |

该门控只选择预先定义的数据难度区间，不修改 IS 参数。manifest 必须保存 probe 题目、逐题结果、门控分支和最终
候选池哈希。

### 2.3 主数据分区

| 分区 | 题数 | 领域分配 | 用途 |
| --- | ---: | --- | --- |
| `probe` | 8 | 每桶 2 题 | 只选择难度区间 |
| `screen` | 12 | 每桶 3 题 | 排出 top-2 ratio |
| `confirm` | 8 | 每桶 2 题 | 冻结参数后的独立确认 |

screen 的前两题兼作端到端 smoke。只有代码、配置、模型服务和数据 revision 均未发生变化时，这两题才能保留；
任何语义性修复都必须更换 tag 并重新运行完整 screen。

## 3. 模型与生成协议

| 项目 | 固定值 |
| --- | --- |
| 模型 | `Qwen/Qwen3.8-27B`；以实际 API 请求名和响应名为准 |
| 推理模式 | thinking 开启，`reasoning_effort="medium"` |
| 总生成上限 $`L`$ | `1024` sampled output tokens，包括 reasoning 和最终答案 |
| 温度 | `1.0` |
| top-p | `1.0` |
| top-k | 禁用 |
| EOS | 固定 tokenizer 的 EOS ID |
| Prompt | 固定英文模板，要求逐步推理并以 `\boxed{}` 给出最终答案 |
| 候选/rollout 模型 | 同一个 Qwen3.8-27B checkpoint 和采样策略 |
| 外部工具 | 禁用 |

thinking 内容必须作为模型采样序列的一部分返回，并具有逐 token 有限 logprob。若服务端隐藏 reasoning token 或未返回
其 logprob，exact 模式 preflight 失败，不得把未评分 token 当作 0。可见 token-only 实验只能使用独立 tag，并明确标为
不同奖励目标，不能与主结果合并。

## 4. 目标分布与 Logprob 奖励

对 prompt $`x`$ 和完整生成 $`y`$，定义

```math
L_p(x,y)=\sum_{t\in\mathcal M(y)}\log p(y_t\mid x,y_{\lt t}),
\qquad r_{\log p}(x,y)=cL_p(x,y).
```

$`\mathcal M(y)`$ 包含所有实际采样并提交给解码器的 reasoning、答案和 EOS token；达到长度上限时没有 EOS 项。
主实验固定

```text
logprob_reward_scale c = 1.0
reward_temperature tau = 10.0
effective alpha = 1 + c / tau = 1.1
```

因此目标为

```math
\pi(y\mid x)\propto p(y\mid x)\exp\{r_{\log p}(x,y)/\tau\}
=p(y\mid x)^{1.1}.
```

必须使用完整序列累计 logprob 作为奖励。token 平均 logprob 只作为长度偏差诊断，不能在运行中替换奖励。累计
logprob 会偏向较短生成，因此结果必须同时报告生成长度、EOS 率和长度截断率。

## 5. 条件 IS 与固定参数

在已经生成的前缀 $`g`$ 后，每个引导步骤执行：

1. 从基础策略生成 $`M=4`$ 个候选块 $`z_m`$；
2. 对每个候选生成 $`K=2`$ 条独立 on-policy rollout 到 EOS 或总长度 $`L`$；
3. 计算

```math
\log \widehat h_m
=\mathrm{logmeanexp}_{k=1}^{K}
\left\{r_{\log p}(g,z_m,u_{mk})/\tau\right\};
```

4. 对 $`\log\widehat h_m`$ 做 log-space 归一化并重采样一个候选块；
5. 将选中块追加到前缀，直到 EOS 或 $`L`$。

主实验固定配置：

```toml
[generation]
max_new_tokens = 1024

[sampling]
temperature = 1.0
top_p = 1.0
# Omit top_k so hard vocabulary truncation is disabled.

[conditional_is]
candidate_count = 4
rollout_count = 2
rollout_design = "iid"
reward = "sequence_log_probability"
logprob_reward_scale = 1.0
reward_temperature = 10.0
# Omit importance_log_ratio_clip; candidates and rollouts are on-policy.
apply_importance_correction = true
exact_rollout_early_stop = false
rollout_evaluation_batch_size = 8
chunk_alignment_tokens = 8
chunk_ratios = [0.125, 0.25, 0.5, 1.0]
```

候选和 rollout 都来自同一策略，所以 $`p/q=1`$；不引入小 proposal 模型、off-policy 修正或权重截断。
`rollout_evaluation_batch_size` 和请求并发只影响执行，不是算法 batch，所有 arm 必须保持一致。

## 6. Chunk Ratio 定义与消融轴

`chunk_ratio` 是配置源参数，`chunk_tokens` 只是由总生成上限派生的运行值。对总长度 $`L`$、比例 $`r`$ 和
对齐单位 $`a=8`$，定义

```math
C(r,L,a)=\min\left\{L,\;a\left\lceil\frac{rL}{a}\right\rceil\right\}.
```

单步实际块长为 $`\min\{C,L-|g|\}`$。本实验中：

| Arm | `chunk_ratio` | 派生 `chunk_tokens` | 名义引导次数 `ceil(L/C)` |
| --- | ---: | ---: | ---: |
| `is-cr0125` | `0.125` | 128 | 8 |
| `is-cr0250` | `0.25` | 256 | 4 |
| `is-cr0500` | `0.5` | 512 | 2 |
| `is-cr1000` | `1.0` | 1024 | 1 |

`ratio=1.0` 是边界对照：它比较一次完整序列 SIR 与多阶段条件引导。终端候选没有未来 suffix，条件期望已经精确，
因此无需生成空 rollout；记录中仍保留配置的 $`K=2`$、每候选一次精确 reward contribution，以及实际 future
rollout generation 数 0。reward contribution 不能误报成一次模型生成。

每条记录必须同时保存配置比例、派生 token、每步实际块长、名义/实际引导次数。后续改变 $`L`$ 时仍使用相同比例，
不得直接复用本实验的整数 token 并称为同一配置。

## 7. 实验矩阵与执行顺序

### 7.1 Preflight

在运行数据集前验证：

- API 请求/响应模型名、服务端 revision 和 tokenizer revision 可记录；
- sampled token、解码文本和逐 token logprob 一致；
- thinking、答案、EOS 或长度终止的概率记账完整；
- 同一 seed 的批量与单请求采样语义一致；
- `score_batch` 对已采样序列的累计 logprob 与生成时累计值在容差内一致；
- `chunk_ratio` 到 `chunk_tokens` 的转换和最后一个短块正确。

### 7.2 Difficulty Probe

运行 8 个互斥 probe 题的 Base，根据第 2.2 节选择难度区间。该阶段不运行 IS，不进入质量排名。

### 7.3 Screen

在同一组 12 题和同一组根 seed 上运行：

| Arm | 题数 | 用途 |
| --- | ---: | --- |
| `base` | 12 | 固定 $`L=1024`$ 的基础策略参照 |
| `is-cr0125` | 12 | 8 次引导 |
| `is-cr0250` | 12 | 4 次引导 |
| `is-cr0500` | 12 | 2 次引导 |
| `is-cr1000` | 12 | 1 次引导边界 |

共 60 个 problem-arm，其中 48 个为 IS。完成后按第 9 节冻结 top-2 ratio；不得查看 confirm 结果后重新选择。

### 7.4 Blind Confirm

在 8 个互斥 confirm 题上只运行 Base 和冻结的 top-2 ratio，共 24 个 problem-arm。confirm 前写入一个包含
top-2、screen summary hash 和配置 fingerprint 的冻结文件；确认阶段不得调整比例、奖励尺度或其他 IS 参数。

## 8. 随机种子与配对

所有 arm 使用相同 `dataset_seed` 和相同题目顺序。每题根 seed 由
`SHA256(experiment_seed | problem_id)` 派生；候选和 rollout seed 再由方法、比例、引导步、候选下标和 rollout 下标
派生。不同 ratio 不要求产生逐 token 相同轨迹，但必须在题目层面配对。

重试复用同一 request ID 和 seed。基础设施失败可按固定次数重试；模型产生不可解析答案、EOS 过早或达到长度上限属于
方法结果，不能通过更换 seed 重跑到成功。

## 9. 指标、统计与最优参数判定

### 9.1 主要质量指标

- 官方规则评测的单次最终答案准确率（pass@1）；
- 每个 arm 的 Wilson 95% 区间；
- ratio 与 ratio、ratio 与 Base 的题目级配对准确率差及配对 bootstrap 95% 区间。

### 9.2 IS 与执行诊断

- 每步候选完整序列 logprob、log weight、归一化权重；
- `ESS/M`、最大权重和权重熵；
- 名义/实际引导次数，计划/完成/跳过/失败 rollout 数；
- selected output tokens、EOS 率、截断率和答案解析失败率；
- generation/score forward token slots、估算 dense FLOPs、共享 prefix KV 节省量；
- 模型服务时间、端到端墙钟、批次数和请求失败数。

若平均 `ESS/M < 0.25`，将该 arm 标记为权重退化；不自动修改 $`\alpha`$，因为那会破坏单因素消融。

### 9.3 预注册选择规则

1. 缺失完整 logprob、配置不一致或结果不完整的 arm 不进入排名；基础设施修复后使用新 tag 重跑。
2. Screen 首先按准确率选出 top-2；准确率相同则依次按较低前向 token slots、较低墙钟和较大 `ESS/M` 排序。
3. Confirm 中 top-2 的正确数决定质量最优 ratio，并同时报告配对差值。
4. Confirm 打平时，以互斥 screen + confirm 的 20 题 pooled accuracy 作预注册辅助判定。
5. pooled accuracy 仍相同时，选择总 forward token slots 较低者；成本差小于 10% 时选择更接近 `0.25` 的 ratio。
6. 无论哪个 ratio 胜出，都单独比较其与 Base 的准确率和成本；若未超过 Base，只能结论“该 ratio 是 IS arm 中最好”，
   不能声称 inference scaling 改善了质量。

报告同时给出“质量最优 ratio”和由准确率、forward token slots、墙钟构成的 Pareto 前沿，不把 reward 均值作为最终
质量指标。

## 10. 成本与快速停止

小 ratio 会增加引导次数，并反复生成较长 rollout，成本不会与 ratio 线性变化。所有 arm 使用自然成本，不按 token
强行配平；比较时报告 `IS / Base` 和各 ratio 相对 `ratio=1.0` 的成本倍数。

在模型已经加载、请求可批处理且无服务排队的前提下，预计 screen 需要约 1--3 小时，完整 confirm 后约 2--5 小时。
这只是容量规划范围；完成 screen 的第一个问题后，使用实际 forward token slots 和墙钟更新剩余时间估计，但不能根据
耗时改变 arm 或题目清单。

若只需要功能检查，可以在两道 smoke 题完成后停止；该结果不得用于选择最优 ratio。正式最优参数至少需要完整 screen，
推荐完成 blind confirm。

## 11. 结果、Manifest 与续跑

建议输出结构：

```text
results/omnimath/qwen38-27b-is-chunk-ratio-v1/
  <tag>/
  dataset_probe.jsonl
  dataset_screen.jsonl
  dataset_confirm.jsonl
  difficulty_gate.json
  frozen_top2.json
  probe/{manifest.json,records.jsonl,summary.json}
  screen/{manifest.json,records.jsonl,summary.json}
  confirm/{manifest.json,records.jsonl,summary.json}
```

manifest 至少记录：

```text
experiment_version, git_commit, implementation_sha256
model_request_name, model_response_name, server_revision
tokenizer_revision, thinking_config, prompt_sha256
dataset_repository, dataset_revision, dataset_file_sha256
probe/screen/confirm problem IDs and hashes
generation_config, sampling_config, conditional_is_config
chunk_ratios, derived_chunk_tokens, seed derivation version
reward definition, c, tau, effective alpha, logprob coverage mode
```

每个输出目录先原子写入 manifest；逐题结果以 `(arm, problem_index)` 唯一标识并逐行刷入 JSONL。续跑前先校验
manifest 中的配置、题目清单、数据哈希、模型 artifact 哈希和实现哈希，并拒绝重复记录；只有 fingerprint 一致的完整行
才会跳过。API key、私有 endpoint 和 authorization header 不进入结果。

## 12. 实现前验收门槛

进入 screen 前必须满足：

1. 数据 revision、规则评测代码和三个分区题目清单已固定；
2. prompt 不包含 gold answer、参考解答或难度说明；
3. 每个 sampled token 都有有限 logprob，完整序列求和可复核；
4. `sequence_log_probability` 的 scale、temperature 和有效 $`\alpha=1.1`$ 写入记录；
5. 固定表格后端上的 IS 权重、logmeanexp 和重采样测试通过；
6. 四个比例正确派生为 `128/256/512/1024`，最后一个短块不越过总长度；
7. 候选数、rollout 数、采样策略和请求并发在所有 ratio 间一致；
8. Base 与所有 ratio 使用相同 screen/confirm 题目；
9. ESS、生成/评分 token slots、FLOPs、墙钟和失败原因能够汇总；
10. 中断续跑不会混合不同配置或重复完整记录。

## 13. 主要风险

| 风险 | 处理 |
| --- | --- |
| Qwen3.8-27B 在所选难度上仍触顶或触底 | 使用互斥 Base probe 按预注册规则选择难度区间 |
| 累计 logprob 偏向短答案 | 目标保持不变，同时报告长度、EOS 和截断诊断 |
| 小 ratio 计算量快速增长 | 只测试 4 个几何比例，先完成两题 smoke，再运行完整 screen |
| thinking token 被隐藏或未评分 | exact preflight 失败；visible-only 只能作为独立实验 |
| $`\alpha=1.1`$ 仍导致权重退化 | 标记 `ESS/M < 0.25`，不在本消融内改奖励尺度 |
| 12/8 题统计区间较宽 | 使用配对统计和 blind confirm，将结论限制为工程选型 |
| 数据公开导致潜在训练污染 | 固定 revision 并披露限制，不把绝对准确率解释为无污染能力估计 |
| rule evaluator 对等价表达式误判 | preflight 覆盖代表性答案类型，保存原始输出和判定明细 |

## 14. 实现与运行入口

实现复用共享 SIR 核；数据集读取、官方答案判定、比例派生和实验冻结均留在实验层：

- 正式配置：`configs/omnimath_qwen38_27b_chunk_ablation.toml`；
- 本机 smoke 配置：`configs/omnimath_qwen3_8b_smoke.toml`；
- 数据准备：`experiments/arllm/prepare_omnimath_rule.py`；
- 实验入口：`experiments/arllm/omnimath_chunk_ablation.py`。

先安装本项目和规则 evaluator 的轻量依赖，然后准备固定上游 checkout：

```bash
python -m pip install -e '.[omnimath]'
python experiments/arllm/prepare_omnimath_rule.py
```

本机 Qwen3-8B 功能检查：

```bash
python experiments/arllm/omnimath_chunk_ablation.py \
  --config configs/omnimath_qwen3_8b_smoke.toml \
  --phase smoke \
  --tag local-flow-v1
```

服务器正式流程中，三阶段必须使用同一 `--tag`、模型路径和配置：

```bash
MODEL=/path/to/Qwen3.8-27B
TAG=qwen38-27b-chunk-v1

python experiments/arllm/omnimath_chunk_ablation.py \
  --config configs/omnimath_qwen38_27b_chunk_ablation.toml \
  --phase probe --model "$MODEL" --tag "$TAG"

python experiments/arllm/omnimath_chunk_ablation.py \
  --config configs/omnimath_qwen38_27b_chunk_ablation.toml \
  --phase screen --model "$MODEL" --tag "$TAG"

python experiments/arllm/omnimath_chunk_ablation.py \
  --config configs/omnimath_qwen38_27b_chunk_ablation.toml \
  --phase confirm --model "$MODEL" --tag "$TAG"
```

`probe` 自动写入 `difficulty_gate.json`；`screen` 按预注册规则写入 `frozen_top2.json`；`confirm` 自动读取
冻结比例并校验数据 SHA、模型 fingerprint、生成协议和除 ratio 外的固定 IS 参数。任一项变化都会拒绝续跑，要求使用新 tag。

## 15. 本机功能验证

2026-09-10 使用 `/home/jenkins/anaconda3/envs/zm_sm70`、单张 Tesla V100 32GB 和本地 Qwen3-8B 完成一题
三 arm smoke。配置为 $`L=32`$、$`M=2`$、$`K=1`$、ratio `0.5/1.0`，只用于控制流验证：

- sampled-token logprob 与 `score_batch` 重打分最大绝对差为 `0.0`；
- 最终代码复跑中，Base、ratio 0.5、ratio 1.0 分别用时约 `2.03s / 3.44s / 2.24s`；
- 派生 chunk 为 `16/32`，实际引导次数为 `2/1`；
- ratio 1.0 的 future rollout generation 为 `0`，但完整候选 reward 正常评分；
- 三条输出均因 32-token smoke 上限截断，准确率为 0，不能解释为质量结果；
- 原命令续跑时未重新加载模型，只读取完整记录并重建 summary。

功能验证同时发现并修复了一个共享边界条件：同一候选 batch 中第一个候选提前 EOS、其他候选未终止时，future
rollout 长度现在按最长候选块计算，不会越过 `total_length`。对应回归测试已加入 `tests/test_conditional_is.py`。

同日又以 `L=8`、`M=2`、`K=1` 完整执行了 `probe -> screen -> confirm` 控制流：

- probe 完成 8 个 Base 记录，并按 `0/8` 自动冻结 difficulty 6--8；
- screen 完成 12 题、36 个 problem-arm，生成并校验 `frozen_top2.json`；
- confirm 在 8 个互斥题上完成 24 个 problem-arm，读取冻结比例并生成最终决策；
- 三阶段合计 68 个 problem-arm，均成功写入 manifest、分区、逐题记录和 summary。

该流水线把生成长度压到 8，而 `chunk_alignment_tokens=8`，所以 ratio 0.5 和 1.0 都派生为 8-token chunk；所有答案
也都因长度上限截断。它只证明阶段交接、冻结、防混跑、官方 evaluator 和结果汇总可工作，不提供任何比例优劣证据。
