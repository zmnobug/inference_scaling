# SWE-bench Qwen3.8-27B API IS/MH 消融实验设计

本文档定义在 SWE-bench 原版 MiniAgent 上比较重要性采样（IS）和
Metropolis--Hastings（MH）的实验协议。模型使用已经部署的 `qwen3.8-27B` API，奖励只来自模型自身返回的
可见 token logprob。实验不引入其他 Agent harness、奖励模型、正确性 verifier 或训练过程。

本文只固定实验语义、消融矩阵、预算、统计与审计要求。MiniAgent 上游仓库 revision、API 的实际
`model` 字符串和 SWE-bench 数据 revision 必须在首次运行前写入配置与运行清单，不能依赖浮动默认值。

## 1. 实验目标

实验回答以下问题：

1. 在不改变 MiniAgent 行为的前提下，logprob 引导的 IS 或 MH 是否提高 SWE-bench resolved rate？
2. IS 的 `alpha`、候选 batch、chunk 和每候选 rollout 数怎样影响质量、有效样本量和 API 成本？
3. MH 的 `alpha`、每链更新数、proposal 后缀跨度和后缀调度怎样影响质量、接受率和 API 成本？
4. IS 与 MH 自然产生的 API token、请求数和墙钟开销分别是多少，质量--成本曲线如何？
5. 参数收益是否能在未参与调参的 SWE-bench 实例和独立随机种子上复现？

最终参数不按单次最高 resolved rate 决定。先在小规模调参集上逐级淘汰不稳定配置，冻结候选配置后，再在互斥的
确认集上比较。API token 不作为运行上限或成本配平条件，但必须完整记录；质量接近时同时报告 token、墙钟和失败率。

## 2. 固定范围

| 项目 | 固定规则 |
| --- | --- |
| 模型 | 已部署的 `qwen3.8-27B` API；保存请求使用的模型名及服务端返回的模型版本 |
| Agent | SWE-bench 原版 MiniAgent；固定上游 commit、prompt、工具、最大步数、总生成长度、超时和补丁提交逻辑 |
| Agent harness | 不接入其他 harness；只在 MiniAgent 的模型调用边界添加采样适配器 |
| 数据 | 主实验使用 SWE-bench Verified；运行前固定数据 revision 和实例 ID 清单 |
| 基础采样策略 | `temperature=1`、`top_p=1`、禁用 top-k；候选和 rollout 使用同一个 API 模型 |
| 奖励 | API 返回的可见生成 token 累计 logprob；不读取 gold patch、测试结果或任务标签 |
| 最终评测 | MiniAgent 产出的补丁按固定的 SWE-bench 官方评测流程计算 `resolved` |
| 工具环境 | Docker root filesystem checkpoint；每个候选 rollout、MH proposal 和独立链使用隔离的精确工作区状态 |
| 主输出 | 每个实例每个随机种子只提交一个补丁；pass@k 必须另列，不能混入 pass@1 |

官方 SWE-bench evaluator 是任务结果判定器，不是新增 Agent harness。它只在轨迹结束后评测最终补丁，不能把
中间测试结果作为 IS/MH 奖励。

### 2.1 明确不做的事情

- 不修改 MiniAgent 的系统提示、工具定义、命令执行规则、上下文压缩或终止条件。
- 不增加 SWE-agent、OpenHands 或其他 Agent 编排层。
- 不使用 gold patch、FAIL_TO_PASS/PASS_TO_PASS 结果或测试反馈作为采样奖励。
- 不使用第二个 proposal 模型，不做 off-policy IS，也不截断 importance ratio。
- 不把 API 请求并发数当成算法 batch 大小。
- 不以多条链中 logprob 最大的补丁作为 MH 输出；该做法属于 Best-of-N，不再是目标 MH 样本。
- 不把调参集上的最高点直接写成最终结论。

## 3. 概率目标与 logprob 奖励

令 `h` 表示当前 MiniAgent 历史，包括任务描述、此前 assistant action 和工具 observation；令 `y` 表示从该状态
开始直到终止的模型决策轨迹。工具输出作为条件上下文，不属于模型随机变量。轨迹 logprob 定义为

```math
L_{\mathrm{score}}(y\mid h)=\sum_{t\in\mathcal M(y)}\log p(y_t\mid h,y_{\lt t}),
```

其中 $`\mathcal M(y)`$ 只包含 API 实际采样的 assistant 文本和 tool-call token：

- 不计 system/user prompt、工具 observation 和服务端自动插入的文本；
- API 报告的每个可见 output token 都必须有有限 logprob，token 数不一致时请求失败；
- 若服务端另行返回有限的 EOS/stop `termination_logprob`，则 exact power 模式把它计入；只有 stop reason 时不伪造概率；
- token 文本、token ID（若 API 提供）和逐 token logprob 必须与最终提交给 MiniAgent 的 action 一致；
- 任一参与采样的 token 缺少 logprob、出现 `NaN`/`inf` 或响应被服务端改写时，该请求立即标记失败。

默认 `api.logprob_mode="visible_tokens"` 使用如下奖励倾斜目标：

```math
\pi_\alpha(y\mid h)
\propto p_{\mathrm{API}}(y\mid h)
\exp\{(\alpha-1)L_{\mathrm{score}}(y\mid h)\},
\qquad \alpha\ge 1.
```

因此 `alpha=1` 是原始基础 API 分布，IS/MH 都使用 `(alpha - 1) * L_score` 作为相对基础分布的 log reward。
当每个响应的可见 token 和随机终止事件都具有 logprob 时，可设置 `api.logprob_mode="power_target_exact"`，此时
$`L_{\mathrm{score}}=\log p_{\mathrm{API}}(y\mid h)`$，上式才严格化为 $`p_{\mathrm{API}}^\alpha`$。运行记录保存
`termination_status` 与 `power_target_exact`，不能把默认 visible-token 结果静默写成严格幂目标。

累计 logprob 会偏向较短的 action 和较短的 Agent 轨迹。这是当前累计 logprob 奖励倾斜的性质；在 exact 模式下也是
$`p^\alpha`$ 目标的性质。主实验不得在运行中改成 token 平均 logprob。结果必须同时报告模型生成长度、Agent 步数和
补丁大小；若以后研究平均 logprob，必须作为改变目标函数的独立奖励消融。

## 4. MiniAgent 接入边界

采样适配器只替换 MiniAgent 的一次模型调用：输入仍是 MiniAgent 构造的 messages/tool schema，输出仍是原版
MiniAgent 可消费的一条 assistant action。工具只能在 action 被正式选中后作用于主工作区。

IS 的候选 action 在隔离工作区中继续运行 MiniAgent rollout。MH 的正式 proposal 从一个已经保存的合法 action
边界恢复工作区，然后由原版 MiniAgent 继续生成到终止或该轨迹的总输出 token 上限。以下内容必须保持一致：

- prompt 和 tool schema 的字节内容；
- API sampling policy、stop 条件和最大上下文；
- MiniAgent 的工具执行器、超时、重试与错误处理；
- 初始仓库镜像、安装步骤和环境变量白名单；
- 最终 patch 的提取和提交方式。

每个隔离工作区必须从固定基础镜像或当前 action 边界的 immutable Docker checkpoint 创建。checkpoint 前校验容器没有
mount，因为 `docker commit` 不保存挂载数据；候选不能共享未提交文件、进程、端口或工具缓存。模型 API 可以共享，
但每个请求必须有唯一的实验 request ID。IS/MH 正式 profile 因而只支持 Docker environment。

## 5. IS 方法

在 MiniAgent 的一个决策点，IS 生成 $`B`$ 个候选 action/chunk $`z_m`$。每个候选在独立工作区中继续运行
$`R`$ 条 MiniAgent rollout 到终止或统一的轨迹长度上限，记第 $`k`$ 条完整后续轨迹为 $`(z_m,u_{mk})`$。候选的
log weight 为

```math
\log \widehat w_m
=\mathrm{logmeanexp}_{k=1}^{R}
\left[(\alpha-1)L(z_m,u_{mk}\mid h)\right].
```

按归一化后的 $`\widehat w_m`$ 重采样一个候选，并直接把已执行候选的容器和 MiniAgent 状态提升为主链；不得在旧主
容器中再次执行该 action。若算法在后续决策点继续使用 IS，则已选 action 的真实工具结果进入新的历史，未选候选
工作区全部关闭。

实现中的每个 rollout logprob 是候选 action 与其后续 action 的累计值；候选本身的 logprob 必须恰好计入一次，
既不能遗漏也不能在 suffix 中重复累计，否则就不再对应完整后续轨迹 $`(z_m,u_{mk})`$ 的奖励。

### 5.1 IS 消融参数

| 参数 | 配置名 | 初筛值 | 作用 |
| --- | --- | --- | --- |
| logprob 强度 | `alpha` | `1.0, 1.25, 1.5, 2.0, 4.0` | 控制高概率轨迹的偏好强度 |
| 候选 batch | `candidate_count` | `2, 4, 8` | 每个决策点比较的候选 action 数 |
| 完整轨迹长度 | `agent.max_trajectory_output_tokens` | `8192` | 每条 Base/IS rollout/MH chain 的累计模型输出 token 上限；对应原 GSM8K `generation.max_new_tokens` |
| action chunk 上限 | `chunk_tokens` | `410, 819, 1229`（约为总上限的 5%、10%、15%） | 单个候选 action 及每次后续 API 调用的最大生成 token 数；对应原 GSM8K `block_size` 的 action 化版本 |
| rollout 数 | `rollouts_per_candidate` | `1, 2, 4` | 每个候选的后续条件权重估计样本数 |

`agent.max_trajectory_output_tokens` 是一条完整 MiniAgent 轨迹的累计生成长度上限；达到后停止该轨迹。它不是成本
预算，实际 token 仍完整记录。当前总上限为 8192，IS chunk 取其 5%、10%、15% 并分别四舍五入为 410、819、1229；
`chunk_tokens` 是单次 API 调用的输出上限，也是一个候选 action 的最大长度，不是 API
transport batch。chunk 必须在 MiniAgent 可以解析的完整 assistant action 边界提交；达到 chunk 上限仍未形成合法 action
时，保留 `finish_reason=length`，沿用原版 MiniAgent 对截断响应的处理，不得用人工规则挑选或修补。

### 5.2 IS 诊断量

每个决策点至少保存：

- 候选原始 logprob、rollout logprob、log weight 和归一化权重；
- 权重 ESS：$`1/\sum_m \bar w_m^2`$；
- 最大权重、权重熵、被选候选下标；
- 计划/完成/失败的 rollout 数；
- 每个候选与 rollout 的输入/output token、请求数、墙钟和工具调用数。

`alpha=1` 时所有有限 log weight 应相等。该条件是实现检查，不要求与 Base 在相同 seed 下逐 token 一致。

## 6. MH 方法

正式 MH 以一条完整 MiniAgent 轨迹及其工作区为链状态。初始化由原版 MiniAgent 基础策略产生。一次 proposal：

1. 按 `suffix_schedule` 从当前轨迹的合法 assistant action 边界选择切点 $`c`$；
2. 恢复该切点对应的隔离工作区快照；
3. 保留切点前的 MiniAgent 历史，从 `qwen3.8-27B` API 反复生成 action 并执行工具，直至终止或达到该轨迹的
   `agent.max_trajectory_output_tokens` 总生成上限；
4. 计算当前后缀和 proposal 后缀的累计模型 logprob；
5. 按完整 Hastings 比接受或拒绝；拒绝时恢复当前链状态和工作区。

若切点调度的正反概率分别为 $`\rho(c\mid y)`$ 和 $`\rho(c\mid y')`$，proposal 与目标模型相同，则

```math
\log A=\min\left\{0,
(\alpha-1)(L_{\mathrm{new\ suffix}}-L_{\mathrm{old\ suffix}})
+\log\rho(c\mid y')-\log\rho(c\mid y)
\right\}.
```

只有在正反切点概率相同时才能省略最后两项。实现必须记录原始目标差、正反 proposal 概率和最终
`log_acceptance`，不能根据经验接受率修改接受公式。

对包含 $`J`$ 个 assistant action 的当前轨迹，`max_suffix_actions=d` 表示切点只从最后至多 $`d`$ 个旧 action
边界中选择；它不截断新后缀，新后缀仍由 MiniAgent 反复调用 API 并运行到终止或统一的轨迹总生成上限。`full` 总是从初始 action 边界重生成；
`uniform` 在可用切点上均匀分布；`inverse_length` 偏向较短旧后缀；`multiscale` 同时给局部、二次幂跨度和完整
后缀分配概率。proposal 改变轨迹 action 数后，必须在新轨迹上重新计算同一切点的反向概率；反向概率为零时该
proposal 必须拒绝。

历史工具操作不从基础镜像重放。运行时在每个合法 action 边界保存 root filesystem 与 MiniAgent message/counter 状态，
proposal 直接从切点 checkpoint 启动；接受时提升 proposal 状态，拒绝时保留当前状态。网络访问、系统时间和遗留后台
进程等非 checkpoint 输入必须关闭或记录。只在尚未执行的单条 action 内做局部 MH 可以用于 API smoke，但它只采样局部
action 奖励倾斜目标，不等于完整 Agent 轨迹目标，不能混入正式质量表；只有 exact 模式下才能把该局部目标写成
$`p(a\mid h)^\alpha`$。

### 6.1 MH 消融参数

| 参数 | 配置名 | 初筛值 | 作用 |
| --- | --- | --- | --- |
| logprob 强度 | `alpha` | `1.0, 1.25, 1.5, 2.0, 4.0` | 与 IS 相同的累计 logprob 奖励倾斜目标 |
| 每链更新数 | `updates_per_chain` | `1, 2, 4, 8` | 控制有限步 MH 的混合程度；对应 IS rollout 预算轴 |
| 最大 proposal 后缀 | `max_suffix_actions` | `1, 2, 4, all` | 控制一次 proposal 需要重跑多少个 Agent action |
| 后缀调度 | `suffix_schedule` | `full, uniform, inverse_length, multiscale` | 控制局部修改与全局重生成的比例 |
| 独立链数 | `chains` | `1, 2, 4` | 评估并行链、初始化方差和 pass@k；pass@1 主实验默认 1 |

这些参数与 IS 参数不是逐项数学等价：

- IS `candidate_count` 是一次重采样中的候选池大小；MH `chains` 是独立马尔可夫链数。
- IS `rollouts_per_candidate` 估计条件权重；MH `updates_per_chain` 迭代转移核，logprob 奖励本身不需要 rollout 估计。
- IS `chunk_tokens` 控制下一 action 的候选大小；MH 固定使用 10% reference chunk，主要消融轴仍是重生成后缀包含的 action 数。
- API `request_batch_size` 只改变并发和墙钟，不改变候选、链或转移核，必须放在单独的执行实验中。

多链 pass@1 若需输出一条轨迹，必须在运行前由 seed 均匀选定输出链，不能查看结果后选择。多链全部参与的指标只能
报告为 pass@k 或链间诊断。

### 6.2 MH 诊断量

每条链至少保存：

- 初始化轨迹 logprob、每次 proposal 的新旧后缀 logprob；
- 切点、正反切点概率、proposal action 数和生成 token 数；
- `log_acceptance`、接受标记、累计接受率；
- proposal 实际改变的 action/token 数和接受后改变的 action/token 数；
- 当前链的 Agent 步数、补丁大小、终止原因和工作区快照 ID；
- API token、请求数、墙钟、工具执行时间和失败原因。

接受率只是诊断量，不作为唯一调参目标。高接受率可能只表示 proposal 变化太小，低接受率可能表示 `alpha` 或后缀跨度
过大；必须结合 accepted token changes 和 resolved rate 判断。

## 7. 基线与公平比较

每个正式实例和 seed 至少运行：

| 方法 | 用途 |
| --- | --- |
| `base_miniagent` | 原版 MiniAgent 单次基础采样，不经过 IS/MH |
| `is_alpha_1` | 检查 IS 在无 logprob 倾斜时的分布与成本 |
| `mh_alpha_1` | 检查 MH 保持基础分布；仅正反 proposal 概率相等时应全部接受 |
| `is_selected` | 调参阶段冻结的 IS 配置 |
| `mh_selected` | 调参阶段冻结的 MH 配置 |

实验不做 token 成本配平，但同时记录三种资源用量：

1. API 输入 token、规范化可见输出 token、服务端原始输出 token、被过滤隐藏 token 和总计费 token；
2. API 请求数、模型服务墙钟和端到端 Agent 墙钟；
3. 工具调用数、工具执行时间和隔离工作区数量。

`agent.max_trajectory_output_tokens` 是每条轨迹的协议性生成上限；`budget.max_input_tokens` 与
`budget.max_output_tokens` 仍设为 `0`，表示不增加跨候选、跨 rollout 的共享 token 预算。API 请求数、工具调用数和
墙钟仍保留很高的紧急上限，只用于阻止死循环。每个请求、case 和 arm 都保存 input/output token、API 时间、工具时间
与 checkpoint 次数/耗时。轨迹上限使用规范化的 MiniAgent 可见 token；计费和成本排序使用原始 output token。

IS 的粗略生成成本随 `candidate_count * rollouts_per_candidate` 增长；MH 成本近似为

```math
\text{chains}\times
\left(\text{initial trajectory tokens}
+\text{updates}\times\mathbb E[\text{proposal suffix tokens}]\right).
```

实际 API 输入上下文会重复发送，最终比较必须使用服务端或客户端记录的真实 token，不能只使用上述近似。

## 8. 分阶段消融

不运行 IS 的 $`5\times3\times3\times3=135`$ 全笛卡尔积，也不把 28 个单因素 arm 直接铺到 50 个实例。
数据使用 `repo_stratified_v1` 固定计划：仓库内按 `instance_plan_seed` 和 `instance_id` 的 SHA-256 排序，各阶段按仓库
分层分配。确认集优先保留跨仓库覆盖，smoke、calibrate、screen、confirm 互斥；stress 复用 calibrate 的两个实例，
seed_check 复用 calibrate 与 screen 的 20 个实例。一个 case 是一个 `arm × instance × seed`。

| 阶段/profile | 分层分区 | arm | seed | case |
| --- | --- | ---: | ---: | ---: |
| `smoke` | 3 个独立 smoke 实例 | 5 | 1 | 15 |
| `calibrate` | 5 个分层调参实例 | 13 | 1 | 65 |
| `stress` | calibrate 中固定 2 个 | 10 | 1 | 20 |
| `screen` | 15 个新分层调参实例 | 7 | 1 | 105 |
| `seed_check` | calibrate + screen | 3 | 1 个新 seed | 60 |
| `confirm` | 50 个独立分层实例 | 3 | 2 | 300 |

总计 565 个 case。`ofat` profile 保留原始 28-arm 单因素全集，只用于手动诊断，不属于默认流程。

### 8.1 Smoke

运行 Base、低成本 `alpha=1` IS/MH 控制组以及参考 IS/MH。只验收 API logprob、工作区隔离、补丁提取、计数和失败恢复。

### 8.2 Calibrate 与 Stress

`calibrate` 使用 13 个核心 arm：Base；参考 IS 加 `alpha=1、2`、`batch=2`、`chunk=410`、`rollout=1`；参考 MH
加 `alpha=1、2`、`updates=1`、`suffix=2`、`schedule=full`。`stress` 仅在两个实例上运行 10 个边界 arm：IS 的
`alpha=4, batch=8, chunk=1229, rollout=4`，以及 MH 的 `alpha=4, updates=8, suffix=1, uniform,
inverse_length, chains=4`。

calibrate 的小样本 resolved 只用于可行性淘汰，不作为质量结论。`evaluation_summary.json` 先排除推理、预算、evaluator
或基础设施失败的配置，再按 resolved、失败数、自然 API token 和 arm tag 给出确定性顺序，同时保留 Wilson 区间与当前
最好配置相容的候选。IS/MH 各自的前两个只作为临时建议：第一项对应 `reference_*`，第二项对应 `[shortlist]`；还必须
结合 stress 的 ESS、MH 接受率和失败警告复核。

### 8.3 Screen 与 Seed Check

`screen` 固定 7 个 arm：Base、两个 `alpha=1` 控制组、每种方法的 reference 和 shortlist。它们在 15 个新实例上
运行。随后冻结每种方法一个配置，在前 20 个调参实例上使用新 seed 运行 Base、最终 IS、最终 MH，检查排序是否稳定。

### 8.4 Blind Confirm

确认阶段只运行 Base、最终 IS、最终 MH，在未参与选择的 50 个分层实例上运行两个 seed。确认阶段不得再修改参数；
若修改，必须使用新 tag，并将结果标记为新的探索实验。50 个实例只能提供工程信号，不应把小差异表述为确定提升。

## 9. 指标与统计

### 9.1 主要指标

- `resolved_rate`：官方评测中 resolved 的实例比例；
- `resolved_per_1m_api_tokens`：每百万实际 API 总 token 的 resolved 数，仅作成本效率辅助指标；
- `api_tokens_per_instance`、`api_requests_per_instance`；
- `agent_wall_seconds` 和 `api_wall_seconds`。

### 9.2 次要指标

- MiniAgent 成功终止率、补丁非空率和评测基础设施失败率；
- 模型输出 token、Agent action 数、工具调用数和 patch 行数；
- IS ESS、最大权重和 rollout 完成率；
- MH 接受率、proposal/accepted token changes 和各链终止原因；
- API 超时、限流、重试、缺失 logprob 和上下文溢出次数。

单配置 resolved rate 报告 Wilson 95% 区间。方法差异使用实例级配对 bootstrap；多个 seed 时先保留
`instance_id × seed` 原始结果，再分别报告按 seed 的结果和以实例为重采样单位的聚合区间。成本差异使用相同实例与
seed 的配对比值。配置选择同时给出 Pareto 前沿，不把小样本点估计差异写成确定提升。

基础设施失败与模型失败必须分开：API 5xx、镜像损坏和 evaluator 崩溃属于基础设施失败并按预设重试；MiniAgent
生成无效 action、主动终止或产生错误补丁属于方法结果，不能删除后重跑到成功。

## 10. API 与可复现性要求

API 适配器至少需要：

- 接受 MiniAgent 原始 messages 和 tool schema；
- 返回最终 assistant action、finish reason 和每个采样 token 的 logprob；
- 支持记录或设置 seed；不支持确定性 seed 时显式记录 `seed_supported=false`；
- 返回 input/output token 计数，或允许客户端用固定 tokenizer 复核；
- 对重试使用稳定 request ID，防止超时后重复计费而没有记录；
- 禁止把 API key、Authorization header 或私有 endpoint 写入结果。

每次运行的 manifest 至少包含：

```text
experiment_version
git_commit
model_request_name
model_response_name
api_server_version
tokenizer_revision
miniagent_repository
miniagent_commit
swebench_dataset_revision
swebench_instance_ids_sha256
container_image_digest
sampler_method
sampler_config
base_sampling_config
budget_config
seed
prompt_and_tools_sha256
```

实际实现按 `arm / seed / instance_id` 分片保存 `record.json` 和 `trajectory.json`，唯一性由
`instance_id / seed / arm_fingerprint / config_fingerprint` 保证。文件先写同目录临时文件，再原子重命名；续跑时只
跳过状态完整且配置、arm、seed、数据行哈希都一致的记录。主轨迹、IS 候选/rollout 和 MH proposal 的逐 token
logprob、request ID、服务端模型字段、计数和错误信息都进入审计记录，API key、私有 endpoint 和 header 会脱敏。

## 11. 运行验收门槛

进入正式调参前必须同时满足：

1. 原版 MiniAgent Base 能在 smoke 清单端到端产生并评测补丁；
2. 采样适配器关闭时，发给 API 的 messages、tools 和 sampling 参数与 Base 完全一致；
3. 所有被计入奖励的 token 都有有限 logprob，累计值与逐 token 求和一致；
4. IS `alpha=1` 的候选权重相等，固定表格后端上的重采样分布测试通过；
5. MH `alpha=1` 且正反 proposal 概率相同时全部接受，非对称调度仍包含 Hastings 修正；
6. MH 正反切点概率不相等时，Hastings 调度修正项确实进入接受率；
7. 候选/链工作区隔离测试证明未选分支不会污染主工作区；
8. API token、请求、墙钟和工具成本能按实例、候选、rollout、proposal 汇总；
9. 中断后续跑不会重复提交已完成实例，也不会混用旧配置结果；
10. MiniAgent commit、数据 revision、镜像 digest 和配置 hash 已固定。

## 12. 主要风险与解释边界

| 风险 | 处理 |
| --- | --- |
| API 未覆盖可见 output token logprob | 请求失败；不能用 0 或文本概率替代 |
| API 不返回 EOS/stop logprob | 使用明确标记的 visible-token 奖励倾斜；不得声称严格 $`p^\alpha`$ |
| `alpha` 与长轨迹导致权重/接受率退化 | 使用 log-space 计算；先筛选 `1.0--2.0`，`4.0` 作为压力点 |
| 累计 logprob 偏向短轨迹 | 报告长度与终止原因；不静默改用平均 logprob |
| rollout/proposal 工具状态互相污染 | 每个分支使用独立快照和进程命名空间 |
| 工具或测试存在非确定性 | 从真实 action 边界 checkpoint 派生分支，不从基础镜像重放历史命令；仍不可 checkpoint 的状态需记录并降级结论 |
| vLLM 自动解析原生 tool call | 文本/XML MiniAgent 服务必须关闭 `--enable-auto-tool-choice` 和 `--tool-call-parser`，保留原始文本及 logprob |
| API 限流改变墙钟 | 记录排队、重试和服务端时间；质量与墙钟分开解释 |
| 调参过拟合 SWE-bench | 固定互斥 tuning/confirmation 实例，确认前冻结配置 |
| 多链后挑最好结果 | 禁止用于 pass@1；另列 Best-of-N/pass@k |
| 局部 action MH 被误写成轨迹 MH | 正式标签只用于工作区后缀重放版本，局部版本带 `local_action_smoke` 标签 |

最终结论只适用于固定的 Qwen API 版本、MiniAgent revision、SWE-bench split 和运行约束。模型服务、prompt、工具或
上下文策略发生变化后，必须生成新的实验版本，不能与旧结果直接合并。

## 13. 搬机运行

仓库固定以下外部实现：

- mini-SWE-agent `2.4.6`，commit `25941c89cfbc91eb40b3f8756348c91d9977d57e`；
- SWE-bench evaluator `5.0.1`；
- SWE-bench Verified `SWE-bench/SWE-bench_Verified` dataset revision `78f471bf655a3137b2e8a75af1501690ec009ec3`；
- LiteLLM `1.99.0`、OpenAI Python client `2.54.0` 和 Docker SDK `7.2.0`；
- MiniAgent 官方 `swebench_xml.yaml`，不使用其他 Agent harness。

目标机需要 Python 3.11+、Git、可用的 Docker daemon、足够的镜像/工作区磁盘，以及能访问 Qwen API、Hugging Face
数据和 SWE-bench Docker registry 的网络。安装固定依赖：

```bash
bash experiments/swebench/bootstrap.sh
```

设置 API。可以直接导出变量，也可以从模板建立本机私有环境文件
`configs/swebench_qwen38_27b.env`：

```bash
cp configs/swebench_qwen38_27b.env.example configs/swebench_qwen38_27b.env
```

其中 `QWEN_API_BASE` 必须包含 OpenAI-compatible `/v1` 路径，`QWEN_API_KEY` 只保存在目标机。配置中的
`api.model_name` 必须与服务端实际模型 ID 对齐，并保留 LiteLLM 的 `openai/` provider 前缀。
vLLM 必须关闭自动工具调用解析，即启动命令不得包含 `--enable-auto-tool-choice` 或 `--tool-call-parser`；本实验使用
MiniAgent 官方 text/XML action 协议，不向 API 发送原生 tools。

先运行 3 个实例、5 个预注册 arm 的 smoke：

```bash
./run_swebench_stage.sh smoke configs/swebench_qwen38_27b_api.toml
./evaluate_swebench_ablation.sh \
  results/swebench/qwen38-27b-is-mh-v2/smoke --max-workers 4
```

预检会验证 Python/依赖、Docker、数据集和一次真实 API logprob 响应。任一 token 缺 logprob 时会在启动正式 Docker
任务前失败；API 若返回没有对应 logprob 的独立 reasoning 字段也会失败。smoke 通过后按顺序运行成本校准和边界压力：

```bash
./run_swebench_stage.sh calibrate configs/swebench_qwen38_27b_api.toml
./run_swebench_stage.sh stress configs/swebench_qwen38_27b_api.toml
./evaluate_swebench_ablation.sh \
  results/swebench/qwen38-27b-is-mh-v2/calibrate --max-workers 4
./evaluate_swebench_ablation.sh \
  results/swebench/qwen38-27b-is-mh-v2/stress --max-workers 4
```

每次 evaluator 完成后会生成 `evaluation_summary.json`。根据 calibrate 的临时建议与 stress 的 ESS、接受率和失败警告，
把 IS/MH 第一项写入 `reference_*`，第二项写入 `[shortlist]`，然后运行二轮筛选。二轮完成后结合 screen 汇总冻结
`reference_*`，再执行 seed 检查和盲确认：

```bash
./run_swebench_stage.sh screen configs/swebench_qwen38_27b_api.toml
./evaluate_swebench_ablation.sh \
  results/swebench/qwen38-27b-is-mh-v2/screen --max-workers 4
./run_swebench_stage.sh seed_check configs/swebench_qwen38_27b_api.toml
./evaluate_swebench_ablation.sh \
  results/swebench/qwen38-27b-is-mh-v2/seed_check --max-workers 4
./run_swebench_stage.sh confirm configs/swebench_qwen38_27b_api.toml
./evaluate_swebench_ablation.sh \
  results/swebench/qwen38-27b-is-mh-v2/confirm --max-workers 4
```

`run_swebench_50.sh` 是最后一条 `confirm` 命令的兼容快捷入口。任一阶段增加 `--dry-run` 可只查看 arm、实例、seed 和
case 数；`--workers 2` 可调整并发。直接调用 `run_swebench_ablation.sh` 仍可运行单个 profile 或用 `ofat` 做完整诊断。

结果位于
`results/swebench/<tag>/<profile>/<arm>/seed-<seed>/`。每个实例分别保存 `record.json` 与原版 MiniAgent
`trajectory.json`；profile 根目录保存本次选中数据行的 `dataset.parquet`，官方 evaluator 直接读取这份固定快照。
若评测旧 `c104f840...` 诊断结果，评测器会保留原文件并生成 `dataset.evaluation.parquet`，从固定的 5.x revision 补齐
`image/eval_script/log_parser/eval_type`；`evaluation/dataset_provenance.json` 保存双方 hash 和身份字段校验结果。不同
dataset revision 或 `v1/v2` tag 的结果不得合并。
每个 arm/seed 自动重建 `preds.json`，profile 结束时自动更新 `inference_summary.json`，其中包含 input/output token、
API 请求、工具调用和各项耗时的总量与均值。官方评测完成后另写 `evaluation_summary.json`，包含 resolved、Wilson 区间、
失败分类、采样诊断、确定性排名和建议配置字段。跨分支的共享 token 预算只记录不截断；每条轨迹仍遵守
`agent.max_trajectory_output_tokens` 协议上限，达到上限会记录 `TrajectoryTokenLimitExceeded`。相同配置、数据行、arm 和 seed 的完整结果会自动
跳过；运行矩阵或数据哈希不同时必须使用新 tag，避免混合结果。

checkpoint 镜像带有 `org.inference-scaling.swebench.checkpoint=true` 标签，正常结束时自动删除。进程被强制终止后，可在
确认没有同仓库实验运行时清理未被容器引用的残留镜像：

```bash
docker image prune -f \
  --filter label=org.inference-scaling.swebench.checkpoint=true
```

生成推理成本汇总：

```bash
.venv-swebench/bin/python -m experiments.swebench.summarize \
  --results results/swebench/qwen38-27b-is-mh-v2/screen
```

使用固定官方 evaluator 评测某个 profile：

```bash
./evaluate_swebench_ablation.sh \
  results/swebench/qwen38-27b-is-mh-v2/screen --max-workers 4
```

evaluation 日志写入 profile 目录下的 `evaluation/`。先加 `--dry-run` 可以检查每个 arm/seed 的 evaluator 命令。
