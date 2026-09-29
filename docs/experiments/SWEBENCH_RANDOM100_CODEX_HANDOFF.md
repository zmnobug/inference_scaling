# SWE-bench 固定百题：另一 Codex 会话的复跑 Prompt

将下文完整交给另一个 Codex 即可。文档内嵌全部题目 ID，不依赖原机器的未提交清单文件。默认目标是独立运行 baseline 与 Thinking IS 两组；如果只需要 baseline，可明确要求先只执行 baseline。

## 可直接使用的 Prompt

请在独立工作目录中，对下面固定的 SWE-bench Verified 100 道题进行独立复跑。不是重新随机抽样，也不是运行 Verified 全集。先核对环境、完成单题 smoke，再后台运行百题和官方评测。

### 1. 代码与运行边界

- 仓库：`https://github.com/zmnobug/inference_scaling.git`。
- 分支：`feat/swebench-integration`。
- 本次复跑代码基线：`ac23896b653590ebe7c9dafa4e22b26fd8c573f2`。固定该提交；如果采用后续代码，必须记录差异，不要静默更新版本。
- 该提交已经包含合法零 thinking 候选的流程修复。不要改成“所有候选无分数就失败”，也不要给无效候选伪造奖励。
- 先读工作区适用的 AGENTS.md，再阅读 `experiments/swebench/` 和 `src/inference_scaling/swebench/`。
- 不修改原实验目录、不覆盖已有结果、不停止别人的服务、不自动占用全部 GPU、不推送代码。使用独立输出目录、run tag、日志及评测 run prefix。
- 模型服务名称 `qwen3.8-27b` 是原实验的本地部署标识，不能据此猜测实际模型权重。先向用户核对模型路径或可用服务地址、GPU/端口使用范围；没有授权就不要启动或关闭其他服务。
- 当前远端不包含原机器所有未提交文件。不要假设远端有 random100 配置、百题清单、双服务启动脚本或历史报告；清单直接用本文，配置从已提交模板生成。
- 特别注意：原机器还有未提交的独立 reasoning/logprobs 兼容处理、拒绝响应审计和磁盘保护等改动。`ac23896` 不是完整历史运行环境快照。先检查这些差异是否影响当前服务；如需迁移兼容补丁，先说明范围并记录 patch/hash，不得静默修改评分规则，或宣称只用远端提交就能精确复现历史结果。

### 2. 固定数据、agent 和公共参数

- 数据集：`SWE-bench/SWE-bench_Verified`；split：`test`。
- 数据集 revision：`78f471bf655a3137b2e8a75af1501690ec009ec3`。
- 题目：本文末尾固定 100 个 instance_id，禁止重新抽样、漏题或重复计数。
- mini-swe-agent commit：`25941c89cfbc91eb40b3f8756348c91d9977d57e`。
- Agent 配置：`swebench_xml.yaml`；`action_mode="text"`；Docker 环境。
- 原归档 Python 为 3.11.15，SWE-bench harness 为 5.0.1；记录实际安装版本。
- seed：`20260916`；temperature：`1.0`；top_p：`1.0`。
- `agent.max_trajectory_output_tokens=131072`：一题主轨迹累计输出预算，包含 thinking 与正文，不是只限制最终答案，也不是全部候选/rollout 的总计算量。
- `agent.context_window=133120`；`agent.context_safety_tokens=256`：单次调用输入加输出的上下文边界与安全余量。
- 普通生成的单次输出还受剩余主轨迹预算和剩余上下文共同限制，不能无条件要求每次输出 131072 tokens。
- `agent.step_limit=250`；`agent.cost_limit=0`；`budget.max_tool_calls=250`。
- `budget.max_input_tokens=0`；`budget.max_output_tokens=0`，不要误以为这会取消上面的主轨迹输出预算。
- 单 API 请求 `timeout_seconds=1800`；`max_retries=0`；`seed_supported=true`；`logprob_mode="visible_tokens"`。
- 每个 runner 使用 `workers=1`。如使用两个独立模型服务，可把清单拆成互斥分片分别运行；分片并集必须严格等于这 100 题，不要直接把 context-aware runner 改成多线程。

### 3. 两组配置

先复跑以下两组；本次不增加 MH，也不增加正文 IS/logprob 奖励组。

| 参数 | Baseline | Thinking IS |
| --- | --- | --- |
| `arms.method` | `base` | `is_thinking` |
| `arms.chunk_tokens` | `131072`，普通生成上限配置 | `100` |
| 候选数 / rollout 数 | 不适用 | `candidate_count=4` / `rollout_count=2` |
| thinking | 普通生成 | Conditional IS + Consilience |
| 正文 | 普通生成 | 普通生成 |
| `agent.wall_time_limit_seconds` | `1800` | `0`，不设整题时间上限 |
| `budget.max_wall_seconds` | `7200`，但 agent 的 1800 秒先约束 | `0` |
| `budget.max_api_requests` | `250` | `50000` |
| `agent.max_consecutive_format_errors` | `1` | `3` |

Thinking IS 使用原有按块多步流程：生成 4 个短块，对每个候选做 2 次 rollout，根据奖励权重采样选中一个块，接入前缀后继续。不是一次生成 4 条完整答案择优，也不是永远选分数最高的候选。

Consilience 参数保持代码默认：`top_k=5`、`skip_fraction=0.05`、`window_fraction=0.2`、`initial_penalty=3.0`、`scale=1.0`，奖励温度 `2.0`。奖励只用于 thinking；正文不做 IS。不要启用额外 `max_steps_per_round` / `max_round_seconds` / `max_rollout_tokens` 保护或 `fallback_to_plain` 来改变实验协议。

这些参数保留历史两组的预算差异，因此不是严格等预算的算法因果对照。如果用户要求公平预算重测，先提出统一整题时间和格式错误策略的方案，经确认后使用新的实验标签，不要悄悄改动本协议。

### 4. 环境与启动步骤

1. 将文末清单原样保存为 `configs/qwen38_swebench_random100_instances.txt`，UTF-8、LF 换行，末尾保留换行。确认共 100 行、100 个不同 ID。
2. 从已提交的 `configs/qwen38_swebench_random5_baseline.toml`、`configs/qwen38_swebench_thinking_is_smoke.toml` 生成独立百题配置，按上表设置参数。清空 `instance_filter` 和 `instance_slice`，避免遗留五题/单题筛选；不要直接用只含 70 题的历史配置跑百题。
3. 设置独立 run tag、输出目录、真实 deployment_id，并通过 `OPENAI_API_BASE` / `OPENAI_API_KEY` 配置服务。不要把密钥写进日志或提交。
4. 用项目 `experiments/swebench/bootstrap.sh CONFIG` 建立环境，或核对已有环境。检查 Docker、磁盘、内存、模型权重和上下文配置。不要直接照抄原机器 `/tmp` 虚拟环境路径；未缓存数据或模型时不要开启离线模式。
5. 原服务参考配置：TP=4、FP16、`max_model_len=133120`、`max_num_seqs=8`、`max_num_batched_tokens=8192`、prefix caching 开启、processed top-5 logprobs。8192 是服务调度批次 token 参数，不是单轮输出上限。不同硬件/服务设置需记录，耗时不能直接与历史混比。
6. Thinking IS 需要 `/tokenize`、`/detokenize`、`/v1/completions`，以及准确的 prompt/output token ID、sampled logprob、top-5 logprobs。执行项目 preflight 和相关测试；不能只验证 chat 接口能返回文本就启动百题。
7. 检查独立 reasoning 字段的处理，确保不丢弃 thinking、不伪造缺失 logprobs、不把不完整动作当合法提交。遇到接口兼容异常先报告证据并修正兼容问题，不要让同一错误扩散到 100 题。
8. 从本清单选一题（例如 `pallets__flask-5014`）先跑两组 smoke，使用独立 smoke tag，并完成官方评测。Smoke 只验证生成、补丁导出、评测闭环，不保证这题必然通过。正式百题重新跑，不按成功与否挑选复用 smoke 结果。
9. 确认闭环后，用 nohup、tmux 或可用作业管理器后台运行，保证断开会话后不退出，保存 PID、日志、启动命令、生成和评测退出码。不要把断开会话的口头承诺当作后台运行验证。
10. 生成与评测分别调用项目入口，示意如下。`CONFIG_PATH`、`RESULTS_DIR`、`UNIQUE_RUN_PREFIX` 需替换为实际值；`RESULTS_DIR` 是含 `manifest.json` 的目录。

```bash
./run_swebench.sh CONFIG_PATH --instance-file configs/qwen38_swebench_random100_instances.txt
./evaluate_swebench.sh RESULTS_DIR --max-workers 1 --run-prefix UNIQUE_RUN_PREFIX
```

`--max-workers` 在第二条命令中控制官方评测并发，不是模型生成并发。只有需要额外功能且代码实际支持时才添加 CLI 参数，不要照抄尚未提交脚本里的 `--min-free-gib` 等参数。

### 5. 结果要求

- 每题记录：instance_id、实验组、是否生成正式非空 patch、agent exit_status、官方 resolved、失败阶段/原因、解题耗时、评测耗时、API 次数、工具调用数。
- 分开统计：主轨迹累计输出、包含候选和 rollout 的全部 API 输出、最大单轮完整输出、最大单轮 thinking 长度、最大单轮输入加输出。缺少准确 token 数据就明确标注缺失或估算，不能把不同口径混在一起。
- 保存每题轨迹、正式 patch、API 审计、官方测试报告、数据集快照、配置、git SHA、环境/服务指纹及新增兼容补丁。不得将 gold patch 或官方隐藏测试内容用于 agent 求解或 IS 候选评分。
- 正式通过率分母固定为 100；完整流程失败也必须计入。运行中可以报告已评测题通过率，但不能冒充百题最终通过率。
- 输出 Markdown 报告与逐题 CSV，汇总通过率、流程失败率、耗时总量/均值/中位数/P90、token 开销，以及两组都过、仅 baseline 过、仅 IS 过、两组都不过的四格表。
- 新实验结果独立统计，不能按题混选最好结果。历史参考为 baseline 70/100、IS 合并结果 69/100；其中 IS 是 91 道旧版本记录加 9 道修复后重跑，不是统一 v3 百题结果。不要把历史数字当作本次应达到的目标，也不要伪称逐题确定性复现。
- 先汇报代码版本、清单校验、资源与服务、最终参数以及 smoke 结果，再持续汇报百题进度；未运行或失败的步骤必须如实说明。

### 6. 固定 100 题清单

清单 SHA-256：`559abe0a8499a40f0c82837f1b9cdf79ccaead21cd21555878ef1b7c5e8461eb`。

```text
pydata__xarray-6938
django__django-11951
pytest-dev__pytest-5787
sphinx-doc__sphinx-10614
sympy__sympy-15976
django__django-14534
django__django-13837
matplotlib__matplotlib-26291
django__django-13569
astropy__astropy-13236
django__django-12155
sympy__sympy-14711
django__django-15380
matplotlib__matplotlib-25960
django__django-14771
sphinx-doc__sphinx-11445
sympy__sympy-22914
matplotlib__matplotlib-25332
sympy__sympy-20801
matplotlib__matplotlib-23476
django__django-13315
pytest-dev__pytest-10356
django__django-13346
sphinx-doc__sphinx-9258
sympy__sympy-13615
django__django-16938
sympy__sympy-17139
pytest-dev__pytest-7236
sphinx-doc__sphinx-9673
django__django-15695
astropy__astropy-14365
django__django-15382
scikit-learn__scikit-learn-14894
scikit-learn__scikit-learn-25931
astropy__astropy-8872
django__django-12273
sphinx-doc__sphinx-9711
psf__requests-2931
sphinx-doc__sphinx-7889
django__django-11848
django__django-14315
sphinx-doc__sphinx-8551
sympy__sympy-21847
astropy__astropy-14508
matplotlib__matplotlib-13989
scikit-learn__scikit-learn-25102
astropy__astropy-12907
sympy__sympy-16597
pydata__xarray-7393
matplotlib__matplotlib-24570
django__django-12419
sphinx-doc__sphinx-8548
sphinx-doc__sphinx-8721
sphinx-doc__sphinx-7454
pydata__xarray-6599
django__django-15098
django__django-13810
django__django-13406
django__django-13212
django__django-15973
django__django-16662
sympy__sympy-13372
django__django-13195
sympy__sympy-18211
django__django-15554
matplotlib__matplotlib-20826
django__django-13658
django__django-13363
django__django-14580
matplotlib__matplotlib-24637
django__django-14493
sympy__sympy-18763
django__django-11603
pallets__flask-5014
django__django-9296
astropy__astropy-7671
django__django-11532
django__django-11099
django__django-14089
astropy__astropy-14995
sympy__sympy-22456
django__django-14017
django__django-11477
matplotlib__matplotlib-26466
django__django-13279
django__django-16333
django__django-16801
django__django-11964
scikit-learn__scikit-learn-11310
sphinx-doc__sphinx-9658
sympy__sympy-23413
django__django-14404
django__django-17087
django__django-11728
django__django-11211
django__django-12325
django__django-15525
django__django-10554
sympy__sympy-17318
matplotlib__matplotlib-20676
```
