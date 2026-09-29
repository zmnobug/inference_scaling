# Qwen3.8-27B x SWE-bench Verified：Thinking / Action Conditional IS 实验方案

状态：2026-09-23 更新；统一v3百题63/100，历史baseline70/100；环境修复后独立补跑三题：django-14404未通过，requests-2931与django-14771通过；不替换历史百题成绩，正文IS暂不运行<br>
模型：`Qwen/Qwen3.8-27B`<br>
Agent：mini-swe-agent `2.4.6`<br>
随机种子：`20260916`

百题最终报告：`docs/reports/QWEN38_SWEBENCH_RANDOM100_THINKING_IS_BASELINE_COMPARISON.md`。统一v3百题63/100（救回4题、回退11题）；历史混合版本69/100及原始62/100独立保留。以下保留各阶段执行方案与时间线。

## 2026-09-23：任务执行环境修复与独立单题验证

- **适用全部实验组**：baseline、Thinking IS及使用同一session工厂的其他方法；不修改Consilience、候选权重、chunk/M/K、L或上下文预算。
- 每条工具命令先加载`/opt/miniconda3/etc/profile.d/conda.sh`，激活`/opt/miniconda3/envs/testbed`，再执行原命令。每次独立shell都重新激活，不依赖上一条命令的环境变量；激活失败不执行原动作，不退回base环境。
- 初始session在创建模型前运行限时120秒的环境探针：核验Python prefix、`/testbed`工作目录、项目导入来自当前checkout、测试入口可导入／可调用。当前登记Verified的12个仓库；未知仓库要求明确补充探针，不默默跳过。
- 探针不运行隐藏测试，不要求待修复代码的测试全绿；测试断言失败、返回码及原始输出仍交给agent。导入探针成功也不保证每个测试文件或插件都正常，应继续检查实际测试执行输出。
- 恢复IS/MH检查点时只核验解释器和工作目录，不重新导入已被候选修改的项目，避免把候选代码自身的错误误判为环境故障。
- 两组共同追加环境／验证指引：使用任务Python和真实仓库测试，不能把手抄简化函数通过、导入失败或零测试收集当作补丁验证成功。这是共同prompt变化，不能把修复后结果与历史baseline当严格同协议对照。
- 新环境协议`swebench-testbed-v1`；结果schema升级为`swebench-is-mh-v6`。旧schema不视为可续跑完成记录；默认拒绝在不同schema的旧manifest目录继续写入，后续使用新tag／输出目录，不覆盖旧实验。
- 环境探针原始输出、解释器、导入路径及耗时写入`record.json`的`diagnostics.task_environment`；成功轨迹还保存`info.runtime.task_environment`。初始化失败为`TaskEnvironmentError`，在模型调用前停止并清理容器；探针时间计入runner总耗时、不计为agent工具调用或模型token。
- 可在原有预检中指定真实题目容器，且不调用模型：

```bash
python -m experiments.swebench.preflight \
  --config configs/qwen38_swebench_thinking_is_random100_v3_unlimited.toml \
  --skip-api \
  --task-instance astropy__astropy-14508 \
  --task-instance matplotlib__matplotlib-24570
```

未传`--task-instance`的常规全局预检不是题目容器验证；真正运行时每个初始session仍自动执行检查。真实容器验证结果和修复局限统一见唯一结果报告第14.7节。用户随后批准仅补跑最短回退题，单题配置为`configs/qwen38_swebench_thinking_is_envfix_django14404.toml`：环境ready，官方仍未通过；详细证据见报告第14.8节。没有启动新的百题或全部11题补跑，历史成绩不变。

用户随后批准再补跑第二短的`psf__requests-2931`，配置为`configs/qwen38_swebench_thinking_is_envfix_requests2931.toml`，保持原采样与预算、沿用8000服务。官方判题通过；真实仓库测试发现并帮助模型修正了原bytes查询参数回归。该镜像仍缺少pytest-httpbin，不能把本题官方通过当成原仓库完整测试环境已无问题；具体结果及限制见唯一报告第14.9节。未启动其他补跑。

之后用户批准第三道`django__django-14771`，配置为`configs/qwen38_swebench_thinking_is_envfix_django14771.toml`，沿用8001服务及同一份修复代码。模型实际探测了`sys._xoptions`的bool值，并跑通Django原生测试入口；官方目标1项与原有60项测试全部通过。三道独立补跑为2过1未过，完整证据与样本选择限制见报告第14.10节；其余8道尚未启动。

## 2026-09-20：零thinking最小修复与独立9题补跑

- 新采样诊断协议为 `thinking-is-token-prefix-v3`，`empty_thinking_policy=uniform_if_no_scored_candidate`。百题归档仍是v2，原始62/100不变。
- 只将已通过响应审计、完整文本直接以 `<mswea_bash_command>` 开始且thinking token数为0的候选识别为合法零thinking。其Consilience奖励仍为null，不伪造0分，也不把未形成边界／EOS在前／损坏logprobs等无效情况放行。
- 若有任何可评分的候选或rollout，完全沿用原Consilience权重，零thinking候选不参与该次选择。只有所有奖励均不可评分、但至少存在一个合法零thinking候选时，才在这些候选中均匀选择；无效候选权重仍为0，记录 `selection_mode=empty_thinking_uniform`。
- 选择后保留原始token前缀（包括与结束标记共享token的正文前缀），直接走原有正文普通生成；不再做thinking rollout、不启用guarded-v2 fallback、不重置前缀、不补写或修复动作。没有合法零thinking候选且全无有效奖励时，继续按原规则终止。
- L、上下文余量、单次请求超时、EOS审计及动作解析规则不变；标记已经耗尽本轮预算时不绕过上限。候选M、rollout K、chunk、seed和奖励公式均不变。
- 代码修复不代表原9题会全部通过；模型补跑必须使用独立实验标签与源码快照，不覆盖原始百题成绩或旧结果；报告可追加明确标注来源的修复后合并结果。
- 修复阶段验证：Thinking IS专项38项、完整SWE-bench回归168项全部通过，ruff及差异空白检查通过。覆盖全零thinking、空／非空混合候选、损坏logprobs、EOS在标记前、未形成边界、不可评分的共享thinking token、非有限奖励、正文共享token、输出／上下文预算与不完整动作；该验证阶段没有发起真实模型补跑。

### 用户确认的9题完整重跑

- 固定重跑原始百题中全部9道 `no_valid_thinking_rollout`：`django__django-12325`、`matplotlib__matplotlib-20826`、`matplotlib__matplotlib-24637`、`matplotlib__matplotlib-25960`、`pallets__flask-5014`、`pytest-dev__pytest-5787`、`sympy__sympy-17139`、`sympy__sympy-22456`、`sympy__sympy-23413`。它们包含6道原baseline通过题及3道原baseline失败题。
- 配置／名单：`configs/qwen38_swebench_thinking_is_empty9_rerun_unlimited.toml`、`configs/qwen38_swebench_thinking_is_empty9_instances.txt`。除tag、filter以及v3零thinking代码修复外，模型API配置、seed、agent预算和arm参数与原不限时实验一致；L=131072、上下文133120、chunk=100、M=4、K=2、不限整题时间、单API请求1800秒不变。
- 从干净任务容器完整重跑，每题一次，不续接旧工作区，不挑选最好一次。双服务按排序交错分成5＋4题，A为8000／GPU4–7，B为8001／GPU0–3；各分片完成生成后自动官方判题，判题串行。只比较新9题与旧9题，不把原始62/100直接覆盖成修复后的统一百题成绩。
- 启动脚本：`experiments/swebench/run_empty9_dual_background.sh`；独立后台单元 `qwen38-swebench-thinking-is-empty9-rerun-unlimited-dual.service`。输出 `results/swebench/qwen38-thinking-is-empty9-rerun-unlimited-dual/` 软链接到同名数据盘目录 `/data/users/jenkins/inference_scaling-results/` 下；保留 `parent_cases.json`、分片名单、配置哈希、源码快照，完成后汇总9题的 `summary.json` 和 `case_timings.csv`。
- 存储前置处理：启动前根分区仅3.4GiB。经授权，将已完成的 `qwen38-thinking-is-failed30-unlimited-dual` 归档复制到数据盘并逐文件比对一致，原路径替换成软链接后移除已校验的原磁盘副本；内容未丢弃、结果未改写。根分区恢复约8.7GiB，数据盘余量约95GiB；新任务继续同时检查两盘4GiB保护线，不降低阈值。
- 本次补跑已完成：2026-09-20 14:24:54启动，20:53:40结束（北京时间），墙钟约6小时29分钟；正式通过7/9，9题均提交非空补丁，生成、评测和汇总退出0。未通过为 `sympy__sympy-17139`（测试失败）、`pytest-dev__pytest-5787`（官方辅助标签为no_tests_collected，但逐日志复核确认实际为PASS_TO_PASS反序列化回归；详见百题报告第0.9节）。九题整体替换后的百题结果为69/100，非统一v3百题；原始62/100不覆盖。完整指标与逐题明细已更新到百题报告第0节、第9节，本次文档更新不启动额外实验。启动前169项回归全部通过，冻结的v3采样源码SHA-256为 `8444f42e5af046fbdefa13705495a811609bdf68f690588689de22413972fab0`。旧9题合计runner约2.08小时，但均在流程异常处提前结束，不能把它作为修复后完成时间的可靠预测；继续沿用不限整题时间并记录逐题实际耗时。

## 2026-09-19：补齐不限时 Thinking IS 百题

- 用户确认：保留已完成不限时30题，运行固定百题中剩余70题，不重新抽样。70题包括此前仅按30分钟上限运行过的12题，以及该批次尚未运行的58题；旧限时20题不能直接拼入不限时百题统计。
- 名单：`configs/qwen38_swebench_thinking_is_remaining70_instances.txt`；与 `configs/qwen38_swebench_baseline_failed30_instances.txt` 无交集，二者并集严格等于原随机100题。
- 配置：`configs/qwen38_swebench_thinking_is_remaining70_unlimited.toml`，除标签、筛选名单外与已完成30题相同。Thinking 使用 Conditional IS＋Consilience，正文普通生成；`chunk=100, M=4, K_rollout=2`；整题累计选中轨迹输出 `L=131072`、上下文 `133120`、安全余量256；250步／工具调用、50000次API请求。单题墙钟上限为0（禁用），但单API请求超时1800秒仍保留；不启用guarded-v2或新增截断策略。
- 两服务各35题，固定交错分片：A使用8000／GPU4–7，B使用8001／GPU0–3；服务内单题串行，候选并发沿用现有实现。每个分片生成后官方判题，判题文件锁串行；逐题记录agent、runner、API和工具耗时。
- 启动脚本：`experiments/swebench/run_remaining70_dual_background.sh`；已于2026-09-19 22:35:09（北京时间）使用独立systemd用户单元 `qwen38-swebench-thinking-is-remaining70-unlimited-dual.service` 启动，不依赖会话，不隐式重启已存在的实验目录。两套预检通过，各35题manifest生成，首题分别为 `astropy__astropy-12907` 和 `astropy__astropy-13236`，均已进入实际IS推理。保留源码快照、配置哈希、分片清单；两套runtime指纹分别与已完成30题的对应服务一致。启动前156项SWE-bench测试及静态检查通过。
- 新输出入口：`results/swebench/qwen38-thinking-is-remaining70-unlimited-dual/`，软链接到 `/data/users/jenkins/inference_scaling-results/qwen38-thinking-is-remaining70-unlimited-dual/`。旧数据不迁移、不删除。启动检查时根分区约4.6GiB、数据盘约109GiB可用；生成每题和判题启动前**同时检查数据盘与Docker所在根分区至少4GiB**。不足时等待，每300秒重查，不删除数据；这不是磁盘预留，运行中的单题仍可能继续占用磁盘。
- 基于已完成30题平均agent耗时约27分钟，70题双服务理想均衡生成约15.8小时，暂按16–24小时以上规划。无整题时间上限，长尾、分片不均衡及磁盘等待都可能继续延长，不承诺固定完成时间。
- 最终主对比：不限时IS的30＋70题对历史baseline固定100题70/100，完整报告通过增益、回退与耗时。历史baseline有旧30分钟上限及不同格式纠错设置，因此属于历史对照，不宣称严格同协议的纯IS因果收益。两题补跑baseline结果1/2单列，不择优替换旧baseline；旧20题仅作历史诊断，不计入新IS百题。

结果与修复更新：20题结果、两题边界修复补跑及可选guarded-v2说明统一见 `docs/reports/QWEN38_SWEBENCH_RANDOM100_THINKING_IS_BASELINE_COMPARISON.md`。
纯Conditional IS的历史定义及结果保留；新增 `configs/qwen38_swebench_thinking_is_guarded_smoke.toml` 独立定义
每轮4块／60秒IS预算、1024-token rollout、显式普通续写及最后60秒收尾，不能将其与无fallback的旧方法混为同一协议。
此配置仅准备定向验证，不表示已经重跑五题或批准启动百题。

### 新增实验：baseline失败30题，不限整题时间

用户确认下一批针对修复合并后70/100的baseline所剩30题运行Thinking IS，并取消每题30分钟限制。
用户随后批准使用两个现有服务并行启动，现已于2026-09-19 18:16（北京时间）完成全部生成、官方判题及汇总，结果为7/30。完整逐题结果和baseline对照统一见 `docs/reports/QWEN38_SWEBENCH_RANDOM100_THINKING_IS_BASELINE_COMPARISON.md`。启动前149项SWE-bench测试通过；两服务预检通过、各15题manifest与固定分片一致，systemd未设置运行时限。本节仅覆盖这一新配置；下文原20题的1800秒历史协议保持不变。

- 配置：`configs/qwen38_swebench_thinking_is_failed30_unlimited.toml`。
- 固定名单：`configs/qwen38_swebench_baseline_failed30_instances.txt`。由原百题官方结果和固定11题reasoning兼容补跑报告全量替换后计算，恰好30题；不是原63/100时的37题。配置内置相同精确筛选，防止未传名单时误跑全集。
- 方法仍为thinking Conditional IS＋Consilience、正文普通生成，chunk=100、M=4、K=2；不启用guarded-v2及其fallback、验证／收尾提醒。L=131,072、上下文133,120（安全余量256）、250步、连续3次格式错误上限不变。
- `agent.wall_time_limit_seconds=0`：关闭整题agent硬截止，不安装该任务的SIGALRM定时器。
- `budget.max_wall_seconds=0`：关闭账本原两小时累计墙钟预算；不是将30分钟改成另一个隐含整题上限。
- 无整题时限的Docker任务使用 `container_timeout="infinity"`，取消mini-swe-agent默认 `sleep 2h` 的容器寿命；任务正常或异常终止后仍走原清理流程。进程被强杀等情况下仍需检查残留容器。
- **保留单次操作保护**：API单请求timeout=1800秒、tokenize请求最多30秒、工具命令超时沿用mini-swe-agent配置，官方评测自己的测试超时不变。它们不累计成每题30分钟上限，但单次API超时仍可能导致该题失败；不是允许单个无响应请求无限等待。
- 总API请求数50,000、工具调用250次、上下文和主轨迹L限制继续生效；取消时间限制不代表保证提交或保证解题成功。耗时不再有可承诺的整批上界，额外候选／rollout可能非常昂贵。
- 成功和失败题都记录 `record.json` 的 `diagnostics.limits.agent_seconds`（agent推理、选块、rollout、工具操作阶段实际耗时），以及 `usage.elapsed_seconds`（单题runner账本跨度，含环境准备及清理，不含官方判题）。初始化失败等未进入agent的情况没有agent_seconds，但仍有usage耗时和失败原因。
- 逐轮记录 `diagnostics.limits.requests[].elapsed_seconds`；无整题时限时 `remaining_seconds=null`，不将Infinity写入JSON。逐请求API/工具累计耗时、token数、终态和补丁照常保存。
- 结果报告应逐题列出上述耗时、官方通过情况及终止原因，汇总成功／失败两组的均值、中位数、长尾及超过30分钟的题数。官方判题时间单列，不把失败题从时间统计或30题分母中删去。

这批是**不限整题时间的定向救回实验**，与历史有30分钟上限的baseline不再同时间预算。后续救回可能来自更多计算时间、适配修复或IS策略，不能全部归因于Consilience/IS；也不能将其结果称为纯IS百题通过率。正式判断算法收益需要同协议对照。历史20题及两题补跑的配置、数据不修改。

#### 双服务执行与时间预估

- 名单按题目ID排序后交错分片，各15题：`shard_a`使用8000／GPU 4–7，`shard_b`使用8001／GPU 0–3。题目总并发2，每服务内部串行，候选及rollout仍按原方式执行；不从历史结果择优复用，也不重复分派题目。
- 后台脚本：`experiments/swebench/run_failed30_dual_background.sh`。systemd单元：`qwen38-swebench-thinking-is-failed30-unlimited-dual.service`。不依赖当前会话，不自动重启或隐式重跑已有目录。
- 输出根目录：`results/swebench/qwen38-thinking-is-failed30-unlimited-dual/`。`assignment.json`、两份名单、`inputs.sha256`及源码快照冻结执行来源；两服务分别保留manifest和runtime指纹。
- `pipeline.log`记录监督进程，`shard_a.log`、`shard_b.log`记录各自预检、生成和判题。每个分片生成完成后自动官方判题；判题用文件锁串行，最多一个评测任务，避免两套官方测试同时抢CPU和磁盘。
- 全部完成后校验30条记录和两份官方报告覆盖一致，生成 `summary.json` 与 `case_timings.csv`，保留每题agent时间、runner时间、API／工具时间及成败。合并汇总是aggregation-only，两套官方报告独立保留，不伪造统一runtime指纹。任一分片缺结果则拒绝输出完整30题汇总。
- 每题及评测启动前保留4GiB磁盘保护。两服务启动前可用空间约9.2GiB；若后续不足则等待，不自动删数据。这种等待会增加批次墙钟时间。
- 历史限时IS20题平均约16.9分钟，对30题双服务理想均衡外推约4.2小时；失败题及原超时轨迹会更慢，不能将这个值当作不限时实验的完成承诺。**暂按每题平均30–60分钟估算，生成约7.5–15小时，整体预留8–16小时；这是规划假设，不是统计置信区间。** 长尾、分片不均衡、超长rollout或磁盘等待可能使整批超过24小时。完成首批题目后应以实测每服务吞吐更新估计。

本文把 [LiveCodeBench 三组 Conditional IS 方案](QWEN38_LIVECODEBENCH_IS_EXPERIMENT.md)
迁移到 mini-swe-agent 的多轮软件工程轨迹。LiveCodeBench 的单轮 thinking / 正文边界在这里映射为
每轮 agent 的可见 thinking / shell action 边界；不能把单轮代码生成协议原样套到多轮 SWE-bench。

## 1. 实验问题

在完全相同的模型、SWE-bench 实例、agent prompt、采样参数、seed 派生规则、单题输出预算和墙钟上限下，
比较以下三组的官方 `resolved`：

| 组别 | 计划标识 | Thinking | Action 正文 |
| --- | --- | --- | --- |
| Baseline | `baseline` | 基础分布单次生成 | 与 thinking 同一次普通响应 |
| Thinking IS | `is_thinking` | Consilience Conditional IS | 选定 thinking 后按基础分布生成一次 |
| Thinking + Action IS | `is_thinking_action_logprob` | 与上一组相同 | Conditional IS，奖励为 action 序列 logprob |

主问题是两组 IS 是否能解决 baseline 未解决的实例，以及增量通过率是否值得额外 API 请求、模型前向
token、Docker 分支和墙钟。MH 不进入本轮实验。

2026-09-18 用户确认：保留 `L=131072`、上下文 `133120`，chunk 改为固定 `100`，三组统一采用连续
`3` 次格式错误才结束的有限纠错，后续沿用 `configs/qwen38_swebench_random100_instances.txt` 的固定 100 题。
本轮只启动 Thinking IS 单题 smoke，不启动百题或正文 IS。未新增单轮 4096-token 限制；正常正文仍受剩余
上下文、累计 L 和 1800 秒时限约束。原 70% 是旧纠错协议下的补跑合并成绩，不是新协议的正式配对 baseline。
百题历史单轮 thinking 均值约 91 tokens、P95 约 412；chunk=100 不意味着平均四步，短 thinking 会提前到边界。

第三组使用 logprob 奖励形成权重后做 categorical resampling，不直接选择 logprob 最大候选。
任何候选选择都不能读取公开测试、隐藏测试、gold patch 或官方 evaluator 结果。

## 2. SWE-bench 中的 Thinking / Action 边界

mini-swe-agent 的 text/XML 协议要求每轮响应包含一段解释和一个 shell action：

```text
THOUGHT: visible reasoning for the next repository operation

<mswea_bash_command>one shell command</mswea_bash_command>
```

本实验固定以下 token 所有权：

- thinking：assistant 可见输出起点到 opening `<mswea_bash_command>` marker 之前的全部 token；
- action：opening marker、命令内容、closing `</mswea_bash_command>` marker 及该响应的终止 token；
- observation：命令执行结果，只作为下一轮条件，不属于模型输出奖励；
- submission：仍由 mini-swe-agent 的官方提交命令和解析逻辑产生，不人工重建补丁。

marker 可以在解码文本中定位，但必须核对实际生成 token IDs，续写使用原始 ID，不能切开 token 或
将文本重新 tokenize 来代替生成前缀。共享marker边界的token整体排除在thinking奖励外，前缀保留其全部内容，
包括已经采样的正文首字符。旧版对非空白共享边界的严格拒绝已证实会误伤token `>/`，现已修复。
API 若把 reasoning
放入没有对应 logprobs 的独立 `reasoning_content` 字段，本实验直接拒绝该响应，不把隐藏 reasoning 与可见
action 拼接后评分。

独立字段本身不代表缺少评分。若 sampled-token 流完整覆盖 reasoning、边界和正文，且按本机 Qwen parser
的拆分规则能严格复现原字段，则从 token bytes 无损还原完整输出。还原文本统一用于 action parser 和后续
history，原始拆分响应仍保留在轨迹中；不关闭 thinking、不补造 marker 或 logprob，也不丢弃 parser 隐去的
已评分前缀。详见 [reasoning 兼容修复](../reports/QWEN38_SWEBENCH_RANDOM100_THINKING_IS_BASELINE_COMPARISON.md)。

没有完整 opening marker 的响应不能进入 action 阶段。没有完整 closing marker、包含多个 action、或不能通过
mini-swe-agent 官方 action parser 的正文，按格式失败处理，不能执行其中的部分命令。

## 3. 三组执行语义

### 3.1 Baseline

每一轮保持 mini-swe-agent 官方 text/XML 流程：模型一次生成 thinking 和 action，parser 验证后执行命令并
追加 observation。达到提交、agent 步数上限、输出预算、上下文边界或墙钟上限时结束。

Baseline 不为了与 IS 实现对齐而拆成两次请求，避免把普通生成改成另一种条件分布。

### 3.2 Thinking IS，Action 普通生成

每轮先只对 thinking 执行在线分块 Conditional IS：

```text
在当前 agent history 后生成 M=4 个 thinking 候选短块
-> 每个候选生成 K_rollout=2 条直到 thinking/action 边界的条件补全
-> 只用完整 thinking 的 Consilience 奖励计算候选权重
-> 按权重随机选择一个 thinking 短块并追加到前缀
-> 继续下一 thinking 步，直到 opening action marker 或达到阶段边界
```

thinking 完成后，以 `agent history + selected thinking` 为固定前缀，只按基础分布生成一次完整 action。
action 不调用奖励、不生成额外候选，也不进入 thinking 的 candidate log weight。

### 3.3 Thinking IS，Action Logprob IS

thinking 阶段与上一组使用相同配置和 seed 派生规则。完成 thinking 后，以相同固定前缀对 action 继续执行
Conditional IS：

```text
生成 M=4 个 action 候选短块
-> 每个候选生成 K_rollout=2 条直到 closing action marker 的条件补全
-> 计算完整 action token 的序列 logprob 奖励
-> 经 reward temperature 缩放后形成候选权重
-> categorical resampling 选择一个 action 短块
-> 必要时继续下一 action 步，直到 action 闭合
```

action 奖励只覆盖本轮 action token，不重复奖励选定 thinking，也不包含 action 执行后的 observation。
最终 action 必须通过同一个 mini-swe-agent parser，随后在从候选分支继承的同一 Docker 文件系统状态中执行。

## 4. 正式参数

| 参数 | 值 |
| --- | ---: |
| 数据集 | `SWE-bench/SWE-bench_Verified`，500 题 |
| 数据 revision | `78f471bf655a3137b2e8a75af1501690ec009ec3` |
| 模型服务上下文 | `133120` tokens |
| 单题选中轨迹累计输出上限 `L` | `131072` tokens |
| 单题 × 方法 agent 墙钟上限 | `1800` 秒 |
| mini-swe-agent step limit | `250` |
| 候选数 `M` | `4` |
| 每候选 rollout 数 `K_rollout` | `2` |
| chunk 上限 | 固定 `100` tokens；剩余预算不足时缩短，阶段边界到达时提前结束 |
| rollout 设计 | `iid`、on-policy |
| 采样温度 | `1.0` |
| `top_p` | `1.0` |
| `top_k` | 禁用 |
| Thinking 奖励 | `consilience`，reward temperature `2.0` |
| Action 奖励 | `sequence_log_probability`，scale `1.0`，reward temperature `10.0` |
| case worker | `1` |
| 候选请求调度 | 首轮 smoke 串行；每步仍固定 M=4、K_rollout=2 |
| 连续动作格式错误上限 | `3`；正常动作后重置计数，错误调用计入所有相关预算 |
| 每题每组正式尝试 | `1` |

`L=131072` 是选中主轨迹上所有 agent 响应的累计输出硬上限，不是每轮 API 调用上限，不包括 prompt、
tool observation、未选候选或 rollout。IS 的全部额外前向 token 单独统计，不能把 `L` 描述为总计算预算。

## 5. 动态上下文与 Chunk

### 5.1 上下文与输出预算

`133120` 是单次模型调用的上下文窗口上限，即本次全部输入与本次新生成输出的 token 总数上限，
不是单轮回答长度，也不是单题累计输出上限。输入包括系统提示、题目、保留的历史响应和工具 observation；
本次新生成输出包括 thinking 和 action。历史响应会占用后续请求的上下文，但不重复计入累计输出 `L`。

多轮 agent history 还包含任务描述和不断增长的 tool observations，因此不能像单轮 LiveCodeBench 一样给
每次调用固定 131,072-token 输出上限。每次请求前必须使用 tokenizer 计算实际 prompt tokens：

```text
context_remaining = 133120 - prompt_tokens - 256
trajectory_remaining = 131072 - selected_trajectory_output_tokens
stage_cap = min(context_remaining, trajectory_remaining)
chunk_tokens = min(100, stage_remaining, context_remaining, trajectory_remaining)
request_max_tokens = min(stage_remaining, context_remaining, trajectory_remaining)
```

其中 256 tokens 是终止 marker、格式恢复和计数误差的固定安全余量。任何一项 remaining 非正时，当前
`题目 × 方法` 以明确的 budget/context 状态结束，不继续发起必然溢出的请求。

候选短块使用 `chunk_tokens`；条件 rollout 可使用 `request_max_tokens` 继续到当前阶段终止边界。进入 action
阶段后重新计算剩余 stage cap；chunk 的配置上限始终是 100，不再按 10% 计算。实际下发的 prompt、chunk、
max tokens 和停止原因必须逐请求记录。

例如，本轮输入为 `40000` tokens，则扣除安全余量后，上下文允许最多生成 `92864` tokens；实际请求仍需
受剩余轨迹预算和阶段预算约束。重新发起一轮请求不会清空历史，也不会重置 `L` 或 30 分钟计时。
本方案不自动删除历史、压缩对话或使用滑动窗口；工具 observation 追加后必须重新检查上下文。

### 5.2 本轮停止与整题终止的判断

以下均为正式实验的目标行为，尚需实现与测试；不能据此认为现有 runner 已支持自动续写或格式恢复。
“停止该题”仅指当前 `instance_id × 方法`，不终止其他实验组或后续实例。

每次请求前、响应返回后和工具执行后均检查墙钟与预算。整题硬限制优先于继续生成或执行新命令；
到达限制后立即进入第 8 节的终态处理，不因已生成一个完整命令而额外获得一轮执行预算。

| 触发条件 | 后续处理 | 是否结束当前题当前组 |
| --- | --- | --- |
| IS 候选短块达到 `chunk_tokens`，尚未到阶段边界 | 按原 Conditional IS 流程做 rollout、选择短块并继续；不能把短块终止当作完整回答终止 | 否，前提是仍有整题预算 |
| thinking 到达 opening action marker | 转入 action 阶段，重新计算可用预算 | 否 |
| 完整响应通过 action parser，且仍有整题预算 | 执行完整命令、追加 observation，再检查预算；普通命令后进入下一轮，正式提交命令则进入判题 | 普通命令不结束，正式提交结束 |
| 本次响应为 `finish_reason=length`，但 action 已完整且通过 parser | 不能仅凭 `length` 判整题失败；仍按预算检查和完整命令规则处理 | 由剩余预算及命令类型决定 |
| 本次响应为 `finish_reason=length`，且最终待执行 action 不完整 | 先检查整题预算；预算尚可时反馈格式错误，计入连续错误次数，不执行部分命令 | 连续第 3 次错误或预算耗尽时结束 |
| 最终响应正常停止，但缺少完整 action 或不能通过 parser | 反馈 `format_error`，不把正常 stop 当作成功提交；正常动作后清零连续错误计数 | 连续第 3 次错误或预算耗尽时结束 |
| 条件 rollout 达到输出限制，未完成所需阶段 | 该 rollout 质量记零，不补采样，不改变 `K_rollout=2` 的分母；检查是否仍有有效候选 | 不因单条 rollout 无效直接结束 |
| 单步所有候选 rollout 均无有效质量 | thinking 记录 `no_valid_thinking_rollout`；action 记录 `no_valid_action_rollout`，不回退 baseline | 是 |
| `context_remaining <= 0` | 记录 `context_budget_exhausted`，不再请求模型 | 是 |
| `trajectory_remaining <= 0` | 记录 `trajectory_output_limit`，不再生成或执行新命令 | 是 |
| 单题墙钟达到 `1800` 秒 | 记录 `generation_timeout`，中断未完成的请求、rollout 或工具操作 | 是 |
| 达到 agent `250` 步上限且未正式提交 | 记录 `agent_step_limit` | 是 |

普通完整响应与 IS 的选中阶段输出不做人工改标签或部分命令执行；仅允许在原预算内将格式错误反馈后重新生成
下一轮，连续 3 次错误终止。该协议不复用旧 fail-fast 成绩作为正式对照。只有既定 Conditional IS 的短块
拼接属于正常继续生成。若以后需要加入续写或恢复，必须另行冻结三组适用的规则、预算计费和协议版本，
不能在正式运行中临时补救失败样本。

日志区分请求级 `finish_reason` 与题目级 `termination_reason`，并记录阶段、角色（主轨迹/候选/rollout）、
输入长度、请求输出上限、实际输出长度、累计选中输出、剩余上下文、剩余时间、parser 结果和 submission 状态。
多个硬限制同时触发时全部保留，主原因按墙钟、累计输出、上下文、步数的顺序确定；不得仅用 `length`
推断是哪一种预算耗尽。

## 6. 奖励

### 6.1 Thinking：Consilience

| 参数 | 值 |
| --- | ---: |
| scope | 当前轮完整 thinking |
| top-logprob 数 | `5` |
| 开头跳过比例 | `0.05` |
| 初始/末尾窗口比例 | `0.2` |
| 初始窗口系数 | `3.0` |
| score temperature | `1.0` |
| reward scale | `1.0` |
| reward temperature | `2.0` |

opening action marker 之前的完整 thinking 才能评分。未闭合、非有限 logprob、token 与文本不能严格重建、
或缺少 top-5 processed logprobs 的 rollout 目标质量为零；不回退到 action 或完整响应评分。每个候选固定
使用 `K_rollout=2` 作 Monte Carlo 分母，不因无效 rollout 补采样或改变分母。

一步中所有候选均为零质量时记录 `no_valid_thinking_rollout`，该题该组失败；不能回退 baseline，否则会
改变方法定义并选择性降低 IS 失败率。

上述规则属于旧纯IS协议。新guarded-v2明确将该情况定义为一次已选前缀的普通续写，并使用独立配置和arm tag，
不修改旧协议成绩；不得在运行中临时切换两种定义。

当前 `is_thinking` 实现按本地 `ConsilienceReward` 的定义，先计算每 token 的
`c_t = -mean(top5_processed_logprobs)`，跳过开头 5%，使用长度 20% 的初始/末尾窗口，
得到 `R = mean(c_final) - 3 * mean(c_initial)`。候选权重为
`w_j ∝ (1/2) * Σ_k exp(R_jk / 2)`，用稳定归一化和 categorical sampling，不额外乘 action logprob。
已经到 thinking/action 边界的候选，其未来 thinking 为空，两个条件 rollout 的奖励相同，可复用该完整
thinking 的评分而不再发两次无意义生成请求；日志仍保存两个奖励值，K 的分母不变。

候选和 rollout 使用 `/v1/completions` 的原始 token ID prompt；首轮 prompt 由同一服务的 `/tokenize`
按 mini-swe-agent chat history 模板生成。全量采样响应、top-5、usage、精确前缀核对结果、随机种子、
候选权重、ESS 和选中 token ID 均留存。只把选中候选短块接到前缀，不能把它的整条 rollout 当作选中答案。
正文以选定 thinking 和已生成的 opening marker 为固定 token 前缀，只做一次普通采样，完整回复经官方 parser
解析后才执行工具。服务端 stop 没有识别跨请求的部分 marker 时，可以多生成后再按 token 边界裁掉未选正文；
这些额外实际生成 tokens 仍计入 API 成本，绝不执行它们。

### 6.2 Action：Sequence Log Probability

| 参数 | 值 |
| --- | ---: |
| scope | opening 到 closing action marker，含边界 token |
| reward | action sampled token logprob 之和 |
| reward scale | `1.0` |
| reward temperature | `10.0` |
| selection | reward-weighted categorical resampling |

action logprob 必须来自实际生成响应的 processed sampled-token logprobs。Qwen 的 stop token 若只出现在
logprob 流而不出现在可见 content，沿用已验证的 termination normalization；未知尾缀仍然拒绝。

## 7. 状态隔离与分支

当前 Thinking IS 的候选和 rollout **仅生成直到 thinking/action 边界的文本，不执行 shell action**，
因此共享只读的父轨迹状态即可，不需要为纯文本候选创建 Docker checkpoint；只在正式选中正文通过 parser 后
执行一次命令。若后续扩展到会执行不同 shell action 的轨迹 rollout，则必须继续使用 Docker checkpoint branching：

- 每个候选从完全相同的 agent messages、调用计数和文件系统 checkpoint 开始；
- rollout 在自己的容器分支中执行，不得修改主轨迹工作树；
- 只保留被选候选对应的 messages、agent counters 和 Docker 状态；
- 未选容器和 checkpoint 必须按所有权关系清理，不能全局 prune；
- reward 和官方判题不能读取其他分支的隐藏测试结果。

Thinking 候选本身尚未执行 action，因此可以共享父文件系统。Action rollout 一旦执行命令就必须独立分支。
若只对文本重采样却让所有 rollout 共享可变容器，实验无效。

## 8. 超时与失败口径

30 分钟从任务容器和 agent 初始化完成后、第一次模型请求发出前开始，覆盖模型请求、候选/rollout、工具执行、
checkpoint 和分支清理。镜像拉取与官方 SWE-bench evaluator 单独计时和报告，不占 agent 的 30 分钟。

每次 API、工具和 rollout 的 timeout 都必须裁剪为当前 case 剩余墙钟；不能在 30 分钟到达后继续等待一个
独立的 30 分钟请求。到时父进程先终止子任务并清理本实例容器；没有已完成官方 submission 的记录按未解决
计数。禁止在超时后人工提取工作树补丁补交。

同样，因上下文、累计输出、步数或格式错误结束时，没有正式 submission 就不能把工作树中的半成品当作
已提交补丁送评。保留已经产生的轨迹、错误信息及已有诊断产物，但不在终止后继续生成、修复或补交；
已完成的正式 submission 才使用其原始补丁进入官方 evaluator。每条终态均写入汇总，不能丢弃失败实例。

以下状态均保留并按未解决计入分母：

- `generation_timeout`；
- `trajectory_output_limit`；
- `context_budget_exhausted`；
- `no_valid_thinking_rollout`；
- `no_valid_action_rollout`；
- `agent_step_limit`；
- `format_error` 或 action parser 失败；
- 空补丁、补丁无法应用、官方测试失败；
- API、Docker 或 evaluator 基础设施错误。

基础设施错误必须单列，不能静默重跑直到成功。正式主结果同时报告 raw resolved rate 与排除预先定义的明确
基础设施故障后的 sensitivity rate。

## 9. 数据、模型与官方评测

- 固定使用本地缓存的 SWE-bench Verified 500 题快照和上述 revision；
- 固定 mini-swe-agent commit `25941c89cfbc91eb40b3f8756348c91d9977d57e`；
- 固定本机 served model `qwen3.8-27b` 和 deployment fingerprint；
- API 必须返回每个 sampled token 的 processed logprob、top-5 logprobs、usage 和终止状态；
- 生成阶段不运行官方隐藏测试；
- 三组生成完成后统一调用固定版本官方 SWE-bench harness；
- 下一阶段主指标是固定百题的 `resolved_instances / 100`，不是提交率、局部测试结果或模型自述成功。
  全 Verified 500 题目前不在本轮启动范围内。

现有 `pytest-dev__pytest-7982` baseline smoke 已由官方 harness 判为 `1/1 resolved`，只证明基础生成和判题
链路可用，不证明新 thinking/action 分段或两组 IS 已实现。

## 10. 执行阶段

### Phase A：先 Thinking IS 单题 smoke

2026-09-18 先在 `pytest-dev__pytest-7982` 上运行 Thinking IS，配置为
`configs/qwen38_swebench_thinking_is_smoke.toml`，结果 tag 为
`qwen38-thinking-is-c100-pytest7982-smoke-20260918`。该 smoke 不启动新 baseline 或正文 IS；
后续补齐统一新协议下的 baseline 与第三组验证。各阶段分别验证：

- thinking/action token 边界与文本严格一致；
- Consilience 只读取 thinking top-5；
- Action IS 只累计 action logprob；
- 候选分支文件系统隔离；
- 30 分钟外层截止和容器清理；
- 第 5.2 节的截断判断通过定向测试：短块正常继续、完整/不完整 action、单条/全零 rollout、
  上下文与累计输出耗尽、步数上限、超时中断及无 submission 不补交；
- 三组均可生成官方 predictions 并完成 harness 判分。

smoke 不进入最终准确率统计。

### Phase B：20 题配对 pilot

从已冻结随机百题中按固定 seed、仅依赖 ID 预先选取 20 题，不根据已有通过情况筛选。三组使用
完全相同的实例和基础 seed，执行顺序固定为 baseline、Thinking IS、Thinking + Action IS。

pilot 用于估计每题墙钟、timeout 比例、请求数、前向 token 放大倍数和磁盘峰值。不能根据 pilot 正确率修改
奖励后继续把同一批题当正式确认集；任何协议变化必须使用新 tag 并重新运行三组。

### Phase C：固定随机 100 题配对实验

仅当 Phase B 满足以下 gate 才启动：

- 三组均有 20/20 可评测记录；
- 没有容器、checkpoint 或镜像引用泄漏；
- top-5 与 sampled-token logprob 覆盖完整；
- timeout 和预算终止均能生成可汇总终态；
- 官方 evaluator 可断点续跑且不会重复覆盖已有判分；
- 根据 pilot 实测确认磁盘和预计总时长可接受。

百题使用冻结协议，不根据中途通过率调整参数，不仅测试 baseline 的失败题。旧合并 70% 仅保留为历史参考，
正式比较需要统一新纠错协议的 baseline。任务可分 batch 续跑，但每条记录必须保留相同 config、模型、
数据和实现 fingerprint。

## 11. 报告指标

每组至少报告：

- 官方 resolved 数、比例和 Wilson 95% 区间；
- 相对 baseline 的题目级配对变化：失败转通过、通过转失败、两者都通过、两者都失败；
- generation timeout、context/output budget、格式错误、空补丁和基础设施错误数；
- 平均、中位数、P90 agent 墙钟；
- API 请求、工具调用、checkpoint、输入/输出 token；
- 候选与 rollout 的逻辑前向 token，以及相对 baseline 的放大倍数；
- Thinking IS 的 ESS、最大权重、全零 rollout 步数；
- Action IS 的 ESS、action 长度和 logprob 奖励分布；
- 官方 evaluator 墙钟和测试失败分类。

主比较为两个 IS 组分别对 baseline 的配对 resolved 差异；Thinking + Action IS 还需与 Thinking IS 直接
配对，以回答正文/action IS 是否提供额外收益。

## 12. 当前实现状态

2026-09-18 新增独立 `is_thinking` arm，入口为 `src/inference_scaling/swebench/thinking_is.py`：
固定 chunk=100、M=4、K=2，精确 token ID 续写，完整 thinking 的 Consilience 加权随机选择，正文普通采样。
与 context-aware baseline 共用 1800 秒主线程硬截止、动态上下文、累计选中输出预算及有限格式纠错。
旧配置未指定 `max_consecutive_format_errors` 时默认保留首次错误即停的行为；新实验显式设置为 3。
新增适配拒绝响应的脱敏审计留存，但没有据此认定历史 scikit-learn 重建问题已修复。

服务端启动参数已核验为 `processed_logprobs`、`max-logprobs=5`、temperature/top-p=1、top-k 禁用。
已通过不执行命令的真实接口 Conditional IS 探针，以及相关回归测试；单题正式工具执行和官方判题结果
以 smoke 产物为准，不能把探针成功当作题目通过。

2026-09-18 首个 Thinking IS smoke 已由官方判为 `pytest-dev__pytest-7982` 的 `1/1 resolved`，
包含 11 轮 agent 交互和 12 步 IS 选择，实际覆盖一轮两步分块；详见
[chunk=100 单题验证报告](../reports/QWEN38_SWEBENCH_RANDOM100_THINKING_IS_BASELINE_COMPARISON.md)。这不证明百题收益。

`is_thinking_action_logprob` 尚未实现，也未启动。旧通用 `method="is"` 仍是完整 decision / 轨迹采样，
不能冒充本方案两个新方法。百题和第三组都需在后续 gate 满足后另行启动。

## 13. 提交与收尾协议更新（2026-09-24，本机日志时间）

本节描述后续运行使用的`RESULT_SCHEMA_VERSION=swebench-is-mh-v7`和
`TASK_ENVIRONMENT_PROTOCOL=swebench-testbed-v2`。此前27题补跑使用冻结的v6源码，
不受当前工作目录修改影响；不得用新协议隐式续写或覆盖旧批次。

### 13.1 提交校验

执行环境捕获mini-swe-agent的`Submitted`事件后，先验证提交非空、含git diff头，
并在隔离临时目录通过`git apply --numstat -z -`检查语法，不修改任务仓库、不运行官方测试。
解释性文本、空内容、损坏的diff会作为工具失败反馈给agent，允许在原预算内纠正，
不会成为正式提交，也不会补写或猜测答案。每次校验保存结果、错误及提交内容SHA256。

校验只证明补丁语法可解析，**不保证能应用到基准checkout，更不证明测试通过**。
最终应用与正确性仍以官方评测为准。删除、重命名和git binary diff均有回归覆盖。
进程`status=completed`仍只表示轨迹结束，不代表有效提交或resolved。

### 13.2 工具命令的退出状态

每次激活testbed后，使用`bash -o pipefail -c`执行原命令，使`pytest ... | tail`中的
上游失败不再被tail的成功返回码掩盖。不启用全局`set -e`，避免破坏显式错误处理。
因此`失败命令; 成功命令`、`|| true`、主动关闭pipefail以及嵌套shell仍可能改变退出状态；
不能声称任意组合命令的所有失败均能被自动识别。共同prompt要求测试独立执行并检查实际测试汇总。

### 13.3 轮次收尾及未提交补丁审计

新增默认`agent.finalization_reserve_steps=5`，在剩余模型调用次数进入最后5次时插入一次收尾提醒。
提醒会在tokenize之前加入上下文，计入上下文约束；不增加250轮预算、输出预算或API预算，
也不将Thinking IS切换为普通采样。checkpoint保留提醒消息，恢复后不重复插入。
设置为0可关闭；该字段纳入配置fingerprint。

`agent.audit_patch_timeout_seconds`默认由0改为10秒。预算终止等未提交状态在清理容器前，
只读保存已跟踪文件的`git diff --binary HEAD`与未跟踪文件名清单，供诊断使用。
每项输出最多保留1MiB并标记截断，未跟踪文件内容不保存。审计失败只记录错误，
**审计diff不会成为正式submission，不会改变preds或官方通过率**。设置为0可关闭。

这两个默认值的变化会改变旧TOML在新代码下解析得到的配置fingerprint；复现实验需使用对应冻结源码。
上述运行保护同时用于baseline与Thinking IS，后续严格配对比较应统一新协议。

### 13.4 压缩采样明细

新运行将`diagnostics.thinking_is`完整明细无损写入独立的
`thinking_is.<SHA256>.json.gz`，主`record.json`仅保留协议、保护参数、请求/轮次数量与文件引用，
其他基础指标、提交、usage及终止原因仍保留。先原子写明细，再发布record；断点续跑检查引用和校验和。
官方预测重建和日常汇总只读轻量record，不必反复解析完整采样记录。

需要完整诊断时使用：

```python
from pathlib import Path
from experiments.swebench.io import load_record

record = load_record(Path("实际题目目录/record.json"), include_sampling_details=True)
requests = record["diagnostics"]["thinking_is"]["requests"]
```

该读取方式也兼容历史内联明细。归档时必须将record与其引用的gzip文件一起保存；
外部分析脚本不能再假定v7主record内总有完整requests和rounds列表。
此次优化减少落盘及日常汇总成本，**没有实现采样过程的流式内存释放**。

### 13.5 验证范围

- 211项SWE-bench回归测试通过；本次修改文件的ruff及`git diff --check`通过。
- 使用真实Django任务容器验证：失败测试管道保留退出码7、拒绝73字节解释性“提交”、
  接受真实diff、收尾只提醒一次、只读补丁审计不改变正式提交，模型API调用数为0，容器正常清理。
- 对历史astropy-13236记录的副本测试：原record为13,663,355字节，新摘要10,681字节、
  gzip明细963,108字节；完整还原相等，历史源文件SHA256未改变。
- 验证证据保存在`results/analysis/swebench-runtime-safety-20260924/`。
- 这不是新模型解题实验，不据此宣称通过率提升，也未自动启动新的补跑。
