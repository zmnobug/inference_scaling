# Qwen3.8-27B x LiveCodeBench-v6: Conditional IS 实验方案

状态：IS 两组继续暂停；2026-09-16 用户授权 baseline 在独立 worker=2 配置下继续全量，旧 v6 目录不追加结果<br>
协议版本：`qwen38-lcb-is-v6`<br>
随机种子：`20260914`

阶段性结果与暂停位置：`docs/reports/QWEN38_LIVECODEBENCH_IS_INTERIM_20260916.md`。

Baseline 单组续跑计划：`docs/experiments/QWEN38_LIVECODEBENCH_BASELINE_FIRST.md`。

本实验保留原始在线分块 Conditional IS 设计。MATH-500 报告仅用于确定可兼容的基础采样、模型长度上限和 Consilience 参数，不把算法替换为整序列一次 SIR。

## 1. 三组对照

| 组别 | 标识 | 定义 |
| --- | --- | --- |
| Baseline | `baseline` | thinking 模式下单次普通生成，不执行 IS |
| Thinking IS | `is_thinking` | thinking 阶段使用 Consilience Conditional IS，遇到 `</think>` 后按基础分布单次生成正文 |
| Thinking + 正文 IS | `is_thinking_content_logprob` | thinking 阶段与上一组相同；正文阶段继续执行 Conditional IS，奖励改为正文序列 logprob |

所有 IS 阶段均保留以下原始多步流程：

```text
在当前已选前缀后生成 M=4 个候选短块
-> 每个候选生成 K_rollout=2 条条件补全
-> 根据该阶段 rollout 奖励计算候选权重
-> 按权重随机选择一个候选块并追加到前缀
-> 进入下一步，直到阶段停止边界、EOS 或达到阶段长度上限
```

两个 IS 组的 thinking 阶段使用完全相同的配置和 seed。第三组在 `</think>` 后裁掉吸收态 padding，以 `prompt + selected_thinking` 作为新 prompt，并把 `L - selected_thinking_tokens` 作为正文阶段长度上限。若 thinking 未闭合，则不启动正文阶段，也不提交不完整 thinking 作为代码。

正文组采用已确认的 A 方案：候选概率为正文完整序列 logprob 奖励经 `tau=10` 缩放后的 Conditional-IS 权重，再按该分布随机选择；不是直接选择 logprob 最大的候选。任何候选选择都不读取公开或私有测试。

## 2. 正式参数

| 参数 | 值 |
| --- | ---: |
| 完整回答最大长度 `L` | `131072` token |
| 单个题目 × 方法硬超时 | `1800` 秒 |
| Conditional IS 块长 `B` | `13107` token |
| 块长比例 | `B = 10% x L` |
| 单阶段最大 IS 步数 | `11`；两阶段因在边界处重新分块，合计最多 `12` |
| 候选数 `M` | `4` |
| 每候选 rollout 数 `K_rollout` | `2` |
| rollout 设计 | `iid` |
| 采样温度 | `1.0` |
| `top_p` | `1.0` |
| `top_k` | 禁用 |
| thinking 奖励 | `consilience`，温度 `2.0` |
| 正文奖励 | `sequence_log_probability`，scale `1.0`，温度 `10.0` |
| thinking 边界检测块长 | `256` token |
| API 并发 worker | `1` |
| 相同前缀 top-5 logprob 校验阈值 | `0.125` |

`L` 是 prompt 之后模型完整输出的上限，包含 thinking、`</think>`、final content 和 EOS。它不是实际必然生成长度，也不是总模型前向计算量。`133120` 不是回答长度，而是 `2048` prompt 加 `131072` 输出所需的服务上下文下限；模型 checkpoint 的原生上下文仍为 `262144`。

模型原生上下文为 `262144`。正式数据的 prompt 被限制在 `2048` token 内，因此服务至少需要：

```text
prompt_tokens <= 2048
L = 131072
service max_model_len >= 131072 + 2048 = 133120
B = round(0.1 x L) = 13107
```

当前运行中的服务已按正式协议重建为 `max_model_len=133120`。Runner 会在生成前检查 `/v1/models` 返回的上下文长度；若服务低于该值则在提交生成前中止。

## 3. 与 MATH-500 报告的关系

从 `docs/reports/QWEN3_MATH500_REASONING.md` 继承：

- 长回答仍必须受模型原生 `262144` token 上下文约束。
- 完整词表采样，不启用 top-p/top-k 截断。
- Consilience 使用 top-5、20% 窗口、跳过开头 5%、初始窗口系数 3、score temperature 1。
- Consilience reward temperature 为 `2.0`。

报告的生成温度 `0.6` 不直接继承。当前 OpenAI 后端从生成响应缓存 processed top-5 概率用于 Consilience；奖励的 `score_temperature=1.0`，因此生成也必须使用 `temperature=1.0`，否则缓存策略不一致且无法精确重评分。后续若增加独立的全词表评分后端，再单独注册 `temperature=0.6` 的协议。

本实验将 `131072` 定义为完整回答长度 `L`，而不是报告中的总前向 token 预算。报告使用的是四条完整候选加一次 SIR；本实验每一步还有 `4 x 2` 条条件 rollout，并且逐块重复执行，两者的成本结构不同。

因此：

- `L=131072` 要求服务上下文至少为 `133120`，不能继续使用当前 32K 服务配置。
- `131072` 不能在保持 `M=4、K=2、B=13107` 的同时再作为严格总计算上限。
- 正式结果必须报告实际生成 token、逻辑前向 token 和墙钟，而不能声称与报告的 131K 档等计算量。

## 4. 分阶段奖励

### 4.1 Thinking: Consilience

| 参数 | 值 |
| --- | ---: |
| scope | `thinking` |
| top-logprob 数 | `5` |
| 开头跳过比例 | `0.05` |
| 初始/末尾窗口比例 | `0.2` |
| 初始窗口系数 | `3.0` |
| score temperature | `1.0` |
| reward scale | `1.0` |
| reward temperature | `2.0` |

正常情况下仅对 `<think> ... </think>` 内的 token 计算 Consilience。thinking 尚未闭合或分段失败时，按现有奖励实现回退到当前可用完整序列，并记录回退原因。

### 4.2 正文: Sequence Log Probability

| 参数 | 值 |
| --- | ---: |
| scope | `</think>` 后的正文 token |
| reward | `sum(log p(token_t | prefix, token_<t))` |
| reward scale | `1.0` |
| reward temperature | `10.0` |
| candidate selection | reward-weighted categorical resampling |

正文阶段把已完成的 thinking 放入固定 prompt，因此 reward 求和只覆盖正文候选及其 rollout，不重复奖励 thinking。所用 token logprob 来自同一 vLLM 生成响应返回的 processed logprob，并由后端缓存；不调用判题器，不使用测试答案，也不增加独立模型评分请求。

## 5. 模型与服务

| 项目 | 值 |
| --- | --- |
| 模型 | `Qwen/Qwen3.8-27B` |
| Revision | `1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0` |
| 本地权重 | `/data/users/jenkins/qwen38-models/Qwen3.8-27B` |
| GPU | `4,5,6,7`，tensor parallel 4 |
| 精度 | FP16 |
| API | `http://127.0.0.1:8000/v1` |
| Served name | `qwen3.8-27b` |
| 单请求及单 case 超时 | `1800` 秒 |

正式运行前服务必须显式使用：

```text
--generation-config vllm
--logprobs-mode processed_logprobs
```

API worker 固定为 1。串行服务在 `abc388_d` 上可重复出现
`top_delta=0.0781231`，超过 v5 的 `0.0625` 校验阈值，而选中 token 的
`selected_delta` 仅为 `1.9072e-06`。v6 将校验阈值放宽为 `0.125`；该阈值
只控制相同前缀概率缓存的一致性保护，不改变采样、IS 或奖励参数。代价是允许
top-5 logprob 在更宽范围内波动，Consilience 权重的跨次运行复现误差可能增加。

## 6. 数据与评测

- 数据：`data/livecodebench/test6.jsonl`，LiveCodeBench v6 新增的 175 题。
- 难度：Easy 43、Medium 52、Hard 80。
- 每题每组生成一次正式结果。
- 判题镜像：`inference-scaling/lcb-judge:28fef95`。
- 每个测试超时 6 秒，每份代码总墙钟上限 180 秒。
- 主指标：通过全部测试的题数除以 175。

生成与判题分阶段执行，避免候选选择接触测试结果。结果同时记录 Wilson 95% 区间、thinking/正文 IS 步数、实际前向 token、墙钟和三组之间的题目级配对差异。

每个“题目 × 方法”在独立子进程中运行。超过 30 分钟时父进程先发送 TERM，10 秒后仍未退出则发送 KILL；该条记录为 `generation_timeout`、按未通过计数，然后继续下一条。超时进程没有可靠的完整后端计数，因此汇总前向 token 均值时排除该条并单独报告 timeout 数量。

## 7. 文件与命令

正式配置：`configs/qwen38_livecodebench_is.toml`<br>
Runner：`experiments/arllm/qwen38_livecodebench_is.py`<br>
服务脚本：`experiments/arllm/qwen38_livecodebench_server.sh`<br>
默认输出：`results/livecodebench_qwen38_is_v6`

v6 从 v5 迁移最初 12 条生成记录，其中 8 条正常结束、4 条生成超时。
8 条正常记录在更严格的 `0.0625` 阈值下完成；4 条超时记录按失败保留，
不能称为通过了完整校验。迁移时保留原始记录及其 v5 manifest fingerprint，
后续记录使用 v6 manifest fingerprint，以明确记录来源。

重建正式服务并等待健康检查：

```bash
experiments/arllm/qwen38_livecodebench_server.sh recreate
```

生成全部三组：

```bash
/home/jenkins/anaconda3/bin/conda run -n zm_qwen python \
  experiments/arllm/qwen38_livecodebench_is.py \
  --stage generate --limit 175
```

生成完成后判题并汇总：

```bash
/home/jenkins/anaconda3/bin/conda run -n base python \
  experiments/arllm/qwen38_livecodebench_is.py \
  --stage judge --limit 175
/home/jenkins/anaconda3/bin/conda run -n base python \
  experiments/arllm/qwen38_livecodebench_is.py \
  --stage summarize --limit 175 --require-complete
```
