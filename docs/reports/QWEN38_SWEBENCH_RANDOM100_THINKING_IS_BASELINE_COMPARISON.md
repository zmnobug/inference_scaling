# Qwen3.8-27B × SWE-bench Verified：固定100题 Baseline / Thinking IS 完整报告

结果更新至2026-09-24（北京时间）。**最新百题合并结果：Thinking IS 71/100，历史baseline 70/100；相对baseline救回6题、回退5题，净差＋1个百分点。** 全部100题清单、官方通过状态、耗时与成本见第15节。71/100由73条完整v3记录与全部27条环境修复补跑记录组成，不是统一修复版本重跑百题。最近完整v3单轮63/100、历史混合版本69/100均独立保留。

这是本项目保留的**唯一SWE-bench实验结果汇总文档**。阅读入口：**第15节为最新完整100题对照**；第14节保留统一v3结果、回退分析及27题补跑过程，第0/9节为历史混合69结果，第11节保留baseline长度分布及全部100行原CSV数据，第12节为阶段验证/修复摘要，第13节为复现入口与实验隔离说明。多轮累计覆盖81/100不混入71/100主表。

本报告为**历史baseline与不限时Thinking IS的百题汇总对照**，不是同协议、同计算预算的随机对照实验。所有结果均来自已归档运行；本次编写报告没有重新生成补丁、修改评测结果、启动补跑或修改采样代码。

## 0. 历史混合版本结果：零thinking修复后九题整体替换（2026-09-20）

**历史合并百题结果：baseline 70/100，Thinking IS 69/100；救回10题、回退11题，净差−1个百分点。** 原始IS 62/100完整保留在第1–8节及第10节历史审计中，第9节为这一历史混合版本的100题逐题明细。最新完整v3结果以第14节为准。

### 0.1 合并口径与完成状态

- 原始IS百题全部使用v2；本次仅将全部9道 `no_valid_thinking_rollout` 的记录替换为v3独立单次补跑，成功和失败都替换，不择优、不续接旧轨迹。其余91题以及baseline的89＋11题合并口径不变，补充baseline B2仍不混入。
- **69/100是91条v2轨迹＋9条v3轨迹的混合版本汇总，不是v3重新完整运行100题的成绩**；这9题因已知流程异常被选中，也不是随机抽取的准确率样本。仍属于历史对照，不宣称严格同预算或纯IS因果收益。
- 新批次I9：`results/swebench/qwen38-thinking-is-empty9-rerun-unlimited-dual/`；2026-09-20 14:24:54启动、20:53:40结束（北京时间），后台日志墙钟约6小时29分钟，汇总器计时6小时28分41秒。两分片生成、官方评测和汇总均退出0；9题全为Submitted、非空补丁，正式通过7题。
- v3只修复合法零thinking候选全不可评分时的均匀选择；M=4、K=2、chunk=100、L=131072、上下文133120、seed=20260916不变，thinking用Conditional IS＋Consilience，正文普通生成，不设整题时间限制。

### 0.2 百题主指标


| 指标 | 历史baseline | 原始IS（v2） | 最新合并IS（91＋9） |
| --- | --- | --- | --- |
| 官方通过／固定100题 | 70（70%） | 62（62%） | 69（69%） |
| 相对baseline通过率 | — | −8个百分点 | −1个百分点 |
| 两者均通过 | — | 55 | 59 |
| baseline未过、IS通过（救回） | — | 7 | 10 |
| baseline通过、IS未过（回退） | — | 15 | 11 |
| 两者均未通过 | — | 23 | 20 |
| 非空正式补丁 | 96 | 91 | 100 |
| 无正式补丁 | 4 | 9 | 0 |
| 非空补丁未通过 | 26（含1歧义） | 29（含1歧义） | 31（官方标记2歧义，其中5787已确认误报） |
| no_valid_thinking_rollout终止 | 不适用 | 9 | 0 |
| 整题超时／上下文／L上限终止 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |
| 官方evaluator错误 | 0 | 0 | 0 |


原成功保留率59/70＝84.29%，回退率11/70＝15.71%；原失败救回率10/30＝33.33%。官方汇总为31题未通过，其中2题被启发式标记 `no_tests_collected`：`pytest-dev__pytest-10356`（旧结果）及 `pytest-dev__pytest-5787`（本次补跑）。后续逐日志复核确认5787实际执行127项测试，并有明确PASS_TO_PASS失败，属于标签误报而非未收集测试。因此当前实质归因为30题有实际测试失败、1题10356的歧义标签未在本次十一题审计中复核；原始官方标签不改写，31题仍全部按未通过计分。详见第0.9节。

### 0.3 九题替换明细

九题旧IS均在零thinking状态退出、没有正式补丁。下表时间为runner分钟，包含该题agent及少量runner开销；不是官方判题耗时。


| 题目 | Baseline | 旧IS分钟 | v3分钟 | v3正式结果 | 合并后关系 |
| --- | --- | --- | --- | --- | --- |
| django__django-12325 | 未通过 | 7.94 | 8.34 | 通过 | 救回 |
| matplotlib__matplotlib-20826 | 通过 | 88.43 | 40.69 | 通过 | 两者均过 |
| matplotlib__matplotlib-24637 | 未通过 | 21.03 | 19.58 | 通过 | 救回 |
| matplotlib__matplotlib-25960 | 通过 | 0.70 | 189.74 | 通过 | 两者均过 |
| pallets__flask-5014 | 通过 | 0.37 | 1.12 | 通过 | 两者均过 |
| pytest-dev__pytest-5787 | 通过 | 1.69 | 19.32 | 未通过：兼容性回归（官方误标） | 回退 |
| sympy__sympy-17139 | 通过 | 1.57 | 2.15 | 未通过：测试失败 | 回退 |
| sympy__sympy-22456 | 未通过 | 1.71 | 127.20 | 通过 | 救回 |
| sympy__sympy-23413 | 通过 | 1.39 | 222.84 | 通过 | 两者均过 |


v3轨迹审计：本次7题合计28个选择步实际使用 `empty_thinking_uniform`；其余选择沿用原规则。九题均正常提交不等于全部正确；修复恢复了执行能力，7题随后通过。所有九题API失败数为0。

### 0.4 救回10题、回退11题如何变化

- 原7道救回全部保留，详见历史第6节；新增3道救回：`django__django-12325`、`matplotlib__matplotlib-24637`、`sympy__sympy-22456`。三题原baseline也未通过，原IS则流程失败，本次v3官方通过；这是流程修复后的实测恢复，不应直接归因于奖励选择的独立贡献。
- 原6道“baseline通过、IS零thinking终止”中，4道恢复通过：`matplotlib__matplotlib-20826`、`matplotlib__matplotlib-25960`、`pallets__flask-5014`、`sympy__sympy-23413`；另2道仍未通过：`sympy__sympy-17139`的复数指数处理失败，`pytest-dev__pytest-5787`的反序列化兼容性测试失败；后者官方“未收集测试”标签经复核为误报。
- 剩余原9道补丁错误回退没有重跑，仍为：`astropy__astropy-13236`、`django__django-11964`、`django__django-13406`、`django__django-14404`、`django__django-14771`、`django__django-15973`、`psf__requests-2931`、`sphinx-doc__sphinx-9711`、`sympy__sympy-18211`。具体失败机制仍见历史第7.2–7.10节。
- 因此当前11道回退不再包含零thinking流程终止，逐日志复核后全部有实际测试失败证据：9题FAIL_TO_PASS未修好，2题PASS_TO_PASS回归。历史第7节的15题表仅用于追溯修复前状态。

### 0.5 最新时间与计算开销

以下百题统计每题只取最终保留的一条轨迹：9题旧失败运行的成本被替换，不计入“合并百题”，但必须计入实际历史花费。分位数使用nearest-rank；中位数取中间两项均值。Baseline和原始IS口径不变。


| 时间指标 | Baseline | 原始IS | 合并IS |
| --- | --- | --- | --- |
| Agent均值／分钟 | 3.65 | 20.42 | 25.48 |
| Agent中位／分钟 | 2.54 | 8.93 | 10.08 |
| Agent P90／分钟 | 7.43 | 60.53 | 64.96 |
| Agent P95／分钟 | 11.11 | 88.41 | 106.94 |
| Agent最长／分钟 | 23.49 | 120.48 | 222.82 |
| Runner累计／小时 | 6.10 | 34.05 | 42.49 |
| Agent超过30分钟／题 | 0 | 19 | 22 |

| 成本指标 | Baseline | 原始IS | 合并IS | 合并IS / Baseline |
| --- | --- | --- | --- | --- |
| 模型请求数 | 3,242 | 34,667 | 38,862 | 11.99倍 |
| 累计输入tokens | 44,007,454 | 534,157,985 | 620,042,911 | 14.09倍 |
| 累计输出tokens | 606,360 | 3,937,509 | 4,940,519 | 8.15倍 |
| 接入主轨迹输出tokens | 605,664 | 577,211 | 640,577 | 1.06倍 |
| 工具调用数 | 3,238 | 2,936 | 3,147 | 0.97倍 |
| API累计秒数 | 17,701.01 | 118,101.01 | 147,816.92 | 8.35倍 |
| 工具累计秒数 | 3,849.41 | 2,801.47 | 3,241.07 | 0.84倍 |


- 合并IS累计runner为42.49小时，是baseline的6.96倍；当前通过数仍少1题，没有整体准确率提升结论。
- 计算关系：原始百题34.05小时 − 被替换旧九题2.08小时 ＋ 新九题10.52小时 ＝ 合并百题42.49小时。
- 实际执行过的“原始IS百题＋本次九题”累计runner为44.57小时，不能将旧失败尝试的花费视为不存在；该数仍不含历史pilot、其他补跑、评测、服务启动与磁盘等待等。
- 合并百题跨批次、跨采样版本，没有一段对应的真实统一墙钟，不把runner求和或除以2冒充整批实测耗时。本次九题实际墙钟约6小时29分钟；九题中4题超过30分钟且均通过，但这不是30分钟截断策略的对照试验。

### 0.6 最新主轨迹长度与thinking行为

单轮为已选中并接入主轨迹的完整模型决定，含thinking＋动作正文；输入含历史与工具输出。候选及rollout只进入API账本，不进入主轨迹累计L。以下每题先取峰值，再对100题统计；不是所有内部API调用的峰值。


| 口径／tokens | 方法 | 均值 | 中位 | P90 | P95 | 最大 |
| --- | --- | --- | --- | --- | --- | --- |
| 每题累计主轨迹输出 | Baseline | 6,056.64 | 4,163.50 | 13,432 | 18,314 | 42,013 |
| 每题累计主轨迹输出 | 合并IS | 6,405.77 | 4,405.50 | 13,912 | 20,203 | 26,469 |
| 每题单轮已选完整输出峰值 | Baseline | 613.81 | 472.50 | 1,174 | 1,562 | 2,152 |
| 每题单轮已选完整输出峰值 | 合并IS | 634.22 | 542.00 | 1,185 | 1,499 | 1,823 |
| 每题单轮已选输入峰值 | Baseline | 16,562.27 | 13,749.00 | 30,400 | 37,729 | 68,780 |
| 每题单轮已选输入峰值 | 合并IS | 16,880.49 | 14,455.00 | 31,003 | 40,064 | 51,551 |
| 每题单轮已选输入＋输出峰值 | Baseline | 16,648.10 | 13,845.50 | 30,564 | 37,798 | 68,835 |
| 每题单轮已选输入＋输出峰值 | 合并IS | 16,974.07 | 14,504.00 | 31,045 | 40,162 | 51,657 |

| Thinking指标 | 合并IS |
| --- | --- |
| 尝试轮次／形成决定轮次 | 3,150 / 3,150 |
| 每轮已选thinking均值／中位tokens | 100.41 / 47.0 |
| 每轮已选thinking P95／最大tokens | 394 / 1,764 |
| 每题thinking峰值P95 | 1074 |
| 已选thinking≤100 tokens | 2,325/3,150（73.81%） |
| 候选选择步数／每决定平均步数 | 5,193 / 1.65 |
| ESS均值／中位 | 2.809 / 3.000 |
| 已选thinking tokens总和 | 316,303 |


统计包含合法零thinking轮次。chunk=100仍不是“每轮平均4块”的保证；ESS仅描述权重集中程度，不等同奖励有效性。未选分支仍受L与上下文预算约束，不能根据已选峰值直接断言降低上限不会改变结果。

### 0.7 分项目最新结果


| 项目 | 题数 | Baseline通过 | 合并IS通过 | 救回 | 回退 |
| --- | --- | --- | --- | --- | --- |
| astropy | 7 | 6 | 5 | 0 | 1 |
| django | 46 | 31 | 31 | 5 | 5 |
| matplotlib | 10 | 7 | 8 | 1 | 0 |
| pallets | 1 | 1 | 1 | 0 | 0 |
| psf | 1 | 1 | 0 | 0 | 1 |
| pydata | 3 | 1 | 2 | 1 | 0 |
| pytest-dev | 3 | 2 | 1 | 0 | 1 |
| scikit-learn | 4 | 3 | 4 | 1 | 0 |
| sphinx-doc | 11 | 9 | 9 | 1 | 1 |
| sympy | 14 | 9 | 8 | 1 | 2 |


### 0.8 本次审计与后续事项

- 核验固定100题唯一ID、9题补跑完整替换、其余91题完全不变、baseline不变；两分片CSV与官方resolved集合一致，manifest名单与assignment及配置指纹一致，服务runtime指纹与原IS对应服务一致。
- `parent_cases.json`的原批次CSV哈希仍匹配；两分片及汇总退出0；九题新记录和原百题报告独立保留。重新从主轨迹及采样诊断提取长度、thinking和ESS，没有从聊天中的四舍五入数字反推。
- v3源码快照中的 `thinking_is.py` SHA-256为 `8444f42e5af046fbdefa13705495a811609bdf68f690588689de22413972fab0`；仅I9使用v3，不能将原91题标成新代码运行。
- 后续十一题代码及日志复核已完成，见第0.9节；5787的测试收集标签已在本报告纠正为误报。正式评估v3整体效果仍需另行确认是否统一协议跑全100题；本次诊断只读取归档、运行离线审计与专项测试，不启动新模型实验。

新增证据哈希（原始百题哈希仍见历史第10节）：


| 文件 | SHA-256 |
| --- | --- |
| `results/swebench/qwen38-thinking-is-empty9-rerun-unlimited-dual/assignment.json` | `489270c5019163b5fcd8a810b56c055b764a4f9cc6d4dd7d02155d63f7e16f5e` |
| `results/swebench/qwen38-thinking-is-empty9-rerun-unlimited-dual/parent_cases.json` | `bb421ec0fdf13d010fd7c1e1d5c7594175addd482055328f17ab741da1e1f0f0` |
| `results/swebench/qwen38-thinking-is-empty9-rerun-unlimited-dual/summary.json` | `1744f655465ef97076a345fba73ad78ba34ff3830fea398e97d9a1afce1c858f` |
| `results/swebench/qwen38-thinking-is-empty9-rerun-unlimited-dual/case_timings.csv` | `37a50065931d5369bd58a527d9ad86119312071f8ff7e797fafa1f35a36abc8d` |
| `results/swebench/qwen38-thinking-is-empty9-rerun-unlimited-dual/inputs.sha256` | `a1b3fe253ff54c6c2ba88c51c4e9063c634fd7ed4d15e224556e93b84374ab98` |
| `results/swebench/qwen38-thinking-is-empty9-rerun-unlimited-dual/shard_a/qwen38-thinking-is-c100-empty9-rerun-unlimited/evaluation/reports/is_thinking-a1-b4-c100-r2/seed-20260916.json` | `e507beac85d6d1a3af13049ae3d762707ba1f9bc77016c6df15bf036f028723e` |
| `results/swebench/qwen38-thinking-is-empty9-rerun-unlimited-dual/shard_b/qwen38-thinking-is-c100-empty9-rerun-unlimited/evaluation/reports/is_thinking-a1-b4-c100-r2/seed-20260916.json` | `fe05fe9cf0f57e3f26562faf990e116d68a31c8873ae3c7438de784af97cba20` |

### 0.9 十一道回退的实现审计（2026-09-20）

**结论：尚未发现能够解释这11题回退的、已经证实的IS采样实现错误；确认了一处官方评测器的辅助标签误报，以及本报告此前直接采用该标签的归因错误。11题均已正常提交，补丁正确应用，且都有实际失败测试，不能继续归入零thinking流程问题。** 本次不改采样代码、不改官方原始结果、不启动模型补跑；69/100及救回10题、回退11题保持不变。

#### 0.9.1 查了哪些链路

- 范围是当前合并表的全部11道回退：9道保留的v2轨迹＋2道v3轨迹（pytest5787、sympy17139），不是旧15题，也没有把9道补跑中的通过题混入。
- 从每题原始 `record.json` 读取完整completion响应，使用本地同一模型的 `tokenizer.json` 和当前v3采样代码离线重放，禁止访问模型服务；重放输入是已归档响应，不是重新生成答案。合计核验 **4,019次模型请求、347轮主轨迹决定、545步候选选择**。
- 核验每次请求的role、max_tokens、请求seed、prompt token IDs及SHA-256、token计数、逐token/top-5 logprobs；核验全部候选及rollout的奖励、权重、ESS、随机选择索引、已选前缀和thinking边界；重建正文与动作解析结果，逐轮与实际轨迹对齐。
- 4,019次请求账本与usage累计输入／输出一致；347轮最终文本、token IDs、logprobs及已执行动作都与重放一致。11题API失败0、动作解析失败0，没有将候选rollout当成主轨迹执行、丢失已选前缀、拼接错正文或未记录截断的证据。
- 最终 `record.submission`、`trajectory.info.submission`、`preds.json.model_patch` 与官方评测目录 `patch.diff` 全部一致；所有补丁应用成功。对比baseline／IS的冻结dataset快照，11题的repo、base_commit、题面、test_patch、FAIL_TO_PASS和PASS_TO_PASS定义一致；baseline对应官方报告确实通过。
- 独立算式复核：Consilience按尾窗口均值减3倍初窗口均值，跳过前5%、窗口20%；选择质量为各候选 `mean(exp(reward / 2))` 再归一化，无效rollout保留固定分母。与实现结果一致，未发现奖励符号、softmax温度或K平均写错。
- 专项测试：`tests/test_swebench_thinking_is.py`、`tests/test_swebench_baseline.py`、`tests/test_rewards.py`、`tests/test_swebench_evaluation_summary.py`，合计 **73 passed**。离线重放和专项测试均未执行新模型请求。

定位实现：`src/inference_scaling/swebench/thinking_is.py:72`（权重）、`:136`（模型请求）、`:185`（边界）、`:203`（奖励）、`:220`（轮次拼接）、`:284`（候选／rollout选择）、`:345`（动作构建）；`src/inference_scaling/swebench/miniagent.py` 的 `MiniAgentSession.apply_decision` 执行最终选中动作。

边界额外检查：django15973第17轮的一个候选响应文本停在XML标记，但最后一个完整token实际是 `>/`；当前实现保留完整token而不是按文本切掉 `/`，该候选也未被选中。其余请求的本地解码与响应文本相同，所有已选完整回答均与实际轨迹一致，未把此现象误判为新的重建错误。

#### 0.9.2 十一题逐题结论

下表请求／轮次／选择步为本次离线重放覆盖数量。具体失败均来自该题官方 `report.json.tests_status` 与 `test_output.txt`；其中九道保留的v2问题，其补丁细节仍可对照第7节。

| 题目 | 请求／轮次／选择步 | 实际失败证据 | 当前归因 |
| --- | --- | --- | --- |
| astropy__astropy-13236 | 149 / 21 / 26 | `test_ndarray_mixin[False]`、`test_structured_masked_column` | 只增加弃用警告，保留了本应移除的自动NdarrayMixin转换；补丁语义不满足测试 |
| django__django-11964 | 751 / 49 / 94 | `ChoicesTests.test_str`、`test_textchoices` | 在Model初始化转换枚举值，没有修复Choices字符串语义 |
| django__django-13406 | 976 / 60 / 117 | `test_annotation_values_list`、`test_annotation_with_callable_default` | 过度保留values_list迭代类型，违反query反序列化后的预期语义 |
| django__django-14404 | 32 / 6 / 6 | 两项带SCRIPT_NAME的补斜杠测试 | 用request.path替代path_info，使URL解析带上部署前缀 |
| django__django-14771 | 189 / 25 / 31 | `TestChildArguments.test_xoptions` | 传递-X选项时只保留键，丢失选项值 |
| django__django-15973 | 441 / 47 / 64 | `test_create_with_through_model_separate_apps` | 在schema层加hasattr绕过症状，没有修复跨应用迁移依赖 |
| psf__requests-2931 | 144 / 18 / 23 | PASS_TO_PASS：`test_params_bytes_are_encoded` | 修改bytes处理后，原有URL参数行为回归 |
| pytest-dev__pytest-5787 | 402 / 42 / 60 | PASS_TO_PASS：`test_deserialization_failure` | 新增chain反序列化路径绕过旧reprentries校验，未知类型应抛RuntimeError却未抛；不是测试没跑 |
| sphinx-doc__sphinx-9711 | 79 / 15 / 15 | `test_needs_extensions` | 合法版本比较不进入条件分支时，not_new_enough未赋值即使用 |
| sympy__sympy-17139 | 77 / 15 / 15 | `test__TR56` | 未提前返回复数指数，`sin(x)**I`进入perfect_power并报“I is not an integer”；另一个目标测试test_issue_17137已通过 |
| sympy__sympy-18211 | 779 / 49 / 94 | `test_issue_18188` | 过早对等式直接调用solveset，没有保留要求的ConditionSet／原定义域语义 |

#### 0.9.3 pytest5787：明确纠正此前的“未收集测试”解释

该题最终日志的外层会话明确是 **collected 127 items；1 failed, 124 passed, 2 skipped**。失败为 `testing/test_reports.py::TestReportSerialization::test_deserialization_failure`：向反序列化数据注入未知entry type后，测试期望抛RuntimeError，新补丁未抛。FAIL_TO_PASS目标已通过，但这项PASS_TO_PASS回归使最终resolved=false，判未通过有实际依据。

官方SWE-bench 5.0.1的 `harness/infra_failure.py:59` 用 `no tests ran|collected 0 items` 在整份日志中搜索；pytest自身测试会启动嵌套会话，其捕获输出中确实含 `collected 0 items / 1 errors`。`harness/reporting.py:100` 再把该启发式标签加到未通过题，因此误把内部会话文本当作整题测试收集情况。使用已安装分类函数对真实日志和最小嵌套日志样例均复现该误报。

**这是第三方评测器的辅助分类缺陷，加上我们此前报告直接信任标签导致的解释错误；不是IS采样错误，也不是将本应通过的补丁错判失败。** 本次只纠正文档，不修改site-packages或官方JSON；69/100不变。10356不在本次十一题回退审计范围，不能仅凭5787的发现就断言它也属于同一种误报。

#### 0.9.4 仍需保留的机制风险与结论边界

1. **合法零thinking与非空thinking混合时，零thinking候选仍被排除。** 545个选择步中25步（涉及9题）出现这种混合情况；v3按既定最小修复策略只在没有任何可评分候选时均匀选择空thinking。它与当前约定一致，不是这次发现的编码差错，但不是中性的分布处理，可能影响解题路径；尚无控制实验能把某道回退归因于它。
2. **Conditional IS是按权重抽样，不是argmax。** 545步中213步选中的候选权重低于该步最高权重；种子及选择索引重放全部一致，这是预定抽样语义，不是“代码选错候选”。若改为最高奖励选择，就改变了方法，不能当作无影响修复。
3. **奖励不验证补丁正确性。** 347轮中248轮已选thinking≤100 tokens；Consilience只评价thinking置信度轨迹，正文普通生成，也没有候选级执行官方测试。即使完全按代码设计运行，仍可能选择错误修复方向或生成有回归的代码，不能因为最终补丁错误就反推采样实现必然有bug。
4. **离线一致不等于证明整个方法无缺陷。** 本次以归档模型响应为输入，未重新请求vLLM、未重建其内部logits、未重新执行全部任务容器；验证的是记录可审计的拼接、评分、选择、动作及送评链路。不能排除未覆盖输入下的实现问题，也不能量化奖励是否真正提高正确率。
5. **建议下一步先做受控机制验证，而不是盲目再跑11题。** 若用户确认，可统一agent、预算及completions/token-prefix通路做普通生成对照，再单独比较奖励选择；混合零thinking策略如需改动应新建协议并做小样本、多种子验证。本次没有自动开始这些实验。

## 1. 历史原始v2：结论摘要

1. **历史baseline通过70/100，Thinking IS通过62/100，绝对下降8个百分点。** 二者都通过55题；IS救回7题，同时回退15题；都未通过23题。
2. **7题救回不全是纯IS收益。** 5题原baseline有补丁但测试失败，本次IS改出了通过补丁；2题原baseline因动作格式／响应重建流程失败，本次恢复。其中后者之一 `scikit-learn__scikit-learn-14894` 已在补充baseline重跑中通过，不能称为IS独有能力。
3. **15题回退分成6题流程终止、9题补丁错误。** 6题四个候选均直接进入动作正文，thinking长度为0，被Consilience评分接口拒绝，最终整题终止、提交空补丁。其余9题有非空补丁，官方必需测试失败，不能归入该流程缺陷。
4. **额外计算没有带来整体收益。** IS的runner累计时间34.05小时，对照6.10小时，约5.58倍；API请求10.69倍、累计输入tokens 12.14倍、累计输出tokens 6.49倍。工具调用反而是0.91倍，接入主轨迹的输出是0.95倍：成本主要增加在候选／rollout，而非更多实际工具探索。
5. **主要问题不是L或上下文太小。** IS没有整题超时／上下文耗尽／主轨迹L耗尽终止；已接入主轨迹最多22,135 tokens，单轮已选回答最多1,722 tokens。失败包含实现缺陷、错误修复位置、遗漏边界条件和验证不足，不应通过继续扩大token上限笼统处理。
6. 本轮原始62%必须保留。只假设6道回退空补丁全部修复并通过，成绩也仅68%；另外3道原baseline也失败的空thinking终止题若同时全部通过，才会达到71%。**这两个数字都是算术情景，不是已测结果，也不是修复成功率预测。**

## 2. 历史原始v2：样本、来源与统计口径

### 2.1 固定样本与结果来源

- 数据集：`SWE-bench/SWE-bench_Verified`，`test`，固定revision `78f471bf655a3137b2e8a75af1501690ec009ec3`。从Verified固定的随机100题名单出发，不是全500题，也未重新抽样。
- 名单：`configs/qwen38_swebench_random100_instances.txt`。所有100题始终进入分母；空补丁、流程失败及歧义判题均不剔除。
- 历史baseline：原百题保留89题，固定11题兼容性补跑**全部替换**对应记录，不按结果择优；通过数63→70。补跑名单为 `configs/qwen38_swebench_reasoning_rerun11_instances.txt`。
- Thinking IS：已完成的baseline失败30题＋剩余70题，名单互斥、并集严格等于固定100题。旧限时pilot20、边界补跑、单题smoke均不混入。
- 单题以官方报告的 `resolved` 计分，不以 `Submitted`、`status=completed` 或测试进度条的“ran successfully”计分。`completed`仅表示runner生成了终态记录，不能排除流程终止。
- 两套IS服务的runtime指纹在30题与70题间一致；两次源码快照中的 `thinking_is.py` SHA-256均为 `8250a770365c943529418f343d856634006b99ea8ecb3d3d333049fff508fbf1`。70题新增了双文件系统磁盘保护，没有改变采样实现。

本文使用以下来源缩写，后文相对路径均从项目根目录解析：

| 缩写 | 结果根目录 | 本报告取值 |
| --- | --- | --- |
| B0 | `results/swebench/qwen38-verified-random100-baseline-20260917` | 非补跑名单的89题 |
| B11 | `results/swebench/qwen38-reasoning-compat-rerun11-20260918` | 补跑名单全部11题 |
| I30 | `results/swebench/qwen38-thinking-is-failed30-unlimited-dual` | 30题，2＋5通过 |
| I70 | `results/swebench/qwen38-thinking-is-remaining70-unlimited-dual` | 70题，30＋25通过 |
| B2 | `results/swebench/qwen38-baseline-unlimited-rerun2-20260919` | 仅补充分析，不替换主对照 |

I70的项目目录是数据盘软链接，实际位于 `/data/users/jenkins/inference_scaling-results/qwen38-thinking-is-remaining70-unlimited-dual/`。

### 2.2 参数与重要差异

| 项目 | 历史baseline | Thinking IS |
| --- | --- | --- |
| 本地模型服务名 | `qwen3.8-27b` | 相同 |
| Agent | mini-swe-agent 2.4.6，commit `25941c89cfbc91eb40b3f8756348c91d9977d57e` | 相同 |
| Agent配置／动作格式 | `swebench_xml.yaml`／text XML shell动作 | 相同 |
| Python / SWE-bench harness | 本次归档环境Python 3.11.15 / SWE-bench 5.0.1 | 相同版本环境 |
| 种子标签 | 20260916 | 20260916；算法内部种子派生及请求次数不同，不是逐请求相同随机数 |
| temperature / top_p | 1.0 / 1.0 | 1.0 / 1.0 |
| 整题主轨迹输出L | 131,072 | 131,072 |
| 每次调用上下文／安全余量 | 133,120 / 256 | 相同 |
| 单次正常完整回答上限 | 受剩余L与剩余上下文共同约束，配置chunk=131,072 | 正文普通生成；同样受剩余预算约束 |
| Thinking策略 | 普通生成 | Conditional IS＋Consilience |
| IS chunk / M / K_rollout | 不适用 | 100 / 4 / 2 |
| 正文策略 | 普通生成 | 普通生成，没有正文IS或logprob奖励 |
| Consilience配置 | 不适用 | top_k=5、skip_fraction=0.05、window_fraction=0.2、initial_penalty=3、scale=1；奖励温度2 |
| 候选选择 | 不适用 | 按rollout奖励得到权重后随机选择，不是永远取最大分候选 |
| 整题agent墙钟上限 | 1,800秒 | 0，禁用 |
| budget.max_wall_seconds | 7,200秒；agent的1,800秒先约束 | 0，禁用 |
| 单API请求超时／重试 | 1,800秒 / 0 | 相同 |
| 最大API请求数／题 | 250 | 50,000 |
| 最大agent步／工具调用 | 250 / 250 | 相同 |
| 连续动作格式错误退出 | 1次 | 3次 |
| guarded-v2／普通生成fallback | 不适用 | 未启用；空thinking问题没有兜底 |
| 运行并行度 | 单服务串行 | 两服务并行，每服务单题串行；归档的Thinking IS候选与rollout循环为串行 |

服务配置：两套独立TP=4服务，分别使用GPU4–7／端口8000和GPU0–3／端口8001，V100、FP16；`max_model_len=133120`、`max_num_seqs=8`、`max_num_batched_tokens=8192`、prefix caching开启、processed top-5 logprobs。`max_num_seqs=8`是服务容量参数，不等于客户端将4个候选同时提交；8192是调度批次token参数，不是单题L或单次回答上限。

**可比性限制：** baseline混合修复前后两批代码，且保留旧格式纠错和30分钟上限；IS采用更新的兼容处理、更高请求预算和不限时。共享CPU／磁盘、服务缓存和运行日期也不同。因此“62%对70%”是这套工程流程的实际结果，不能单独估计Consilience或IS算法的纯因果效应。模型服务名仅为本地部署标识，本报告不声称复现官方排行榜参数。

## 3. 历史原始v2：通过率、失败构成与配对结果

| 指标 | 历史baseline | Thinking IS |
| --- | --- | --- |
| 固定样本 | 100 | 100 |
| 官方通过 | 70（70.00%） | 62（62.00%） |
| 非空正式补丁 | 96 | 91 |
| 非空补丁但未通过 | 26（含1歧义判题） | 29（含1歧义判题） |
| 无正式补丁 | 4 | 9 |
| 动作格式错误终止 | 3 | 0 |
| 响应适配／运行异常终止 | 1 | 0 |
| 无有效thinking rollout终止 | 不适用 | 9（均为空thinking） |
| 整题超时／上下文／主轨迹L上限终止 | 0 / 0 / 0 | 0 / 0 / 0 |
| 官方evaluator错误 | 0 | 0 |
| 官方歧义判题 | 1（no_tests_collected） | 1（同题） |

| 配对结果 | 题数 | 含义 |
| --- | ---: | --- |
| 两者均通过 | 55 | IS保留原成功 |
| baseline失败、IS通过 | 7 | 救回，含流程恢复 |
| baseline通过、IS失败 | 15 | 回退，6流程＋9补丁 |
| 两者均失败 | 23 | 本轮未解决 |
| 合计 | 100 | 每题仅计一次 |

- 原成功保留率：55/70＝78.57%；原成功回退率：15/70＝21.43%。
- 原失败救回率：7/30＝23.33%；净变化：7−15＝−8题／−8个百分点，相对历史通过率下降11.43%。
- 非空补丁条件通过率：baseline 70/96＝72.92%，IS 62/91＝68.13%。这些条件比例排除了流程退出，不能替代百题主指标。
- IS全100题有9道 `no_valid_thinking_rollout`：6道回退＋3道双方失败；均已从最后一轮候选审计确认为空thinking触发，不是API超时或上下文不足。
- IS其余29道非空未通过中，28道有实际测试失败证据；`pytest-dev__pytest-10356` 为 `no_tests_collected` 歧义判题，仍按未通过计分，不直接归咎补丁质量。baseline的26道非空未通过中也包含同一歧义题。
- 本报告不将单个固定样本／单种子结果外推为整个Verified的模型准确率，也不作统计显著提升宣称。

### 3.1 分项目结果

| 项目 | 题数 | Baseline通过 | IS通过 | 救回 | 回退 |
| --- | --- | --- | --- | --- | --- |
| astropy | 7 | 6 | 5 | 0 | 1 |
| django | 46 | 31 | 30 | 4 | 5 |
| matplotlib | 10 | 7 | 5 | 0 | 2 |
| pallets | 1 | 1 | 0 | 0 | 1 |
| psf | 1 | 1 | 0 | 0 | 1 |
| pydata | 3 | 1 | 2 | 1 | 0 |
| pytest-dev | 3 | 2 | 1 | 0 | 1 |
| scikit-learn | 4 | 3 | 4 | 1 | 0 |
| sphinx-doc | 11 | 9 | 9 | 1 | 1 |
| sympy | 14 | 9 | 6 | 0 | 3 |

项目样本数不均，个别项目只有1–2题；此表用于定位回退，不用于得出项目难度或模型领域能力的稳健排序。

## 4. 历史原始v2：时间、调用与计算开销

### 4.1 指标定义

- **Agent秒数**：`diagnostics.limits.agent_seconds`，包括模型请求、IS采样选择、工具执行与agent循环；不含容器初始化／最终清理。
- **Runner秒数**：`usage.elapsed_seconds`，包含该题环境准备、agent和清理，不包含官方判题及题目前的磁盘等待。本报告逐题表统一使用runner分钟。
- **批次墙钟**：监督进程开始到最终汇总，包括双服务重叠、预检、判题、汇总与磁盘暂停。不能与所有题runner累计时间混为一谈。
- **API／工具秒数**：归档账本内各请求／工具调用累计计时，不是纯GPU kernel时间。预检、tokenize/detokenize等未进入completion账本的开销不能按模型请求计数替代。
- **累计输入tokens**：每次模型请求输入长度之和，重复包含历史和候选前缀，不是去重文本量，也不是排除prefix cache后的实际prefill计算。
- **累计输出tokens**：账本记录的全部模型生成，包括未选候选、rollout和普通正文；与接入agent历史的主轨迹输出不同。旧baseline被拒绝响应未必有完整内容可回补，统计只使用已归档账本。
- **P90/P95**：除中位数外采用nearest-rank分位数（升序第ceil(N×p)项）。时间按100个题等权，包含成功与失败；每题峰值的分位数和“全部调用混合”的分位数分开说明。

| 指标 | Baseline | Thinking IS |
| --- | --- | --- |
| Agent平均／分钟 | 3.65 | 20.42 |
| Agent中位／分钟 | 2.54 | 8.93 |
| Agent P90／分钟 | 7.43 | 60.53 |
| Agent P95／分钟 | 11.11 | 88.41 |
| Agent最长／分钟 | 23.49 | 120.48 |
| Runner平均／分钟 | 3.66 | 20.43 |
| Runner中位／分钟 | 2.55 | 8.94 |
| Runner P95／分钟 | 11.12 | 88.43 |
| Runner累计／小时 | 6.10 | 34.05 |
| Agent超过30分钟／题 | 0 | 19 |

### 4.2 请求与tokens总账

| 指标 | Baseline | Thinking IS | IS / Baseline |
| --- | --- | --- | --- |
| 模型请求数 | 3,242 | 34,667 | 10.69倍 |
| 累计输入tokens | 44,007,454 | 534,157,985 | 12.14倍 |
| 累计输出tokens | 606,360 | 3,937,509 | 6.49倍 |
| 接入主轨迹输出tokens | 605,664 | 577,211 | 0.95倍 |
| 工具调用数 | 3,238 | 2,936 | 0.91倍 |
| API累计秒数 | 17,701.01 | 118,101.01 | 6.67倍 |
| 工具累计秒数 | 3,849.41 | 2,801.47 | 0.73倍 |

IS累计生成3,937,509 tokens，其中只有577,211 tokens接入主轨迹，约14.66%；其余约85.34%用于候选／rollout等未接入主轨迹的生成。这里不是说这些计算必然“无用”，而是说明成本没有转化成同比例增加的可执行历史。

额外runner成本为约27.95小时，最终通过题反而少8题；因此本轮没有正的“净增通过题单位成本”可以报告。若只看7道救回，会遗漏15道回退及双方失败样本的成本。

| 配对分组 | 题数 | Baseline累计runner小时 | IS累计runner小时 |
| --- | --- | --- | --- |
| 两者均过 | 55 | 2.65 | 15.83 |
| 救回 | 7 | 0.56 | 5.77 |
| 回退 | 15 | 1.10 | 4.73 |
| 两者均失败 | 23 | 1.80 | 7.72 |

这些都是该机器和该服务配置下的观测值。未测量电费、云端费用、精确GPU-hours、FLOPs或缓存命中率，不能用API token倍率直接冒充硬件计算倍率。

### 4.3 执行时间线

- I30：2026-09-19 03:12:03开始，18:16:04完成；约15小时4分钟，包含约6小时5分钟的磁盘不足等待。两路各15题，分别通过2题和5题。
- I70：2026-09-19 22:35:09开始，2026-09-20 10:24:01完成；约11小时49分钟。A组08:18:52完成判题，30/35；B组10:22:05完成判题，25/35，随后完成汇总。
- 两批墙钟简单相加约26小时53分钟；两批中间另有空档，因此不能把它说成一次连续百题吞吐。逐题runner累计34.05小时，而不是26小时53分钟；这是不同口径。
- 两批均 `shard_a=0 shard_b=0 summary=0`，四个分片均 `generation=0 evaluation=0`；没有自动重试选择最佳成绩。
- 历史baseline百题按来源替换后的runner累计6.10小时是100条保留轨迹的成本，**不是**原百题＋补跑11题全部实验开销，也不是一次统一代码版本的真实整批墙钟。

## 5. 历史原始v2：输出长度、上下文与Thinking IS行为

### 5.1 主轨迹长度对照

以下“单轮”指**已经接入主轨迹的完整模型决定**，含thinking＋动作正文＋记账终止token；不包含被舍弃候选或rollout，也不包含被拒绝／尚未接入主轨迹的最后一次响应。每题先取峰值，再在100题上统计。不能拿这些峰值当作所有IS内部API调用的最大长度。

| 口径／tokens | 方法 | 均值 | 中位 | P90 | P95 | 最大 |
| --- | --- | --- | --- | --- | --- | --- |
| 每题累计主轨迹输出 | Baseline | 6,056.64 | 4,163.50 | 13,432 | 18,314 | 42,013 |
| 每题累计主轨迹输出 | IS | 5,772.11 | 4,076.00 | 11,991 | 19,016 | 22,135 |
| 每题单轮已选完整输出峰值 | Baseline | 613.81 | 472.50 | 1,174 | 1,562 | 2,152 |
| 每题单轮已选完整输出峰值 | IS | 573.03 | 464.50 | 1,063 | 1,301 | 1,722 |
| 每题单轮已选输入峰值 | Baseline | 16,562.27 | 13,749.00 | 30,400 | 37,729 | 68,780 |
| 每题单轮已选输入峰值 | IS | 15,652.84 | 13,345.00 | 29,858 | 38,435 | 56,546 |
| 每题单轮已选输入＋输出峰值 | Baseline | 16,648.10 | 13,845.50 | 30,564 | 37,798 | 68,835 |
| 每题单轮已选输入＋输出峰值 | IS | 15,752.44 | 13,433.00 | 29,959 | 38,499 | 56,864 |

每次调用的实际生成空间受 `min(剩余L, 133120 − 本轮输入 − 256)` 限制；chunk=100只约束候选短块，未给每次rollout设置额外的小上限。工具输出进入下一轮输入，历史又被重复发送，所以“最大本轮输入＋输出”大于“整题累计模型输出”完全可能。

本轮IS主轨迹累计最高22,135，仅占L的16.89%；主轨迹单轮输入＋输出峰值56,864，占133,120的42.72%。这些观测不能证明把L／上下文降至对应峰值就不会影响重新采样，因为rollout和未选分支也受预算约束；但它们说明本轮已记录终止并非主轨迹碰到了这两道硬上限。

### 5.2 已选thinking与权重行为

| 指标 | IS实测 |
| --- | --- |
| 尝试轮次／形成决定的轮次 | 2,948 / 2,939 |
| 每轮已选thinking平均／中位tokens | 96.14 / 47 |
| 每轮已选thinking P95／最大tokens | 368 / 1,680 |
| 每题thinking峰值P95 | 973 |
| 已选thinking≤100 tokens的轮次 | 2,180/2,939（74.17%） |
| 完成的候选选择步数 | 4,707 |
| 选择步ESS平均／中位 | 2.793 / 2.972 |
| 已选thinking tokens总和 | 282,552 |

thinking长度按 `thinking_is.rounds[].thinking_tokens`，即动作XML标记之前、可由该采样器评分的token前缀定义，不是另一个未记录的隐式推理通道。2939个已形成决定的轮次有长度记录；另9个零thinking失败轮次尚未形成决定，故未混入这2939个长度样本，但保留在2948次尝试及百题失败分母中。

约74.17%的已选thinking不超过100 tokens。**chunk=100不意味着每轮平均4块**；本轮完成4707次候选选择，平均每个已形成决定的轮次约1.60次选择。ESS均值约2.79（M=4，越接近4表示权重越平均），说明不少选择没有高度集中到单一候选；ESS不能作为补丁正确率或奖励有效性的证明。

## 6. 历史原始v2：救回7题：逐题分析

| 题目 | Baseline分钟 | IS分钟 | 耗时倍率 | 解释 |
| --- | --- | --- | --- | --- |
| django__django-12273 | 8.32 | 106.97 | 12.85 | 主键同步修复 |
| django__django-13315 | 2.57 | 15.82 | 6.16 | 表单查询去重 |
| django__django-15098 | 2.48 | 51.32 | 20.71 | 旧格式失败恢复；新baseline仍失败 |
| django__django-16938 | 3.37 | 39.64 | 11.77 | 序列化查询修复 |
| pydata__xarray-6599 | 8.22 | 53.30 | 6.49 | 日期／时差转换修复 |
| scikit-learn__scikit-learn-14894 | 0.97 | 2.39 | 2.46 | 旧重建失败恢复；新baseline也通过 |
| sphinx-doc__sphinx-10614 | 7.44 | 76.91 | 10.33 | SVG引用修复 |

### 6.1 django__django-12273：修复多表继承主键同步，原补丁改错阶段

原baseline只在 `_save_parents()` 的主键恢复条件上加 `self._state.adding`，仍未通过“pk设None后新建对象”的单继承／多继承测试。IS改为在 `_set_pk_val()` 中同步非自身主键的parent link目标字段，从赋值阶段解决父表旧主键残留。官方两项原失败测试均通过。

这是**有补丁测试失败→正确补丁**的恢复，不是空补丁流程恢复；但IS约107分钟，baseline约8分钟，且本次成功发生在30分钟之后，不能将全部收益归给奖励而忽略预算差异。

### 6.2 django__django-13315：修到了实际表单查询链

原baseline在普通字段 `get_choices()` 的查询上加 `.distinct()`，未覆盖 `limit_choices_to` 对表单字段queryset的路径，`test_limit_choices_to_no_duplicates` 仍失败。IS在 `django/forms/models.py` 的 `apply_limit_choices_to_to_formfield()` 中对 `complex_filter()` 的结果去重，官方通过。此题体现正确定位到实际调用路径，而不是笼统增加代码量。

### 6.3 django__django-16938：保留序列化只读主键优化，同时清除select_related

原baseline遇到 `select_related` 时绕开 `.only("pk")`，解决一部分冲突却破坏了序列化只读主键及自然键相关行为，JSON/YAML/JSONL/XML测试均有失败。IS在Python和XML serializer中改为 `.select_related(None).only("pk").iterator()`，保留只读主键策略并清除关系联查，官方通过。

### 6.4 pydata__xarray-6599：区分datetime与timedelta的数值转换

原baseline尝试从坐标索引选择数据并调整offset，`polyval` 的timedelta场景仍失败，且有PASS_TO_PASS回归。IS对datetime使用最小时间偏移，对timedelta直接按纳秒单位转换，官方通过。这里可以确认最终提交在该实例的测试集上修复了失败，不能据此证明所有未覆盖datetime边界都正确。

### 6.5 sphinx-doc__sphinx-10614：修复继承图SVG引用路径／键映射

原baseline同时修改graphviz的路径计算和继承图引用转换，官方的SVG继承图测试仍失败。IS将修改集中在 `inheritance_diagram.py`：处理当前文件basename、保留refuri，并调整外部intersphinx引用的键映射，官方通过。属于实际补丁改善，耗时约77分钟；仍需注意单题测试覆盖范围及预算差异。

### 6.6 django__django-15098：历史流程恢复，补充baseline仍未通过

原baseline因动作格式错误终止，没有正式补丁。IS提交了语言代码匹配与大小写处理修复，官方通过，耗时约51分钟。随后采用更新纠错策略且取消整题时限的baseline单次补跑，正常提交但仍有两项测试失败，耗时约9.13分钟。因此这道题目前存在“新baseline失败、IS通过”的补充证据，但只有一次样本且成本相差约5.62倍，仍不是严格等预算、多种子结论。

### 6.7 scikit-learn__scikit-learn-14894：不能算IS独有收益

原baseline因为 `sampled logprob tokens do not reconstruct response content` 被中断，没有正式补丁。IS补充了零support-vector时稀疏矩阵索引构造分支，通过官方测试。**补充baseline在同样取消时限、更新流程后也通过**：约1.65分钟，对比IS约2.39分钟。它在历史配对表中仍属于救回，但应解释为历史流程失败恢复，而不是IS算法必须提供的能力。

### 6.8 对救回的归因边界

- 原有有效补丁但测试失败的5题：12273、13315、16938、xarray6599、sphinx10614，均观察到更合适的修复路径。
- 原流程失败的2题：15098、sklearn14894。补充baseline结果1/2仅用于解释，不替换历史70/100；尤其不能挑选性地将成功补跑并入主baseline后又保留其旧失败成本。
- 7题中5题本次IS耗时超过30分钟。若对这些**已观测轨迹**施加30分钟硬截止，它们来不及按该路径提交；这不是一次新的限时配置评测结果。
- 历史baseline这100题没有因30分钟硬上限被截断；“取消时限有助IS走完更长路径”不等于“baseline原失败都是超时”。

## 7. 历史原始v2：回退15题：逐题分析

| 题目 | Baseline分钟 | IS分钟 | 失败类别／直接原因 |
| --- | --- | --- | --- |
| astropy__astropy-13236 | 1.09 | 4.40 | 只加警告，未移除转换 |
| django__django-11964 | 2.53 | 35.49 | 枚举str未修复 |
| django__django-13406 | 6.21 | 63.93 | query恢复返回类型错误 |
| django__django-14404 | 3.96 | 0.71 | 带前缀URL解析错误 |
| django__django-14771 | 2.19 | 6.20 | 遗漏-X选项值 |
| django__django-15973 | 2.69 | 18.89 | 迁移依赖未修复 |
| matplotlib__matplotlib-20826 | 17.61 | 88.43 | 流程：空thinking终止，空补丁 |
| matplotlib__matplotlib-25960 | 7.83 | 0.70 | 流程：空thinking终止，空补丁 |
| pallets__flask-5014 | 1.01 | 0.37 | 流程：空thinking终止，空补丁 |
| psf__requests-2931 | 2.99 | 4.79 | bytes URL参数回归 |
| pytest-dev__pytest-5787 | 7.00 | 1.69 | 流程：空thinking终止，空补丁 |
| sphinx-doc__sphinx-9711 | 2.43 | 2.31 | 未初始化变量 |
| sympy__sympy-17139 | 0.82 | 1.57 | 流程：空thinking终止，空补丁 |
| sympy__sympy-18211 | 2.41 | 52.63 | ConditionSet语义不符 |
| sympy__sympy-23413 | 5.10 | 1.39 | 流程：空thinking终止，空补丁 |

### 7.1 六题共享的流程缺陷：零thinking被误当整题失败

已逐题核对最后一轮：4个候选的token前缀完全相同，均为 `<mswea_bash_command>` 对应的8个tokens；`terminal_thinking=true`、`prefix_tokens=0`、两个reward均为null、没有rollout请求。不是“生成了8条错误解法”，而是候选已经抵达正文边界，没有可评分thinking。

当前 `_quality()` 在 `boundary[0]==0` 时返回None；`reward_weights()` 在全部None时抛出 `no_valid_thinking_rollout`；外层将该异常变成整题结束，`_append_limit_exit()` 写入空submission。因而即使此前工作区已有修改，也不会作为正式补丁进入判题。

| 原baseline通过、IS空补丁题 | 触发轮次 | 该轮输入tokens | 已执行工具数 | IS分钟 |
| --- | --- | --- | --- | --- |
| matplotlib__matplotlib-20826 | 88 | 56987 | 87 | 88.43 |
| matplotlib__matplotlib-25960 | 6 | 5389 | 5 | 0.70 |
| pallets__flask-5014 | 5 | 2727 | 4 | 0.37 |
| pytest-dev__pytest-5787 | 7 | 6872 | 6 | 1.69 |
| sympy__sympy-17139 | 12 | 4874 | 11 | 1.57 |
| sympy__sympy-23413 | 10 | 7349 | 9 | 1.39 |

matplotlib-20826在第88轮、耗时约88分钟后触发，说明问题不仅存在于“短题刚开始”，也会吞掉长时间探索后的结果。SymPy-17139已经改代码、做复现，但pytest调用因环境缺少pytest而未真正跑通；不能将已有修改当作确定正确。其余题也只能断言流程被提前截断，不能预先给分。

另外，双方均失败的 `django__django-12325`、`matplotlib__matplotlib-24637`、`sympy__sympy-22456` 也触发完全相同的空thinking分支。因此该缺陷覆盖本轮9/100，而不是只有A组最先发现的3题。

代码依据：`src/inference_scaling/swebench/thinking_is.py` 的 `_quality()`、`reward_weights()` 和 `_select_step()`；`src/inference_scaling/swebench/baseline.py` 的 `SamplingStopped` 处理；`src/inference_scaling/swebench/miniagent.py` 的 `_append_limit_exit()`。这里不建议把所有无效奖励一概改成0：应单独定义合法零thinking状态，保留对损坏响应、无法完成边界和缺失logprobs的严格拒绝。

### 7.2 astropy__astropy-13236：保留了本应移除的自动转换

Baseline直接移除structured ndarray自动转 `NdarrayMixin` 的分支。IS仍保留转换，只额外发出弃用警告。官方 `test_ndarray_mixin[False]` 和 `test_structured_masked_column` 未通过，日志包括新增的 `AstropyDeprecationWarning` 被当作错误。属于修复目标／行为选择错误，不是增加预算能自动解决的截断问题。

### 7.3 django__django-11964：修改Model构造而没有修复枚举自身的字符串表示

Baseline在Choices枚举上实现 `__str__()` 返回 `str(self.value)`。IS却在Model初始化中把enum转换为value，并额外改ChoicesMeta参数处理。这样即使某些模型实例字段看起来正常，直接对枚举调用str的语义仍不正确。官方 `test_str`、`test_textchoices` 失败。IS运行约35分钟、49次工具调用，不能把它简单归因于“完全没测试”；更准确的是实现目标偏移、验证未保证官方要求的枚举行为。

### 7.4 django__django-13406：过度保存values_list的迭代类型，违反query恢复契约

Baseline在赋回含 `values_select` 的query时将默认ModelIterable转换为ValuesIterable。IS把 `_iterable_class`、`_fields` 存进query并在恢复时原样带回，因此原values_list恢复后仍返回tuple／标量／Row，而官方期望dictionary，如 `('test',) != {'name': 'test'}`。官方报告列出 `test_annotation_values_list`、`test_annotation_with_callable_default` 未通过；明确堆栈展示了前者的三种返回类型错误。IS约64分钟、60次工具调用，说明更长探索也可能走向错误契约。

### 7.5 django__django-14404：把部署前缀带进URL解析

Baseline保留 `request.path_info` 供resolve使用，只在最终重定向时用 `request.path + '/'`。IS将前面的解析路径也改为request.path，导致带SCRIPT_NAME／FORCE_SCRIPT_NAME的请求404，而测试期望301。两个相关FAIL_TO_PASS测试失败。IS仅6次工具调用、43秒提交，没有运行实际复现或测试，只查看源码与diff；属于错误定位叠加验证不足。

### 7.6 django__django-14771：只传递-X选项名，遗漏取值

IS对 `sys._xoptions` 只迭代key，生成 `-Xa`；官方测试要求保留value，生成 `-Xa=b`。Baseline遍历items并区分无值标记与key=value。`test_xoptions` 明确显示上述差异。属于遗漏参数化边界，不是平台未启动。

### 7.7 django__django-15973：在schema层绕过症状，未修迁移依赖

跨app many-to-many through模型需要正确迁移依赖。Baseline在autodetector中将错误的目标关系改成 `field.remote_field.through`。IS却在schema editor里加 `hasattr(..., '_meta')` 跳过部分处理，未修依赖生成。官方 `test_create_with_through_model_separate_apps` 期望authors生成2个migration，实际仍只有1个。属于改错层级、处理表面症状。

### 7.8 psf__requests-2931：修复二进制body但回归URL参数

IS让 `_encode_params()` 对bytes直接返回，解决了一条body路径，却没有在URL构造端把bytes参数转回文本。原本应通过的 `test_params_bytes_are_encoded` 发生 `TypeError: Cannot mix str and non-str arguments`，即PASS_TO_PASS回归。Baseline除保留body bytes外，还在prepare_url侧处理enc_params的bytes→native string。此题尤其说明只验证问题示例、不检查共享函数的其他调用方会损害已通过行为。

### 7.9 sphinx-doc__sphinx-9711：未初始化变量，替代代码验证掩盖缺陷

IS仅在版本不足时给 `not_new_enough=True`，版本相等或足够时未赋值，随后引用导致 `UnboundLocalError`；官方 `test_needs_extensions` 失败。轨迹显示实际模块导入因缺docutils／babel失败后，agent另写了一个直接return比较值的简化函数验证；该函数不是实际补丁，因此没覆盖未赋值分支。Baseline补丁没有该变量缺陷，并补齐依赖后调用实际函数做复现。这里既有补丁逻辑错误，也有验证对象错误。

### 7.10 sympy__sympy-18211：对所有等式提前调用solveset，未保留要求的ConditionSet语义

Baseline在原求解失败的异常路径构造 `ConditionSet(_gen, Eq(e,0), _domain)`，保留条件与原域。IS在前面增加 `Eq且not relational` 的提前返回，直接调用solveset并替换变量；部分示例可得到结果，但官方 `test_issue_18188` 对带sqrt和sin表达式的ConditionSet等价断言失败。IS约53分钟，做了多次复现和测试尝试；观察支持“边界语义未覆盖”，不支持把全部回退概括为“IS都没有验证”。

### 7.11 对回退机制的归纳

- **确定的工程缺陷**：空thinking已到正文仍终止全题，影响6道原成功题及3道原失败题，优先级最高。
- **语义定位偏差**：修错调用层、保留错误旧行为或过度重建内部类型，如Astropy、Django11964/13406/14404/15973。
- **边界与回归覆盖不足**：遗漏-X值、bytes URL参数、ConditionSet语义；Requests明确是PASS_TO_PASS回归。
- **验证纪律不足**：Django14404未实际测试，Sphinx9711测试了不等价替代函数；但其他回退题也存在较长验证过程，不能以单一原因覆盖9道补丁失败。
- Consilience在当前实现中只评价thinking的模型logprob轨迹，不执行官方测试，也不直接评价最终补丁。它没有阻止这些错误；不过没有同前缀候选正确性对照或多种子消融，不能断言每次失败都是它把正确候选筛掉了。

## 8. 历史原始v2：下一步建议：保留原始成绩，分层验证

1. **先冻结本报告与原始62/100。** 本轮原始baseline仍是70/100，不混入两题补充baseline或任何后续IS重试。修复后的实验应使用新标签、源码快照和独立官方报告。
2. **最小化修复零thinking状态处理。** 四候选均已直接到正文且没有thinking时，应定义明确的无thinking选择／普通正文续写策略，而非整题失败；混合空／非空候选如何赋权也需预先定义，不能临时按结果选择。增加单元测试覆盖全空、混合、EOS／边界token、真正损坏响应和剩余预算。
3. **先在9道已确认流程退出题上做单次诊断补跑。** 保留原seed与其他参数，逐题记录是否能正常提交及官方是否通过；不要把“恢复生成”当成“恢复正确”。这批是条件诊断，不能替代一次新协议的完整百题成绩。
4. **对真实补丁回退加强实际代码验证。** 明确解释器／测试环境，提交前运行实际被修改函数或聚焦测试；管道尾部exit 0不能代表前面测试成功。若改变agent提示或提交约束，应同时用于baseline和IS，不能只增强IS后与旧baseline做纯算法比较。
5. **建立同协议、等成本对照。** 统一格式容错、时间／token预算、依赖和代码版本；比较普通baseline、Thinking IS，以及相近成本的多次独立baseline／验证选择策略。当前5.58倍runner成本没有净收益，不建议未经验证就扩大M/K或L。
6. **奖励消融需要额外实验，不能从本轮直接推出。** 可比较普通thinking、均匀候选选择、Consilience选择，观察同前缀候选的实际错误率、验证行为与成本，判断权重是否有用；暂不启动正文IS以免把新的变量混入当前诊断。

磁盘提示：报告前的进度检查发现Docker所在根分区低于4GiB保护阈值；本次只读取结果、写文档，不删除旧数据或重启服务。后续实验需先确认可用空间，不能绕过保护线悄悄开始补跑。

## 9. 最新合并100题明细（91条v2＋9条v3）

此表已整体替换九题的新结果、时间与token账本，失败的两题也使用新记录；其余91题不变。单位：时间为runner分钟；tokens为全部模型请求累计输出，IS含候选／rollout，不是L。`B0/B11`为baseline来源；`I30/I70`为原始IS批次（此表分别保留27／64题）；`I9`为本次v3补跑批次（9题），后缀A/B为服务分片。来源根目录见第0.1节和历史第2节；I9分片run目录为 `I9/shard_a或shard_b/qwen38-thinking-is-c100-empty9-rerun-unlimited`。计算使用原始秒数，显示保留两位小数。

| 题目 | B／IS来源 | 配对 | B结果→IS结果 | B分钟 | IS分钟 | B／IS请求数 | B／IS累计输出tokens |
| --- | --- | --- | --- | --- | --- | --- | --- |
| astropy__astropy-12907 | B0 / I70A | 两者均过 | 通过 → 通过 | 2.87 | 4.88 | 31 / 124 | 5,038 / 9,260 |
| astropy__astropy-13236 | B0 / I70B | 回退 | 通过 → 未通过 | 1.09 | 4.40 | 18 / 149 | 1,973 / 8,338 |
| astropy__astropy-14365 | B0 / I30A | 两者均失败 | 未通过 → 未通过 | 1.76 | 3.39 | 21 / 117 | 3,147 / 6,207 |
| astropy__astropy-14508 | B0 / I70A | 两者均过 | 通过 → 通过 | 5.23 | 18.99 | 33 / 383 | 7,932 / 38,540 |
| astropy__astropy-14995 | B0 / I70B | 两者均过 | 通过 → 通过 | 1.77 | 4.65 | 21 / 129 | 2,478 / 7,955 |
| astropy__astropy-7671 | B0 / I70A | 两者均过 | 通过 → 通过 | 2.89 | 22.04 | 33 / 287 | 5,884 / 47,332 |
| astropy__astropy-8872 | B11 / I70B | 两者均过 | 通过 → 通过 | 1.43 | 5.36 | 17 / 152 | 2,529 / 10,007 |
| django__django-10554 | B0 / I30B | 两者均失败 | 未通过 → 未通过 | 23.50 | 117.76 | 100 / 1,178 | 42,013 / 230,825 |
| django__django-11099 | B0 / I70A | 两者均过 | 通过 → 通过 | 0.50 | 0.96 | 9 / 45 | 948 / 1,674 |
| django__django-11211 | B11 / I70B | 两者均过 | 通过 → 通过 | 1.94 | 14.16 | 28 / 288 | 3,022 / 26,123 |
| django__django-11477 | B0 / I30A | 两者均失败 | 未通过 → 未通过 | 2.11 | 18.66 | 31 / 358 | 2,999 / 36,649 |
| django__django-11532 | B0 / I30B | 两者均失败 | 未通过 → 未通过 | 2.30 | 2.20 | 27 / 75 | 4,475 / 4,028 |
| django__django-11603 | B0 / I70A | 两者均过 | 通过 → 通过 | 1.37 | 2.53 | 14 / 79 | 1,443 / 3,584 |
| django__django-11728 | B0 / I70B | 两者均过 | 通过 → 通过 | 4.07 | 27.65 | 29 / 458 | 5,747 / 55,526 |
| django__django-11848 | B0 / I30A | 两者均失败 | 未通过 → 未通过 | 1.20 | 24.14 | 18 / 432 | 2,350 / 48,880 |
| django__django-11951 | B0 / I70A | 两者均过 | 通过 → 通过 | 0.40 | 0.92 | 8 / 45 | 707 / 1,585 |
| django__django-11964 | B0 / I70B | 回退 | 通过 → 未通过 | 2.53 | 35.49 | 23 / 751 | 2,835 / 68,369 |
| django__django-12155 | B0 / I70A | 两者均过 | 通过 → 通过 | 2.41 | 1.11 | 18 / 41 | 1,594 / 2,081 |
| django__django-12273 | B11 / I30B | 救回 | 未通过 → 通过 | 8.32 | 106.97 | 51 / 1,441 | 14,127 / 207,328 |
| django__django-12325 | B0 / I9A | 救回 | 未通过 → 通过 | 4.04 | 8.34 | 39 / 243 | 6,396 / 15,264 |
| django__django-12419 | B0 / I70B | 两者均过 | 通过 → 通过 | 1.54 | 3.27 | 17 / 101 | 1,588 / 4,486 |
| django__django-13195 | B0 / I30B | 两者均失败 | 未通过 → 未通过 | 1.55 | 4.00 | 15 / 151 | 1,530 / 6,835 |
| django__django-13212 | B0 / I30A | 两者均失败 | 未通过 → 未通过 | 2.85 | 4.49 | 27 / 138 | 4,111 / 8,293 |
| django__django-13279 | B11 / I70A | 两者均过 | 通过 → 通过 | 2.96 | 4.61 | 30 / 149 | 5,277 / 6,872 |
| django__django-13315 | B0 / I30B | 救回 | 未通过 → 通过 | 2.57 | 15.82 | 20 / 398 | 3,459 / 28,167 |
| django__django-13346 | B11 / I70B | 两者均过 | 通过 → 通过 | 4.85 | 120.49 | 39 / 1,190 | 9,344 / 238,833 |
| django__django-13363 | B0 / I70A | 两者均过 | 通过 → 通过 | 1.24 | 1.08 | 11 / 41 | 1,205 / 1,957 |
| django__django-13406 | B0 / I70B | 回退 | 通过 → 未通过 | 6.21 | 63.93 | 49 / 976 | 8,942 / 128,138 |
| django__django-13569 | B0 / I70A | 两者均过 | 通过 → 通过 | 3.61 | 6.26 | 36 / 225 | 6,611 / 9,848 |
| django__django-13658 | B0 / I70B | 两者均过 | 通过 → 通过 | 0.36 | 1.16 | 7 / 45 | 685 / 1,981 |
| django__django-13810 | B0 / I70A | 两者均过 | 通过 → 通过 | 2.22 | 12.90 | 21 / 302 | 4,216 / 23,290 |
| django__django-13837 | B0 / I70B | 两者均过 | 通过 → 通过 | 4.55 | 23.61 | 30 / 330 | 5,822 / 46,803 |
| django__django-14017 | B0 / I70A | 两者均过 | 通过 → 通过 | 3.81 | 21.55 | 31 / 493 | 4,273 / 41,721 |
| django__django-14089 | B0 / I70B | 两者均过 | 通过 → 通过 | 0.39 | 0.71 | 7 / 35 | 636 / 1,107 |
| django__django-14315 | B0 / I30A | 两者均失败 | 未通过 → 未通过 | 0.57 | 1.84 | 9 / 61 | 1,087 / 3,425 |
| django__django-14404 | B0 / I70A | 回退 | 通过 → 未通过 | 3.96 | 0.71 | 36 / 32 | 6,726 / 1,253 |
| django__django-14493 | B0 / I70B | 两者均过 | 通过 → 通过 | 3.61 | 1.14 | 32 / 45 | 6,112 / 1,879 |
| django__django-14534 | B0 / I30B | 两者均失败 | 未通过 → 未通过 | 2.86 | 1.80 | 45 / 67 | 4,397 / 3,020 |
| django__django-14580 | B0 / I70A | 两者均过 | 通过 → 通过 | 1.45 | 5.54 | 23 / 194 | 2,538 / 8,927 |
| django__django-14771 | B0 / I70B | 回退 | 通过 → 未通过 | 2.19 | 6.20 | 35 / 189 | 3,454 / 10,826 |
| django__django-15098 | B0 / I30A | 救回 | 格式失败 → 通过 | 2.48 | 51.32 | 25 / 985 | 4,819 / 98,354 |
| django__django-15380 | B0 / I70A | 两者均过 | 通过 → 通过 | 1.37 | 8.81 | 18 / 257 | 2,219 / 16,490 |
| django__django-15382 | B0 / I70B | 两者均过 | 通过 → 通过 | 10.87 | 24.15 | 77 / 498 | 13,822 / 46,071 |
| django__django-15525 | B11 / I30B | 两者均失败 | 格式失败 → 未通过 | 3.77 | 23.12 | 35 / 428 | 7,084 / 45,310 |
| django__django-15554 | B11 / I70A | 两者均过 | 通过 → 通过 | 11.12 | 104.27 | 104 / 1,412 | 19,884 / 205,668 |
| django__django-15695 | B0 / I30A | 两者均失败 | 未通过 → 未通过 | 3.50 | 8.52 | 34 / 229 | 6,901 / 16,375 |
| django__django-15973 | B0 / I70B | 回退 | 通过 → 未通过 | 2.69 | 18.89 | 36 / 441 | 4,789 / 35,445 |
| django__django-16333 | B0 / I70A | 两者均过 | 通过 → 通过 | 0.45 | 2.19 | 7 / 77 | 601 / 3,793 |
| django__django-16662 | B0 / I70B | 两者均过 | 通过 → 通过 | 2.14 | 2.23 | 24 / 80 | 3,213 / 4,073 |
| django__django-16801 | B0 / I70A | 两者均过 | 通过 → 通过 | 1.19 | 6.59 | 15 / 190 | 2,125 / 10,338 |
| django__django-16938 | B0 / I30B | 救回 | 未通过 → 通过 | 3.37 | 39.64 | 32 / 704 | 6,506 / 76,667 |
| django__django-17087 | B0 / I70B | 两者均过 | 通过 → 通过 | 1.57 | 3.34 | 26 / 123 | 2,368 / 5,865 |
| django__django-9296 | B0 / I70A | 两者均过 | 通过 → 通过 | 0.55 | 1.72 | 8 / 75 | 817 / 3,009 |
| matplotlib__matplotlib-13989 | B0 / I70B | 两者均过 | 通过 → 通过 | 1.67 | 9.32 | 25 / 255 | 2,489 / 16,553 |
| matplotlib__matplotlib-20676 | B0 / I70A | 两者均过 | 通过 → 通过 | 2.68 | 14.81 | 30 / 319 | 4,509 / 29,889 |
| matplotlib__matplotlib-20826 | B0 / I9B | 两者均过 | 通过 → 通过 | 17.61 | 40.69 | 119 / 739 | 26,089 / 73,595 |
| matplotlib__matplotlib-23476 | B0 / I30A | 两者均失败 | 未通过 → 未通过 | 3.69 | 10.49 | 29 / 237 | 6,995 / 19,756 |
| matplotlib__matplotlib-24570 | B0 / I70A | 两者均过 | 通过 → 通过 | 1.95 | 64.97 | 21 / 486 | 3,331 / 137,883 |
| matplotlib__matplotlib-24637 | B0 / I9A | 救回 | 未通过 → 通过 | 4.58 | 19.58 | 41 / 445 | 7,489 / 37,497 |
| matplotlib__matplotlib-25332 | B0 / I70B | 两者均过 | 通过 → 通过 | 6.61 | 18.22 | 45 / 388 | 11,966 / 34,460 |
| matplotlib__matplotlib-25960 | B0 / I9B | 两者均过 | 通过 → 通过 | 7.83 | 189.74 | 44 / 1,801 | 13,432 / 364,861 |
| matplotlib__matplotlib-26291 | B0 / I70B | 两者均过 | 通过 → 通过 | 2.58 | 10.00 | 30 / 282 | 3,870 / 18,619 |
| matplotlib__matplotlib-26466 | B0 / I30A | 两者均失败 | 未通过 → 未通过 | 2.89 | 10.18 | 43 / 257 | 3,206 / 17,903 |
| pallets__flask-5014 | B0 / I9A | 两者均过 | 通过 → 通过 | 1.01 | 1.12 | 15 / 55 | 1,464 / 1,856 |
| psf__requests-2931 | B0 / I70B | 回退 | 通过 → 未通过 | 2.99 | 4.79 | 28 / 144 | 6,030 / 9,052 |
| pydata__xarray-6599 | B0 / I30B | 救回 | 未通过 → 通过 | 8.22 | 53.30 | 44 / 812 | 15,049 / 101,924 |
| pydata__xarray-6938 | B0 / I30A | 两者均失败 | 未通过 → 未通过 | 2.40 | 23.93 | 24 / 456 | 3,820 / 46,753 |
| pydata__xarray-7393 | B0 / I70A | 两者均过 | 通过 → 通过 | 2.17 | 3.89 | 28 / 128 | 3,152 / 6,077 |
| pytest-dev__pytest-10356 | B0 / I30B | 两者均失败 | 未通过 → 未通过（无测试收集） | 6.46 | 35.87 | 49 / 548 | 10,634 / 67,934 |
| pytest-dev__pytest-5787 | B0 / I9B | 回退 | 通过 → 未通过（兼容性回归，官方误标） | 7.00 | 19.32 | 58 / 402 | 12,165 / 34,059 |
| pytest-dev__pytest-7236 | B0 / I70A | 两者均过 | 通过 → 通过 | 2.45 | 13.54 | 24 / 312 | 4,098 / 25,853 |
| scikit-learn__scikit-learn-11310 | B0 / I70B | 两者均过 | 通过 → 通过 | 1.36 | 4.20 | 20 / 135 | 2,464 / 7,424 |
| scikit-learn__scikit-learn-14894 | B0 / I30A | 救回 | 适配失败 → 通过 | 0.97 | 2.39 | 9 / 79 | 1,835 / 4,344 |
| scikit-learn__scikit-learn-25102 | B0 / I70A | 两者均过 | 通过 → 通过 | 12.78 | 52.79 | 69 / 848 | 18,314 / 104,625 |
| scikit-learn__scikit-learn-25931 | B0 / I70B | 两者均过 | 通过 → 通过 | 3.23 | 7.22 | 25 / 177 | 5,957 / 12,900 |
| sphinx-doc__sphinx-10614 | B0 / I30B | 救回 | 未通过 → 通过 | 7.44 | 76.91 | 63 / 815 | 13,622 / 151,570 |
| sphinx-doc__sphinx-11445 | B0 / I70A | 两者均过 | 通过 → 通过 | 2.83 | 25.27 | 32 / 495 | 5,243 / 51,631 |
| sphinx-doc__sphinx-7454 | B0 / I70B | 两者均过 | 通过 → 通过 | 4.87 | 5.04 | 50 / 158 | 8,064 / 8,924 |
| sphinx-doc__sphinx-7889 | B0 / I70A | 两者均过 | 通过 → 通过 | 1.28 | 17.06 | 17 / 335 | 1,716 / 34,351 |
| sphinx-doc__sphinx-8548 | B11 / I30A | 两者均失败 | 未通过 → 未通过 | 16.37 | 94.24 | 123 / 1,216 | 28,371 / 182,567 |
| sphinx-doc__sphinx-8551 | B0 / I70B | 两者均过 | 通过 → 通过 | 2.04 | 75.93 | 34 / 1,354 | 3,677 / 136,499 |
| sphinx-doc__sphinx-8721 | B11 / I70A | 两者均过 | 通过 → 通过 | 3.80 | 21.92 | 37 / 506 | 7,216 / 38,442 |
| sphinx-doc__sphinx-9258 | B0 / I70B | 两者均过 | 通过 → 通过 | 4.22 | 9.08 | 50 / 330 | 6,946 / 15,076 |
| sphinx-doc__sphinx-9658 | B0 / I70A | 两者均过 | 通过 → 通过 | 4.51 | 60.54 | 42 / 644 | 7,996 / 127,650 |
| sphinx-doc__sphinx-9673 | B0 / I70B | 两者均过 | 通过 → 通过 | 1.87 | 18.14 | 24 / 377 | 3,020 / 34,222 |
| sphinx-doc__sphinx-9711 | B0 / I70A | 回退 | 通过 → 未通过 | 2.43 | 2.31 | 26 / 79 | 4,225 / 4,159 |
| sympy__sympy-13372 | B0 / I70B | 两者均过 | 通过 → 通过 | 1.26 | 2.30 | 17 / 72 | 2,048 / 3,506 |
| sympy__sympy-13615 | B0 / I70A | 两者均过 | 通过 → 通过 | 3.31 | 38.62 | 40 / 475 | 6,063 / 80,743 |
| sympy__sympy-14711 | B0 / I70B | 两者均过 | 通过 → 通过 | 1.35 | 2.14 | 23 / 80 | 2,228 / 3,191 |
| sympy__sympy-15976 | B0 / I30B | 两者均失败 | 未通过 → 未通过 | 3.95 | 14.66 | 30 / 326 | 7,566 / 27,475 |
| sympy__sympy-16597 | B0 / I30A | 两者均失败 | 未通过 → 未通过 | 2.30 | 19.02 | 26 / 348 | 3,528 / 38,287 |
| sympy__sympy-17139 | B0 / I9A | 回退 | 通过 → 未通过 | 0.82 | 2.15 | 12 / 77 | 1,280 / 3,166 |
| sympy__sympy-17318 | B0 / I30B | 两者均失败 | 未通过 → 未通过 | 2.05 | 9.52 | 23 / 241 | 3,446 / 16,811 |
| sympy__sympy-18211 | B0 / I70B | 回退 | 通过 → 未通过 | 2.41 | 52.63 | 25 / 779 | 3,282 / 95,260 |
| sympy__sympy-18763 | B0 / I30A | 两者均失败 | 未通过 → 未通过 | 1.27 | 4.89 | 18 / 144 | 2,168 / 9,307 |
| sympy__sympy-20801 | B0 / I70A | 两者均过 | 通过 → 通过 | 3.86 | 10.61 | 45 / 292 | 5,789 / 20,266 |
| sympy__sympy-21847 | B0 / I70B | 两者均过 | 通过 → 通过 | 0.85 | 4.09 | 12 / 122 | 1,306 / 6,859 |
| sympy__sympy-22456 | B11 / I9B | 救回 | 格式失败 → 通过 | 12.09 | 127.20 | 69 / 1,215 | 23,456 / 240,226 |
| sympy__sympy-22914 | B0 / I70A | 两者均过 | 通过 → 通过 | 0.68 | 1.40 | 12 / 70 | 1,083 / 2,198 |
| sympy__sympy-23413 | B11 / I9A | 两者均过 | 通过 → 通过 | 5.10 | 222.84 | 42 / 1,571 | 9,865 / 459,642 |

## 10. 历史原始v2：证据定位与审计说明

### 10.1 原始文件查找规则

- Baseline单题：`B0或B11/base/seed-20260916/instances/<ID>/{record.json,trajectory.json}`。
- I30分片run目录：`I30/shard_a或shard_b/qwen38-thinking-is-c100-baseline-failed30-unlimited`。
- I70分片run目录：`I70/shard_a或shard_b/qwen38-thinking-is-c100-remaining70-unlimited`。
- IS单题：上述run目录下 `is_thinking-a1-b4-c100-r2/seed-20260916/instances/<ID>/{record.json,trajectory.json}`。
- 每个run的官方汇总：`evaluation/reports/<arm>/seed-20260916.json`；arm分别是 `base` 或 `is_thinking-a1-b4-c100-r2`。
- 官方逐题证据：run目录下 `evaluation/logs/run_evaluation/<run_id>/openai__qwen3.8-27b/<ID>/`，包含 `patch.diff`、`report.json`、`test_output.txt`。空补丁可能没有逐题执行目录，应查汇总报告的 `empty_patch_ids` 和生成记录，不能因无目录就漏计。
- IS两批另有 `assignment.json`、`inputs.sha256`、`source_snapshot.tar.gz`、`case_timings.csv`、`summary.json`、分片日志与 `pipeline_exit.txt`；汇总是aggregation-only，四个官方报告独立保留，没有伪造单一runtime来源。
- 补充baseline B2的两题记录和官方报告独立保留；本报告历史6.6、6.7引用该批结果，历史第3–5节、最新第0节及第9节均不使用B2替换值。

### 10.2 分析校验

本次统计逐题核验：固定名单100个唯一ID；baseline替换名单11题；IS两批无交集且完整覆盖；IS CSV的resolved与官方ID集合一致；manifest与assignment配置指纹一致；轨迹exit_status与CSV一致；22个差异题的官方报告和最终补丁分别对照；9个无有效rollout的最后一轮4候选均核对为空thinking；两次采样源码快照哈希一致。时间／token统计重新从记录、轨迹和官方报告计算，没有从进度聊天中的四舍五入数字反推。

源码版本与数据哈希如下，便于复核报告来源；这些哈希不意味着历史baseline与IS完全同协议：

| 文件 | SHA-256 |
| --- | --- |
| `configs/qwen38_swebench_random100_instances.txt` | `559abe0a8499a40f0c82837f1b9cdf79ccaead21cd21555878ef1b7c5e8461eb` |
| `configs/qwen38_swebench_reasoning_rerun11_instances.txt` | `015b74860277eb49df1229199821ee24fd8fc1e506a009cfef1e4eabdcb76364` |
| `configs/qwen38_swebench_baseline_failed30_instances.txt` | `dfef1ce4eb4ae07d5354842ce562600113146453615b0cd526326397ee21cf94` |
| `configs/qwen38_swebench_thinking_is_remaining70_instances.txt` | `93312b2c97360c498e8df1d91ae449edece45f454bdde877cf1bf4029a55823f` |
| `configs/qwen38_swebench_thinking_is_failed30_unlimited.toml` | `f63ed947ee596387d4f21e5ba0d0eb630e428977a4f437c60cdb8522e15ea36a` |
| `configs/qwen38_swebench_thinking_is_remaining70_unlimited.toml` | `ae3b0461241d9bcc981ef7556059002bb5c8601841080f372f0c839039269916` |
| `results/swebench/qwen38-thinking-is-failed30-unlimited-dual/summary.json` | `f5e39647cba98819e991dedd3cb838874630c994d6896805dc88548a9c2225cc` |
| `results/swebench/qwen38-thinking-is-remaining70-unlimited-dual/summary.json` | `be028fa942773b9b35bae2bbfaad83091cd7e658efe884994ce8cd2507488c22` |
| `results/swebench/qwen38-thinking-is-failed30-unlimited-dual/case_timings.csv` | `c0668dfa49fccebbb6d3e60df76ed8a50594febb337a15c13d0adabdd8d96589` |
| `results/swebench/qwen38-thinking-is-remaining70-unlimited-dual/case_timings.csv` | `d585dedc93e72739024f64cdabf5c213f32c7909c7d372e305d0864c2973039d` |

统计范围仅为本报告列明的100条baseline保留轨迹与100条IS轨迹。模型费用、所有被拒绝响应的未记录tokens、未选rollout的逐调用最大上下文、多种子方差、奖励选择的因果贡献，均未在本轮完整测量；不以推断数值替代实测。


## 11. Baseline 长度分布与预算参考（历史固定百题）

本节合并原 baseline 独立报告中的长度分析。统计样本仍为历史固定100题，不含正在运行的新一轮完整v3百题。
下文关于更小预算的建议只保留为历史静态分析，不代表已经更改本轮 L、上下文、chunk 或墙钟限制。

**先看量级：整题累计输出均值约 6,064 tokens、最大 42,013；单轮完整输出 P95 为 616、最大 2,152；
单轮 thinking 阶段输出 P95 为 412、最大 2,108；单轮实际输入上下文最大 68,780 tokens。**
这些是不同维度，不能把 6,064 当成单次回答长度，也不能把 412 当成单轮模型所需的全部上下文。

### 长度口径与覆盖范围

本节沿用主报告的固定合并样本：原百题 89 条 + 指定补跑 11 条，共 100 个不同题目；不是 111 次尝试混合统计。
数据来自所选 `record.json`、`trajectory.json` 中的真实 API usage、采样 token bytes 和逐请求预算记录，
不是按字符数换算 token，不调用模型、tokenizer 服务或执行题目代码。

| 指标 | 本节定义 | 对应的参数或用途 |
| --- | --- | --- |
| 整题累计输出 | 所有模型调用的 `completion_tokens` 之和，含 thinking、动作/命令文本和 EOS，也含失败调用的已记账输出 | 整题 `max_trajectory_output_tokens` / L 的预算参考；不是最终 patch 的长度 |
| 单轮完整输出 | 一次 API 调用的 `completion_tokens`，含 thinking + action + EOS | 单次 `max_tokens`；当前 baseline 的 `arms.chunk_tokens` 是单次上限，不是 IS 实际分块长度 |
| 单轮 thinking 阶段输出 | 完整生成起点到首个合法 `<mswea_bash_command>` opening marker 之前的 token，opening marker 不计入 | 按本实验 thinking/action 阶段定义统计，用于理解 thinking 长度；含 THOUGHT 说明、空白及已生成的 thinking marker，不等同于纯隐藏推理 |
| 单轮输入上下文 | API `prompt_tokens`，包括系统提示、题目、此前思考/命令、工具输出及模板开销 | 本轮思考所能看到的输入；工具输出不计入整题输出 L，但会推高此值 |
| 本轮输入＋输出 | 同一次调用的 `prompt_tokens + completion_tokens` | 模型上下文窗口需同时容纳两者；配置还需另留 256 tokens 安全余量 |

全部 100 题共 3,242 次调用，累计输出 606,360 tokens，与合并用量表核对一致：

- 保存原始响应 3,241 条，全部 `finish_reason=stop`，没有已保存的 `length` 响应。
- 缺少原始响应的 1 次为 `scikit-learn__scikit-learn-14894` 第 9 次调用；从该题总 usage 减前 8 次 usage
  得到输入 5,331、输出 647 tokens，并与失败请求的输入计数交叉核对。这次计入输入/输出统计，但不猜测 thinking 长度。
- 另 3 条动作格式错误响应没有合法 opening marker，thinking/action 无法按协议分段，因此不计入 thinking 分布。
  thinking 分布共 3,238 条，覆盖全部 100 题；失败题的最大 thinking 仅代表此前可分段轮次，不代表已知失败轮的 thinking。
- thinking 边界由生成 token 的 bytes 累积位置核对；本样本 3,238 条边界均恰好在 token 边界上，没有跨边界 token
  需要近似分摊。只在 18 条保存响应中看到非空独立 reasoning 字段，不能仅统计该字段，否则会漏掉正文里的 THOUGHT。
- 这里的“峰值上下文”是已实际发起调用时的峰值，不是累计计费输入，也不是最后一轮工具返回后未再次提交给模型的
  整段历史长度。整题累计输出和单轮上下文峰值也不能简单相加。

下面分位数统一采用 **nearest-rank：排序后取第 `ceil(p × N)` 个值**。按调用统计时，长轨迹题权重较大；
因此同时给出按题统计的峰值分布。四个错误终止实例属于提前停止轨迹，其观测长度不是“做完这些题所需长度”。

### 整题与每题峰值分布

单位均为 tokens，调用次数行除外。每题峰值先在该题所有调用内取最大值，再在 100 题间计算分位数。

| 指标 | 样本数 | 均值 | P50 | P90 | P95 | P99 | 最大值 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 整题累计输出 | 100 | 6,063.6 | 4,111 | 13,432 | 18,314 | 28,371 | 42,013 |
| 每题最大单轮完整输出 | 100 | 616.7 | 473 | 1,174 | 1,562 | 2,125 | 2,152 |
| 每题最大单轮 thinking 阶段输出 | 100 | 410.5 | 262 | 888 | 1,380 | 2,070 | 2,108 |
| 每题最大输入上下文 | 100 | 16,576.0 | 13,635 | 30,400 | 37,936 | 64,388 | 68,780 |
| 每题最大本轮输入＋输出 | 100 | 16,662.8 | 13,725 | 30,564 | 37,938 | 64,669 | 68,835 |
| 每题 API 调用次数 | 100 | 32.4 | 28 | 50 | 69 | 119 | 123 |
### 单轮分布

这是“一次模型调用通常有多长”的分布，不是上一张表的“每题最重一轮”的分布。

| 指标 | 调用样本数 | 均值 | P50 | P90 | P95 | P99 | 最大值 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 单轮完整输出 | 3,242 | 187.0 | 103 | 429 | 616 | 995 | 2,152 |
| 单轮 thinking 阶段输出 | 3,238 | 91.0 | 32 | 243 | 412 | 813 | 2,108 |
| 单轮输入上下文 | 3,242 | 13,574.2 | 10,236 | 28,785 | 38,907 | 60,369 | 68,780 |
| 本轮输入＋输出 | 3,242 | 13,761.2 | 10,393 | 29,088 | 39,111 | 60,533 | 68,835 |
例如，单轮 thinking 的 P95 为 412，并不代表把整题上下文窗口设为 412 就够了；对应的实际输入还可能包含
数万 tokens 的历史和工具输出。API 累计输入 44,007,454 tokens 包含每轮重复发送历史，更不是窗口大小。

仅看 70 个 resolved 实例：整题累计输出 P95 为 **13,822**、最大 **26,089**；单轮完整输出最大 **2,125**，
输入＋输出峰值最大 **64,669**。这个成功子集只用于补充解释，不代替全 100 题分母，也不能据此保证缩限后仍通过。

### 更小预算会覆盖多少已观测轨迹

以下是对已保存轨迹的静态比较，不是新配置下的实测结果，也不是失败率预测。缩小窗口或输出上限可能改变生成行为，
尤其是本次错误终止题尚未完成求解；不能将“当前未超阈值”解释为后续所有题或 IS 都不会截断。

| 拟比较的预算 | 已观测轨迹超过/触及预算的题数 | 其中原结果为 resolved 的题数 |
| --- | ---: | ---: |
| 整题累计输出 L = 8,192 | 17 | 10 |
| 整题累计输出 L = 16,384 | 6 | 3 |
| 整题累计输出 L = 32,768 | 1 | 0 |
| 整题累计输出 L = 65,536 | 0 | 0 |
| 单次完整输出上限 = 1,024 | 13 | 6 |
| 单次完整输出上限 = 2,048 | 2 | 1 |
| 单次完整输出上限 = 4,096 | 0 | 0 |
| 上下文窗口 = 32,768（含安全余量） | 8 | 5 |
| 上下文窗口 = 65,536（含安全余量） | 1 | 0 |
| 上下文窗口 = 98,304（含安全余量） | 0 | 0 |
比较规则：单次输出查 `output > cap`；累计输出查 `total >= L`；上下文查 `prompt + output + 256 >= window`，
对应当前预算终止判断。这里没有把最大输入和最大输出分别相加，而是使用同一调用的输入＋输出峰值。

- 整题累计输出最大、上下文峰值最大均为 `django__django-10554`：42,013 / 68,835 tokens，原结果未通过。
  它是 L=32,768 或上下文=65,536 时唯一超过上述预算的已观测实例，但不能因为当前没通过就把它当作可无代价截断。
- `matplotlib__matplotlib-20826` 已通过，但用了 119 次调用、累计输出 26,089、输入＋输出峰值 64,669；
  65,536 窗口扣除 256 余量后，仅比其观测峰值多 611 tokens，余量很小。
- 单轮完整输出最大 2,152 出现在 `sympy__sympy-22456` 的某个此前正常轮次，不是该题最后只输出 `TH` 的错误轮次。
  同理，每题最大 thinking 不一定发生在最后一轮。

### 对后续参数设置的参考（未修改配置）

基于本机这组样本，如果后续需要验证一个更紧凑的 **baseline 候选配置**，可从以下组合开始，而不是直接当作正式新协议：

| 参数 | 候选验证值 | 本次数据依据与限制 |
| --- | ---: | --- |
| 单次完整输出 `max_tokens` 上限 | 4,096；较保守可选 8,192 | 本次已观测最大 2,152；4,096 覆盖全部已观测调用，但未验证新采样/IS 的长尾 |
| 整题累计输出 L | 65,536 | 本次最大 42,013；32,768 会触及 1 条已观测轨迹；这不是单轮输出上限 |
| 模型上下文窗口 | 98,304 | 本次同轮输入＋输出最大 68,835，再加 256 为 69,091；65,536 不能覆盖所有已观测轨迹 |
| 每题硬截止 | 暂保留 1,800 秒 | 本次最长约 23 分 30 秒；本节没有新的超时阈值实验 |

如果首要目标是与现有结果可比、避免同时改变多个变量，也可以继续保留当前 **L=131,072、窗口=133,120**，
先只在独立验证中考察单次上限。EOS 会让正常响应提前结束；大 `max_tokens` 不等于每轮都生成到上限。
因此缩小上限主要限制异常长输出风险，不能从本表直接推断正常调用必然加速；缩窗对吞吐的影响也需要服务端实测。

对 thinking IS 的额外提醒：本次 3,238 个可分段响应中，2,940 个（约 90.8%）的 thinking 不超过 256 tokens，
3,075 个（约 95.0%）不超过 410 tokens。若仍将 **整题 L 的 10%** 作为短块上限，L=131,072 对应
`ceil(0.1 × L)=13,108`，即使 L=65,536 也有 6,554，均远高于本次最大 thinking 2,108。
按这些 baseline 轨迹，thinking 通常会先到 action 边界而不是触及块长；不能指望这样的 chunk 自动产生多步短块选择。
如果要研究单轮 thinking 的多步 IS，需要另行确认 chunk 的预算基准及边界停止实现；这里不擅自将原设计改成
“单轮上限的 10%”，也不把 baseline 长度分布当作 M=4、K=2 候选和 rollout 的长度保证。

### 11.1 百题长度完整数据（原CSV内嵌）

为仅保留一个结果文档，原独立长度CSV的全部字段及100行数据直接保存在下面，可提取代码块恢复CSV。
`source` 区分原百题与固定11题兼容补跑；`result` 是历史baseline官方结果。
`calls` 是该题模型调用数；`total_output_tokens` 是整题累计输出；`max_output_tokens` / `p95_output_tokens` 是单轮完整输出最大值/P95；
`max_thinking_prefix_tokens` 是每题最大单轮thinking阶段输出；`thinking_measured_calls` 是可按协议分段的调用数；
`max_prompt_tokens` 是最大单轮输入；`max_context_with_output` 是同一调用输入加输出的峰值。
不能把最大输入与最大输出分别相加，也不能把本表baseline输出当成IS全部候选/rollout成本。

```csv
instance_id,source,result,calls,total_output_tokens,max_output_tokens,p95_output_tokens,max_thinking_prefix_tokens,thinking_measured_calls,max_prompt_tokens,max_context_with_output
astropy__astropy-12907,original100,通过,31,5038,792,525,483,31,14595,14640
astropy__astropy-13236,original100,通过,18,1973,165,165,127,18,7669,7746
astropy__astropy-14365,original100,未通过,21,3147,370,306,186,21,12788,12838
astropy__astropy-14508,original100,通过,33,7932,1035,815,529,33,18332,18395
astropy__astropy-14995,original100,通过,21,2478,393,345,345,21,14722,14770
astropy__astropy-7671,original100,通过,33,5884,632,467,177,33,14564,14663
astropy__astropy-8872,rerun11,通过,17,2529,462,462,309,17,10456,10526
django__django-10554,original100,未通过,100,42013,1808,1021,1544,100,68780,68835
django__django-11099,original100,通过,9,948,242,242,25,9,4318,4367
django__django-11211,rerun11,通过,28,3022,439,413,290,28,12965,13078
django__django-11477,original100,未通过,31,2999,316,243,117,31,11080,11172
django__django-11532,original100,未通过,27,4475,392,319,228,27,12755,12804
django__django-11603,original100,通过,14,1443,241,241,107,14,6900,6981
django__django-11728,original100,通过,29,5747,756,582,472,29,15649,15726
django__django-11848,original100,未通过,18,2350,411,411,161,18,7546,7611
django__django-11951,original100,通过,8,707,182,182,66,8,4917,4966
django__django-11964,original100,通过,23,2835,266,260,122,23,14119,14169
django__django-12155,original100,通过,18,1594,196,196,79,18,7358,7410
django__django-12273,rerun11,未通过,51,14127,1062,764,979,51,31591,31727
django__django-12325,original100,未通过,39,6396,709,499,552,39,14834,14920
django__django-12419,original100,通过,17,1588,206,206,93,17,8497,8554
django__django-13195,original100,未通过,15,1530,409,409,82,15,7204,7254
django__django-13212,original100,未通过,27,4111,649,506,108,27,19283,19328
django__django-13279,rerun11,通过,30,5277,561,520,258,30,18503,18667
django__django-13315,original100,未通过,20,3459,413,360,110,20,9916,9967
django__django-13346,rerun11,通过,39,9344,1024,823,760,39,25152,25282
django__django-13363,original100,通过,11,1205,191,191,55,11,6769,6843
django__django-13406,original100,通过,49,8942,864,680,800,49,24383,24522
django__django-13569,original100,通过,36,6611,612,537,341,36,18836,18884
django__django-13658,original100,通过,7,685,227,227,26,7,3252,3301
django__django-13810,original100,通过,21,4216,674,542,397,21,13863,13966
django__django-13837,original100,通过,30,5822,911,862,437,30,14668,14718
django__django-14017,original100,通过,31,4273,585,371,333,31,13635,13725
django__django-14089,original100,通过,7,636,166,166,45,7,3551,3595
django__django-14315,original100,未通过,9,1087,278,278,239,9,4813,4884
django__django-14404,original100,通过,36,6726,472,462,216,36,15791,15857
django__django-14493,original100,通过,32,6112,572,533,262,32,13558,13649
django__django-14534,original100,未通过,45,4397,350,232,271,45,14323,14415
django__django-14580,original100,通过,23,2538,271,232,152,23,12078,12180
django__django-14771,original100,通过,35,3454,277,259,151,35,15106,15155
django__django-15098,original100,格式错误,25,4819,664,563,627,24,17120,17135
django__django-15380,original100,通过,18,2219,442,442,97,18,7701,7805
django__django-15382,original100,通过,77,13822,935,783,877,77,33681,33805
django__django-15525,rerun11,格式错误,35,7084,808,726,424,34,24511,24543
django__django-15554,rerun11,通过,104,19884,979,666,888,104,43799,44092
django__django-15695,original100,未通过,34,6901,813,664,614,34,15890,15935
django__django-15973,original100,通过,36,4789,342,315,262,36,14893,14985
django__django-16333,original100,通过,7,601,230,230,38,7,3580,3625
django__django-16662,original100,通过,24,3213,449,317,193,24,10937,11035
django__django-16801,original100,通过,15,2125,317,317,70,15,7268,7312
django__django-16938,original100,未通过,32,6506,557,540,508,32,18834,18922
django__django-17087,original100,通过,26,2368,273,222,97,26,9188,9272
django__django-9296,original100,通过,8,817,223,223,36,8,4370,4419
matplotlib__matplotlib-13989,original100,通过,25,2489,230,211,187,25,10896,10973
matplotlib__matplotlib-20676,original100,通过,30,4509,656,417,254,30,13125,13174
matplotlib__matplotlib-20826,original100,通过,119,26089,1998,751,1380,119,64388,64669
matplotlib__matplotlib-23476,original100,未通过,29,6995,875,861,818,29,21784,21906
matplotlib__matplotlib-24570,original100,通过,21,3331,597,591,498,21,9354,9437
matplotlib__matplotlib-24637,original100,未通过,41,7489,617,474,543,41,20573,20687
matplotlib__matplotlib-25332,original100,通过,45,11966,726,655,345,45,22473,22569
matplotlib__matplotlib-25960,original100,通过,44,13432,1174,931,908,44,31960,32153
matplotlib__matplotlib-26291,original100,通过,30,3870,346,334,237,30,17871,18047
matplotlib__matplotlib-26466,original100,未通过,43,3206,244,182,142,43,13227,13268
pallets__flask-5014,original100,通过,15,1464,227,227,47,15,7828,7878
psf__requests-2931,original100,通过,28,6030,563,477,475,28,13040,13161
pydata__xarray-6599,original100,未通过,44,15049,1562,829,1524,44,29248,29292
pydata__xarray-6938,original100,未通过,24,3820,628,324,584,24,11857,11939
pydata__xarray-7393,original100,通过,28,3152,304,285,219,28,12266,12310
pytest-dev__pytest-10356,original100,未通过,49,10634,692,479,439,49,24398,24511
pytest-dev__pytest-5787,original100,通过,58,12165,1306,1163,382,58,35763,35906
pytest-dev__pytest-7236,original100,通过,24,4098,460,413,419,24,13481,13530
scikit-learn__scikit-learn-11310,original100,通过,20,2464,331,325,70,20,10882,10933
scikit-learn__scikit-learn-14894,original100,重建错误,9,1835,647,647,197,8,5331,5978
scikit-learn__scikit-learn-25102,original100,通过,69,18314,2125,738,2070,69,44465,44566
scikit-learn__scikit-learn-25931,original100,通过,25,5957,713,615,575,25,14442,14528
sphinx-doc__sphinx-10614,original100,未通过,63,13622,1371,763,992,63,30400,30564
sphinx-doc__sphinx-11445,original100,通过,32,5243,565,539,462,32,13997,14116
sphinx-doc__sphinx-7454,original100,通过,50,8064,695,468,641,50,26464,26578
sphinx-doc__sphinx-7889,original100,通过,17,1716,261,261,61,17,7233,7278
sphinx-doc__sphinx-8548,rerun11,未通过,123,28371,1549,692,1234,123,60570,60691
sphinx-doc__sphinx-8551,original100,通过,34,3677,413,371,189,34,16187,16220
sphinx-doc__sphinx-8721,rerun11,通过,37,7216,969,610,554,37,20227,20277
sphinx-doc__sphinx-9258,original100,通过,50,6946,521,407,420,50,24568,24617
sphinx-doc__sphinx-9658,original100,通过,42,7996,666,569,519,42,20061,20112
sphinx-doc__sphinx-9673,original100,通过,24,3020,355,260,183,24,15856,15905
sphinx-doc__sphinx-9711,original100,通过,26,4225,568,484,118,26,9807,9926
sympy__sympy-13372,original100,通过,17,2048,348,348,91,17,7037,7094
sympy__sympy-13615,original100,通过,40,6063,536,396,307,40,13362,13451
sympy__sympy-14711,original100,通过,23,2228,193,156,107,23,6846,6928
sympy__sympy-15976,original100,未通过,30,7566,1254,684,636,30,20566,20668
sympy__sympy-16597,original100,未通过,26,3528,504,442,398,26,10077,10148
sympy__sympy-17139,original100,通过,12,1280,221,221,100,12,4864,4932
sympy__sympy-17318,original100,未通过,23,3446,327,290,269,23,11449,11533
sympy__sympy-18211,original100,通过,25,3282,377,357,227,25,9445,9494
sympy__sympy-18763,original100,未通过,18,2168,449,449,123,18,10774,10818
sympy__sympy-20801,original100,通过,45,5789,473,378,348,45,17576,17671
sympy__sympy-21847,original100,通过,12,1306,215,215,105,12,6477,6542
sympy__sympy-22456,rerun11,格式错误,69,23456,2152,1192,2108,68,37936,37938
sympy__sympy-22914,original100,通过,12,1083,238,238,53,12,4802,4851
sympy__sympy-23413,rerun11,通过,42,9865,1812,745,1729,42,21481,21533
```

## 12. 阶段验证与工程修复汇总

本节替代分散的smoke、五题、20题、30题及兼容诊断报告；这里只保留与最终百题结论有关的信息。
各阶段原始轨迹、配置快照和官方报告仍保存在 `results/swebench/`，阶段成绩不混入当前百题主分母。

### 12.1 阶段成绩与合并边界

| 阶段 | 实测结果 | 如何解释 |
| --- | --- | --- |
| Baseline 单题端到端 | `pytest-dev__pytest-7982`，1/1通过 | 验证生成、工具、提交、官方判题闭环 |
| Baseline 随机五题 | 5/5通过 | 仅作小样本流程验证，不推断百题通过率 |
| 原始 Baseline 百题 | 63/100 | 原始报告保留，不覆盖 |
| 固定11题 reasoning 兼容补跑 | 7/11通过；原89条＋补跑11条合并为70/100 | 整体替换固定名单，不按结果择优；不是统一版本重跑百题 |
| Thinking IS 单题 smoke | `pytest-dev__pytest-7982`，1/1通过 | 11轮工具交互、12步IS选择，验证了多步分块链路 |
| 原始20题 Thinking IS | 7/20；相同题历史baseline为12/20 | 两题边界适配异常、两题30分钟超时、一题真实补丁错误构成五道回退 |
| 固定两题边界修复补跑 | 2/2通过，合并20题为9/20 | 18条旧记录＋2条新记录，不能当作统一协议20题重测 |
| Baseline 失败30题的不限时IS | 7/30通过 | 与其余70题组成原始v2百题，不单看救回而忽略成功题回退 |
| 原始完整IS百题 | 62/100 | 救回7题、回退15题，见历史第1–8节 |
| 固定九题零thinking修复补跑 | 7/9通过；91条v2＋9条v3合并为69/100 | 救回10题、回退11题，见第0节与第9节 |

### 12.2 已发现和处理的问题

1. **独立reasoning被误拒绝。** 旧适配器遇到非空 `reasoning_content` / `reasoning` 就拒绝，未先检查完整生成token是否已有logprobs。
   回放证实部分响应的评分实际覆盖reasoning、thinking marker、正文与EOS；另有 `THO<think>` 前缀被服务parser拆分丢弃的情况。
   兼容处理以sampled-token bytes重建完整文本，严格核对字段、usage和评分覆盖，保留真实前缀；不伪造logprobs、不删除thinking。
   动作解析与后续history使用还原后的完整文本，消除重复reasoning字段；无评分、字段冲突或无法重建的响应仍拒绝。
2. **thinking/action边界跨token。** 原20题中 `astropy__astropy-8872`、`sphinx-doc__sphinx-7454` 触发边界适配异常。
   修复保留原始token前缀和正文首字符，thinking奖励排除与正文共享的token，不靠重新分词伪造采样前缀；两题修复后均通过。
3. **合法零thinking被当成流程失败。** v2遇到候选直接进入合法动作、全部没有thinking分数时终止。
   v3仅在没有任何已评分候选且存在经过审计的合法零thinking候选时，在这些合法候选中均匀选择；有正常分数时维持原权重，无效候选不获权重。
   这是SWE适配层修复，不等于通用核心存在同一个缺陷；主仓库通用Consilience的空thinking回退语义另有定义。
4. **历史30分钟限制与新不限时协议不同。** 早期20题出现过整题超时；后续30＋70题及九题v3补跑取消整题时间上限，仍保留单API请求1800秒超时和token预算。
   不能把限时与不限时结果当作严格同预算算法对照，也不能把API超时和整题截止混淆。
5. **官方日志标签的二次解释有误。** `pytest-dev__pytest-5787` 的 `no_tests_collected` 标签经原日志复核不成立，实际运行127项测试并有PASS_TO_PASS失败。
   已纠正文字归因，官方未通过分数不变；10356的歧义标签没有据此一并宣称解决。详见第0.9节。

### 12.3 不应误称已经解决的失败

- 历史baseline三道动作格式失败：`django__django-15098` 拼错命令标签、`django__django-15525` 的opening tag不匹配、`sympy__sympy-22456` 仅输出 `TH` 后EOS。
  保存的token流能完整还原，均为正常stop而非长度截断；不能归咎于parser误拒绝合法命令，也不能靠扩大L直接解决。
- 历史baseline的首次格式错误直接结束是旧fail-fast策略；后续允许连续3次格式错误是agent协议变化，应单列说明。
- `scikit-learn__scikit-learn-14894` 历史第9次拒绝响应未保存，因此当时无法离线确定响应重建失败的具体文本根因。
  后续baseline补跑通过不反向补全缺失证据，也不能把该题历史流程恢复当作IS独有收益。两题baseline补跑分析见第6.6–6.7节。
- guarded-v2的每轮4块／60秒IS预算、1024-token rollout、普通续写fallback及收尾提醒仅是独立变体设计，未计入本报告主结果；不声称它已经提升百题通过率。

## 13. 复现入口、部署说明与本轮重测隔离

### 13.1 固定样本和服务

- 百题清单：`configs/qwen38_swebench_random100_instances.txt`；100个不同ID，SHA-256为 `559abe0a8499a40f0c82837f1b9cdf79ccaead21cd21555878ef1b7c5e8461eb`。
- 数据集、agent版本及统计协议见第2节；实验设计保留在 `docs/experiments/SWEBENCH_QWEN38_27B_THINKING_IS_EXPERIMENT.md`。
- 给另一Codex的自包含复跑说明及完整清单保留在 `docs/experiments/SWEBENCH_RANDOM100_CODEX_HANDOFF.md`，不是第二份实验结果报告。
- 权重只读目录：`/data/users/jenkins/qwen38-models/Qwen3.8-27B`，容器内为 `/models/model`；API模型名 `qwen3.8-27b` 是本地服务标识。
  本地权重配置声明 `model_type=qwen3_5`、`architectures=[Qwen3_5ForConditionalGeneration]`；报告标题和目录名不能代替官方权重身份或下载来源证明。
- 历史双服务映射：`qwen38-27b-v100` 使用GPU4–7／`http://127.0.0.1:8000/v1`；`qwen38-27b-v100-replica` 使用GPU0–3／`http://127.0.0.1:8001/v1`。
  均仅监听本机，复用同一权重；不要在另一台机器上照抄127.0.0.1地址。
- 两服务历史配置：TP=4、FP16、`max_model_len=133120`、`gpu_memory_utilization=0.85`、`max_num_seqs=8`、`max_num_batched_tokens=8192`，启用prefix caching。
  使用 `processed_logprobs`／top-5、`generation_config=vllm`、`FLASH_ATTN_V100`、GDN `triton`、reasoning parser `qwen3` 和tool parser `qwen3_coder`，禁用custom all-reduce。
- 部署脚本：`experiments/swebench/deploy_qwen38_replica.sh`；历史镜像与配置一致性证据：`results/deployments/qwen38-replica-20260918/parameter_comparison.json`。
  历史部署镜像ID为 `sha256:41ea41cbd04a6ff6252e7918ab538cc4d6807a9dec2c5e39d733ae7718202e22`。

### 13.2 完整v3百题独立统计，不混入历史69/100

本轮已于2026-09-23完成，官方判定63题通过、36题未通过、1题评测异常，按固定100题口径记63%。
全100题统一使用v3采样器，不再是91条v2＋9条v3的拼接结果；baseline没有重跑，历史对照仍有协议差异。详细结果与审计见第14节。

- 当前基线提交：`ac23896`，上游基线为 `45a3669`，另外包含归档的本地适配兼容改动；不是纯提交快照。
- 配置：`configs/qwen38_swebench_thinking_is_random100_v3_unlimited.toml`；启动器：`experiments/swebench/run_random100_v3_dual_background.sh`。
- 运行产物：`results/swebench/qwen38-thinking-is-random100-v3-unlimited-dual-20260922-r1/`，实际在数据盘。
- 每个服务50题，chunk=100、M=4、K=2、L=131072、上下文133120，不设整题时间限制，正文普通生成。
- 运行使用产物目录下的独立 `source/` worktree；源码tar快照、未提交补丁、版本、依赖、分片、输入hash及退出码文件均已保存。
- 文档清理不删除该worktree、不操作其进程/容器、不覆盖日志，也不移动任何原始结果。根分区与数据盘的4GiB启动前保护照常生效。
- 本次只删除合并后的旧报告、HTML展示与独立长度CSV；功能代码、实验设计、清单、运行配置、脚本、测试及原始评测证据继续保留。

## 14. 统一v3百题结果及11道回退审计（2026-09-23）

### 14.1 结果口径与完成状态

**本轮结论：增加Thinking IS计算没有提高这批题的通过率，反而比历史baseline低7个百分点。11道回退均有真实测试失败，不是未跑完、30分钟截断或零thinking拒绝。**

| 指标 | 历史baseline | 本轮统一v3 Thinking IS |
| --- | ---: | ---: |
| 固定题数 | 100 | 100 |
| 官方通过 | 70 | 63 |
| 通过率 | 70% | 63% |
| 本轮正常提交、非空补丁 | — | 100 |
| 本轮推理异常 | — | 0 |
| 官方未通过／评测异常 | — | 36／1 |

| 配对结果 | 数量 |
| --- | ---: |
| baseline通过、IS通过 | 59 |
| baseline未过、IS通过 | 4 |
| baseline通过、IS未过 | 11 |
| 两组均未获通过判定 | 26 |

- 4道救回：`django__django-15525`、`matplotlib__matplotlib-24637`、`scikit-learn__scikit-learn-14894`、`sympy__sympy-17318`。前述历史baseline流程失败及补跑边界仍适用，不能把全部救回都认定为算法独有收益。
- 唯一评测异常为 `sympy__sympy-22456` 的补丁应用失败，不在11道回退中。100题分母不剔除此题；启动器退出码为0不代表每题评测都无异常。
- 两分片分别33/50、30/50。2026-09-22 00:21:02启动，2026-09-23 05:27:45收尾，墙钟约29小时7分钟，包含磁盘保护等待和评测。
- 单题agent用时均值30.35分钟、中位数9.35分钟、最长269.72分钟；26题超过30分钟。累计runner用时50.60小时，不能与双服务墙钟直接等同。
- 与历史混合版本相比：69→63；回退题数都是11，但只重合9题。历史回退中的 `django__django-11964`、`pytest-dev__pytest-5787` 本轮通过；本轮新增回退为 `astropy__astropy-14508`、`matplotlib__matplotlib-24570`。

### 14.2 十一道题具体错在哪里

下表来自本轮最终补丁、历史baseline补丁、官方逐题报告及失败日志，不使用历史失败原因替代本轮检查。时间取各题保存的runner耗时，单位分钟。FTP指应修复的测试未通过，PTP指原有应保持通过的测试被破坏。

| 题目 | baseline／IS用时 | 官方失败测试（简写） | 本轮IS补丁的问题与baseline差异 |
| --- | ---: | --- | --- |
| `astropy__astropy-13236` | 1.09／4.56 | FTP：`test_ndarray_mixin[False]`、`test_structured_masked_column` | IS只增加弃用警告，仍把结构化数组自动转换为NdarrayMixin；baseline移除了这段转换。核心行为没有改到要求的状态。 |
| `astropy__astropy-14508` | 5.23／8.62 | PTP：`test_invalid_float_cards2` | IS改用`str(value)`，只在长字符串回退分支规范化指数，短字符串仍输出小写`e`，违反FITS格式；baseline覆盖了这条路径。 |
| `django__django-13406` | 6.21／62.93 | FTP：两个annotation pickle测试 | IS给Query保存原iterable类型，反序列化继续返回tuple／flat，而目标行为需要字典；baseline按`values_select`恢复ValuesIterable。属于理解错了接口语义。 |
| `django__django-14404` | 3.96／0.73 | FTP：两个SCRIPT_NAME斜杠测试 | IS将路由解析的`path_info`改成`path`，错误带入部署前缀；baseline保留路由解析输入，只修正重定向地址。 |
| `django__django-14771` | 2.19／3.23 | FTP：`test_xoptions` | IS虽然保留了选项值，但把布尔开关写成`-Xutf8=True`，而非`-Xutf8`；baseline单独处理True等无值开关。不是旧版本“所有值丢失”的同一个补丁。 |
| `django__django-15973` | 2.69／18.53 | FTP：`test_create_with_through_model_separate_apps` | IS在schema层跳过字符串through模型，绕过表象；baseline修正autodetector跨应用through模型依赖。修复层级错误。 |
| `matplotlib__matplotlib-24570` | 1.95／42.62 | FTP：`test_packers[bottom/top]` | IS只在HPacker局部交换top/bottom，未覆盖共享对齐逻辑及VPacker；baseline修改公共`_get_aligned_offsets`。 |
| `psf__requests-2931` | 2.99／3.14 | PTP：`test_params_bytes_are_encoded` | IS让编码函数返回bytes，却漏了URL拼接侧的native-string转换；baseline同时修两端，IS破坏原有bytes查询参数行为。 |
| `sphinx-doc__sphinx-9711` | 2.43／3.49 | FTP：`test_needs_extensions` | IS只有版本不足分支才给`not_new_enough`赋值，满足要求时读取未初始化局部变量；baseline直接比较解析后的版本。 |
| `sympy__sympy-17139` | 0.82／3.37 | FTP：`test__TR56` | IS只给大小比较加`is_real`保护，非实数指数仍会落入后续变换；baseline增加非整数指数退出条件。 |
| `sympy__sympy-18211` | 2.41／28.21 | FTP：`test_issue_18188` | IS返回ConditionSet时没有恢复用户原始符号，内部`_gen`泄漏到结果；baseline处理了符号替换恢复。 |

两道PTP失败说明：不是仅仅“没修好新问题”，也确实发生了对原有功能的回归。其余9题在要求修复的测试上失败。5题本轮失败补丁与历史IS失败补丁逐字相同：13236、14404、2931、9711、17139，说明不能只用偶然服务抖动解释全部回退。

### 14.3 核心采样和数据链路审计

对11题使用本轮冻结源码、归档API响应和本地tokenizer离线重放；没有请求模型、重跑题目或改官方评分。

- **3,056次请求、294轮交互、440次选块全部重放一致**：请求角色、seed、token前缀hash、候选与rollout奖励、权重、ESS、选中块、正文衔接、解析动作以及token计数均匹配归档。
- 独立计算指数权重与固定K=2均值，再做候选间归一化，与保存结果一致；没有发现候选索引串位、奖励配错、归一化算错或选中块未接入前缀。
- 11题API错误和动作解析失败均为0，最终状态全部Submitted，没有因L、上下文或整题时间上限终止。trajectory提交、preds补丁和官方实际评测补丁相同，官方记录均成功应用补丁。
- 11题baseline与本轮IS保存的dataset.parquet逐题所有字段一致，排除了题目、base commit或测试字段错配；baseline官方报告也确认这11题确实通过。
- 有1条API响应的单段text与完整token解码不同，但token链与实际动作重放一致；这项审计没有把文本边界差异直接当成失败原因。
- 当前工作区相关单测：`tests/test_swebench_thinking_is.py`及`tests/test_swebench_api_model.py`，**81 passed**。这只能覆盖已有断言，不能证明全部实现和设计没有问题。

**结论边界：未发现本轮11题的采样记账、拼接或评分复算错误；不等于证明Consilience能识别正确修复，也不等于证明agent适配环境没有问题。** 重放使用已归档模型响应，不验证服务端原始logits，也不证明另一个未选候选一定正确。

### 14.4 新发现：求解阶段验证环境和验证方式有薄弱点

保存的mini-swe-agent环境使用`bash -c`、工作目录`/testbed`，没有显式指定任务的`/opt/miniconda3/envs/testbed`解释器；system prompt也没有对应环境指引。轨迹中可直接看到模型调用base环境的`/opt/miniconda3/bin/python`，随后出现依赖缺失或版本不兼容。

这不是官方最终判题环境失败，而是**模型修代码时没有顺利运行真实仓库测试，得到的反馈不足**：

- **astropy-14508**：导入因缺少`erfa`失败，IS改为抽出`_format_float`函数单独执行。浮点数round-trip可成功，但没有检查FITS对大写指数的要求；baseline轨迹则找到了testbed解释器。
- **matplotlib-24570**：日志明确显示base解释器且缺少numpy；IS手写简化对齐函数验证，只覆盖其自身修复思路，没有跑真实HPacker／VPacker测试。baseline使用了testbed环境。
- **sphinx-9711**：缺少docutils，随后测试简化的版本比较函数及语法编译；这些不能覆盖实际函数中未赋值变量的路径。
- **django-15973**：IS有多次导入／测试定位问题，没有看到显式testbed环境调用；baseline有该环境调用记录。这里只能确认验证路径不同，不能断言环境是该题唯一原因。
- **sympy-17139、sympy-18211**：IS最终使用了任务环境，已有相关测试通过，仍漏掉目标边界条件，说明“环境正确”也不等于“测试充分”。

11题中10题轨迹出现过依赖、导入或测试环境错误；这包含测试模块定位问题，**不能解释为10题全是Conda配置导致失败**。历史baseline也遇到过类似错误，这不是已证明的IS独有缺陷。正确表述是：共享执行环境存在可改进之处，而不同采样路径影响模型是否自行找到正确环境，进而影响验证质量。

### 14.5 为什么更多计算没有换来更好补丁

1. **Consilience不是代码正确性奖励。** 当前只从thinking的token logprob统计计算代理分数，不运行候选工具命令、不比较真实测试结果，也不看最终补丁是否修复问题。它可以偏好表达更连贯但语义错误的修复方向；这是与逐题证据相容的机制解释，不是已证实每题的唯一因果归因。
2. **rollout不等于端到端试修。** rollout补全thinking用于估计当前短块，选中后只保留短块，再继续生成；rollout没有在独立仓库里落地补丁并跑测试。正文普通生成也仍有随机性，因此加M/K并不保证找出通过补丁。
3. **实际很多轮没有四个思考块。** 294轮中233轮（79.3%）最终选中的thinking不超过100 tokens。chunk=100是上限划块方式，不保证每轮平均分四块；本轮这11题主要是在很短的思考之间做选择。
4. **IS是按权重采样，不是每步取最高分。** 440步中159步（36.1%）选中的候选权重低于最高权重，这是当前算法定义，不是索引错误。另有183步（41.6%）最高候选概率仍小于0.4，代理分数区分度有限；也有53步最高概率大于0.9，不能说权重始终接近均匀。
5. **仍存在待验证的策略偏置。** 25步同时出现空thinking候选和可评分候选，此时v3排除空候选、在可评分候选中抽样；3步才使用空thinking均匀回退。该规则是现有协议，重放与协议一致，但是否不利于简单动作尚需消融，不能直接当成已经证实的bug。
6. **历史对照还混有协议与随机路径差异。** baseline没有按本轮完全相同的适配协议重跑，同seed也不意味着多候选与单候选产生相同随机轨迹。现有结果足以确认这次实际效果下降，但不足以把−7个百分点全归因于某一公式或估计普遍收益。

不建议仅靠提高L、增加M/K或加奖励z-score来“修好”这11题：没有截断证据，更多代理评分不自动带来正确性；改变奖励标准化、改成argmax、改变空thinking政策都会构成新实验协议。

### 14.6 建议下一步与证据入口

优先级如下，**本次只分析和离线验证，没有启动补跑或修改运行逻辑**：

1. **先补齐两组共用的任务环境检查。** 在执行真实测试前确定任务解释器、依赖与仓库可导入；baseline和IS使用同样机制。不能简单假定把`bash -c`换成`bash -lc`就已解决，需要验证实际解释器。也不把隐藏评测补丁或官方答案提供给agent。
2. **做小样本同协议验证，不直接再跑100题。** 优先选astropy-14508、matplotlib-24570、sphinx-9711验证真实测试能否运行；另选已经能运行测试的SymPy案例作对照，区分环境问题与测试覆盖不足。改善环境不保证模型一定写对。
3. **再隔离代理奖励的作用。** 以同一token-prefix／agent适配路径的无IS为对照，加入同M/K、均匀选候选的消融，与Consilience加权选择比较；固定公开配置、使用多个预先指定seed及包含成功与失败的样本，记录准确率、耗时、token和真实测试执行情况。
4. **最后再决定是否改奖励或采样。** 如要加入执行反馈，那是新的奖励/agent设计，应另立实验；不能用这11题的隐藏测试定向调参后把训练式修正当泛化增益。

原始结果根目录：`results/swebench/qwen38-thinking-is-random100-v3-unlimited-dual-20260922-r1/`，其中`summary.json`为全量汇总，每个分片run目录的`evaluation/reports/`及`evaluation/logs/run_evaluation/`保存官方证据，`source/`保存实际运行源码。

本次新增的是机器可读审计证据，不增加第二份结果Markdown：

- `results/analysis/swebench-fullv3-regression11-20260923/paired100.json`：本轮100题与历史baseline配对布尔结果，评测异常单独标记。
- 同目录`paths.json`：11题baseline、本轮IS及历史IS证据路径。
- 同目录`replay.json`、`replay.log`、`replay.py`：逐题离线重放结果、日志及脚本；复跑应使用原始run的`source/src`作为导入路径。
- 同目录`dataset_check.json`：11题两组保存数据的全字段一致性检查。

以上审计不能由统计相关性证明奖励导致失败，但能把问题缩小到：**模型修复语义与边界覆盖不足、真实测试反馈不充分、以及thinking代理奖励是否选对方向**；目前没有证据应继续把这11题归为零thinking流程故障或长度预算不足。

### 14.7 任务环境修复及真实容器验证（2026-09-23）

**此前的环境问题已有历史迹象，并非本轮才产生。** 回查上一轮IS与baseline原始轨迹，astropy-13236已有缺少erfa、requests-2931已有collections.MutableMapping兼容错误、sphinx-9711已有缺少docutils／babel等记录。旧预检只检查宿主依赖、Docker服务、数据集和API；早期smoke证明了生成—提交—官方判题链路，但没有形成逐题求解环境验收。这是此前验证覆盖不足，不能用“单测通过”替代真实环境检查。

本次已落实修复：

1. 在所有实验组共用的工具执行层逐命令激活Conda testbed环境，避免独立shell重新落回base。激活失败不执行原动作。
2. 初始session创建模型前检查任务解释器、工作目录、项目实际导入路径和测试入口；失败保存`TaskEnvironmentError`及诊断，停止该题并清理容器。恢复候选检查点只检查解释器，不把修改后代码的导入错误误判为初始环境错误。
3. 同时给baseline与IS加入实际仓库测试指引。保留工具原始返回码与输出，不把普通断言失败、项目本来待修复的失败当成环境错误，也不自动要求全部测试通过才能提交。
4. 新结果协议为`swebench-is-mh-v6`，环境协议为`swebench-testbed-v1`；不沿用旧schema的完成记录，默认拒绝在旧协议manifest目录续写。采样方法与预算未改，但环境和共同prompt已变，后续应使用新目录、同协议两组验证。

**验证不是只跑mock单测。** 使用真实session工厂、工具包装器和本机原始题目镜像，没有应用历史模型补丁、官方测试补丁或标准答案，没有请求模型：

| 真实容器题目 | 原仓库测试入口 | 结果 |
| --- | --- | --- |
| astropy-14508 | `test_header.py -k invalid_float_cards2` | 1 passed |
| matplotlib-24570 | `test_offsetbox.py` | 271 passed，1 skipped |
| sphinx-9711 | `test_config.py` | 34 passed |
| sympy-17139 | `bin/test .../test_fu.py` | 27 passed |
| django-14771 | `utils_tests.test_autoreload.TestChildArguments` | 8 passed |
| requests-2931 | `test_requests.py -k params_bytes_are_encoded` | 1 passed |

六个容器均显示实际Python为`/opt/miniconda3/envs/testbed/bin/python`；合计342项测试通过、1项跳过，模型API请求为0。验证容器均已清理，没有操作模型服务或其他人的任务容器。

验证中发现并处理两项检查本身的边界：旧版SymPy不一定存在`sympy.testing.runtests`，因此检查其稳定公开入口`sympy.test`；Sphinx题目的原始checkout没有`tests/test_extension.py`，不能拿评测补丁引入的文件作初始环境检查，改用现有`test_config.py`。Astropy仍有numpy ABI警告、Sphinx／Requests仍有弃用警告，均未隐藏；这不是“所有环境警告都消失”的声明。

全部SWE-bench回归测试 **188 passed**，覆盖逐shell激活、激活失败不执行命令、引号／cwd／退出码保真、错误prefix和依赖失败、分支恢复、失败清理、baseline／IS零API调用的失败审计，以及旧schema不混用。详细命令输出和验证脚本保留在`results/analysis/swebench-task-environment-fix-20260923/validation.json`及同目录`verify.py`。

**边界：这是执行环境修复与原仓库测试可运行性验证，不是6道题解题通过，更不是11道回退已救回。** 导入探针不等于全量测试收集，不能保证任意测试路径、插件或后续模型代码都无错误；模型也仍可能自行使用绝对路径绕开默认Python。实际补题收益需要后续同协议实验验证；历史70/100、63/100及所有判题结果保持不变。本次没有自动开始模型补跑。

### 14.8 环境修复后最短回退题独立补跑：django-14404（2026-09-23）

用户随后要求从11道回退中选上一轮IS耗时最短的一题补跑。本次仅运行`django__django-14404`；它上一轮runner用时43.92秒，是11题中最短。该题此前六轮直接提交，没有因依赖缺失导致测试失败的记录，因此是端到端环境接入检查，不是最能隔离Conda问题因果效应的案例。

**结果：环境修复生效，但题目仍未通过。** 2026-09-23 11:00:59启动，11:10:22完成生成、判题及收尾；整条流水线约9分23秒。生成和评测进程退出码均为0，不等于题目resolved。

| 指标 | 上一轮统一v3 IS | 本次修复后单题 |
| --- | ---: | ---: |
| 官方resolved | false | false |
| runner耗时 | 43.92秒 | 423.79秒（7分4秒） |
| agent耗时 | — | 422.22秒 |
| 工具调用／交互轮数 | 6 | 19 |
| 本次API请求／失败 | — | 189／0 |
| 本次选中轨迹输出／全部候选与rollout输出 | — | 3,494／12,574 tokens |
| 本次官方目标测试 | — | 0通过、2失败 |
| 本次官方原有测试（PASS_TO_PASS） | — | 323通过、0失败 |

配置：独立`configs/qwen38_swebench_thinking_is_envfix_django14404.toml`，只改run tag与单题filter；模型API、agent预算、arm配置与统一v3百题相同。使用原shard_b对应的8001服务，权重挂载和关键启动参数已核验；runtime fingerprint仍为`cbc4f5277d74b13f1aece6c1e10770c723338e5ab0c3dbc8bb118e342ae8b55c`。chunk=100、M=4、K=2、L=131072、上下文133120、seed=20260916、不限整题时间。区别仍包括第14.7节的执行环境与共同prompt修复，不宣称完全同协议消融。

环境证据与验证质量分开记录：

- 初始探针用时0.83秒，`status=ready`，Python为`/opt/miniconda3/envs/testbed/bin/python`；Django及其测试runner分别从`/testbed/django/__init__.py`、`/testbed/django/test/runner.py`导入，探针errors为空。
- 模型第3轮实际执行`python -c "import django; print(django.__version__)"`成功，证明初始化后实际工具命令也能导入任务代码。
- 本次仍没有执行仓库的`tests/runtests.py`或pytest测试入口。模型编写的复现脚本曾错误导入不存在的`django.http.Request`，另一次遗漏`SECRET_KEY`；这些是脚本/API使用错误，不是Conda缺依赖。最后一个脚本捕获Http404并打印，返回码0也不代表修复验证成功。
- 模型曾认识到路由解析应使用`path_info`而重定向应使用`path`，但随后仍以未经验证的“官方PR就是这样改的”推断支持原错误修改。最终补丁与上一轮IS**逐字相同**：把用于`resolve()`的`request.path_info`改成`request.path`，导致部署前缀进入路由解析。
- 官方补丁应用成功，`infra_failure=false`，仍失败于`test_missing_slash_append_slash_true_force_script_name`和`test_missing_slash_append_slash_true_script_name`。baseline原补丁保留解析逻辑，仅把重定向目标改为`request.path + '/'`。

**结论边界**：自动选择正确环境已经修复并在模型端到端运行中验证；“模型必定完成有效测试验证”并没有由此得到保证，新增提示也不是强制验证机制。该题增加了交互和计算但未改正补丁，不能说11题问题已解决，不能把本次失败重新归为依赖安装或长度截断。约409.58秒用于模型API，0.83秒用于环境探针；耗时增长主要来自更多生成请求，不是Conda检查本身。

本次结果独立保存，不择优替换、不重算历史百题成绩，也没有启动其他题。产物目录：`results/swebench/qwen38-thinking-is-c100-envfix-django14404-20260923/`，包括配置与源码快照、`comparison.json`、原始trajectory／record、官方评测日志、报告及退出码。下一步若继续验证环境问题的影响，应另行选择之前明确缺依赖的案例；若要求agent必须完成有效测试，则属于下一项流程约束，需要单独设计并对两组一致实施。

### 14.9 第二短回退题补跑：requests-2931通过（2026-09-23）

用户要求再选一道耗时短的题。本次仅补跑`psf__requests-2931`：其上一轮IS runner用时188.23秒，为11道回退中的第二短；此前轨迹确实存在base Python下的`collections.MutableMapping`兼容错误，无法顺利导入真实Requests项目。

**官方结果：resolved=true，1/1题通过；目标测试1/1通过、原有测试84/84通过，评测异常0。** 该题历史baseline通过、上一轮IS未过，本次恢复通过。2026-09-23 11:27:52启动，11:43:43完成整条流水线，约15分51秒；两阶段退出码均为0，官方没有未停止的评测容器。

| 指标 | 上一轮统一v3 IS | 环境修复后独立补跑 |
| --- | ---: | ---: |
| 官方resolved | false | **true** |
| runner耗时 | 188.23秒（3分8秒） | 873.35秒（14分33秒） |
| agent耗时 | 187.56秒 | 872.20秒 |
| 工具调用／交互轮数 | 16 | 29 |
| 模型API请求／失败 | 102／0 | 317／0 |
| 全部候选与rollout输出 | 6,044 tokens | 24,657 tokens |
| 本次选中轨迹输出 | — | 5,010 tokens |

配置：`configs/qwen38_swebench_thinking_is_envfix_requests2931.toml`，只修改run tag与单题filter；模型API、agent预算、arm与统一v3百题相同。沿用原shard_a的8000服务，runtime fingerprint为`a9f630cc0e46c9fbcb838ef54b1a34f86dcd50b2f93be51796fb7c8ba10c0d6c`；权重及关键部署参数已核验。chunk=100、M=4、K=2、L=131072、上下文133120、seed=20260916，不设置整题截止；继续使用第14.7节的新环境与共同prompt，不是与历史版本只差Conda激活的严格消融。

#### 真实测试反馈如何帮助改正补丁

1. 初始环境探针0.44秒，`status=ready`、errors为空。实际Python为`/opt/miniconda3/envs/testbed/bin/python`；Requests导入自`/testbed/requests/__init__.py`，pytest导入自testbed的Python 3.9环境。此前的MutableMapping导入问题未再阻止求解。
2. 第4轮直接调用真实`PreparedRequest.prepare()`，复现本题的非ASCII字节请求体`UnicodeDecodeError`。第6轮仍先选择修改公共`_encode_params`、让bytes直接返回，和上一轮失败思路相近。
3. **第8轮实际运行仓库pytest，发现`test_params_bytes_are_encoded`失败；第9轮单独重跑该测试确认TypeError。** 这正是上一轮官方判题中的回退测试；它本来就在原始checkout中，不依赖给agent注入隐藏评测补丁。
4. 模型据此区分请求体与URL查询参数：第17轮撤回公共编码函数修改，第19轮仅在`prepare_body`中对bytes请求体直接赋值，保留原有查询参数编码行为。
5. 第20轮对真实仓库再次执行复现及单项pytest，原回退测试变为`1 passed`；第27轮再次验证非ASCII字节请求体。最终官方判定1项目标测试与84项原有测试全部通过。

最终补丁只修改`requests/models.py`的请求体准备分支：`data`为bytes时直接作为body，否则仍调用原编码函数。它既不同于上一轮IS的错误补丁，也不要求逐字复现历史baseline的两处修改；官方测试确认本次方案有效。

**该题提供了具体的“真实项目可导入→实际测试发现回归→修改方案→官方通过”轨迹证据。** 它支持环境修复有实际价值，但不能由单次成功证明Consilience本身提高了准确率，也不能断言11道回退都能救回。两道修复后独立补跑目前为：django-14404未过、requests-2931通过；这些是按历史失败与耗时选择的样本，不是随机准确率评估，历史百题仍保持63/100。

#### 仍然存在的验证局限，不隐去

- 该镜像中`pip show pytest-httpbin`报告未安装，涉及httpbin的原仓库测试出现fixture递归依赖错误。模型完整运行`test_requests.py`得到**85 passed、1 xfailed、81 errors**；暂存补丁后对原始代码重跑，也得到同样数量。因此不能写成“原仓库全套测试全绿”或“所有依赖问题已解决”。
- 本题官方判分要求的1＋84项测试已经通过，官方报告没有基础设施异常；这与agent尝试更广测试集合时存在fixture错误并不矛盾。本次没有安装新依赖或修改测试配置，缺少fixture是后续独立待处理事项。
- 多条模型命令采用`pytest ... | tail`或`| grep`，未开启pipefail，因而shell返回码0时输出仍可能包含FAILED／ERROR／零测试选择。本次模型读取失败文本后进行了修正，但通用验收不能只看工具退出码。
- 较上一轮耗时明显增加，主要来自更多模型计算：API累计846.88秒，工具累计11.28秒，环境探针仅0.44秒。不能把增加约11分钟解释为Conda初始化变慢。

产物独立保存于`results/swebench/qwen38-thinking-is-c100-envfix-requests2931-20260923/`：`comparison.json`记录前后对照与未解决的fixture问题；源码／配置快照、trajectory、record、官方逐题日志及汇总报告均保留。本次没有补跑第三题，也没有覆盖历史百题成绩。

### 14.10 第三短回退题补跑：django-14771通过（2026-09-23）

用户随后批准再补跑一题，按上一轮IS耗时选择尚未补跑的`django__django-14771`，历史用时193.83秒，为11题中第三短。本次仍只启动一题Thinking IS，不运行新baseline，不变更采样或环境实现。

**官方结果：resolved=true；目标测试1/1、原有测试60/60通过，评测错误及基础设施异常均为0。** 2026-09-23 14:34:16启动，14:40:27完成整条流水线，约6分11秒；生成与评测退出码均为0，官方未报告未停止的容器。

| 指标 | 上一轮统一v3 IS | 环境修复后独立补跑 |
| --- | ---: | ---: |
| 官方resolved | false | **true** |
| runner耗时 | 193.83秒（3分14秒） | 267.86秒（4分28秒） |
| agent耗时 | 193.11秒 | 266.24秒 |
| 工具调用／交互轮数 | 25 | 26 |
| API请求／失败 | 133／0 | 174／0 |
| 全部候选与rollout输出 | 5,263 tokens | 7,854 tokens |
| 本次选中轨迹输出／选块步数 | — | 2,863 tokens／31步 |

配置：`configs/qwen38_swebench_thinking_is_envfix_django14771.toml`，只修改run tag与单题filter，使用原shard_b的8001服务。chunk=100、M=4、K=2、L=131072、上下文133120、seed=20260916、不限整题时间；服务部署参数与前次核验一致。开始前还比对了采样器、环境模块、适配器和runner的SHA-256，与前两次环境修复补跑一致，没有暗中修改方法。题目快照所有字段与历史baseline一致。

#### 为什么这次修对了

- 上一轮IS只把`None`视为无值选项，因而把实际值为`True`的开关错误拼成`-Xutf8=True`，官方`test_xoptions`未通过。
- 本次第7、8轮直接运行带`-X utf8`、`-X dev`和有值选项的Python命令，观察到无值选项在`sys._xoptions`中实际为**bool True**，有值选项为字符串，而不是只用自行设定的None做mock。
- 最终补丁在`django/utils/autoreload.py`里对`None`或`True`生成`-Xname`，其他值生成`-Xname=value`，同时保留`-W`参数。它不是上一轮失败补丁的重复提交。
- 第14轮直接调用真实`get_child_arguments()`，输出包含`-Xutf8`、`-Xdev`、`-Xint_max_str_digits=1000`及testbed解释器路径，验证了关键行为。
- 第23轮运行正确的项目测试入口`python tests/runtests.py utils_tests.test_autoreload`：**Ran 80 tests，OK，skipped=20**，即60项通过、20项跳过。最终官方判分所需的新增目标测试及60项原有测试也全部通过。

环境探针0.84秒、errors为空，Python为`/opt/miniconda3/envs/testbed/bin/python`，Django和测试runner均导入自`/testbed`。模型API累计251.26秒，实际工具执行8.63秒，耗时增长主要不在环境预检。

#### 仍需如实保留的过程问题

模型不是每一步都正确：曾写错`sys.xoptions`、尝试导入不存在的`repr`模块，以及设置无效的`-X int_max_str_digits`数值；这些是命令编写错误，不是Conda缺库。本次还先尝试pytest、错误的manage.py位置和测试模块名，之后才找到正确的Django原生runner。

该镜像没有pytest，但Django原生测试入口能够正常运行，**不应因此盲目安装pytest，也不能把所有“ImportError”都认定为环境初始化失败**。模型仍使用`| tail`，所以判定有效测试依据的是实际输出中的测试数量及OK结果、再加官方判题，而非单看shell返回码0。

#### 三道独立补跑小结

| 题目 | 历史baseline | 上一轮IS | 修复后独立补跑 | 本次runner耗时 |
| --- | --- | --- | --- | ---: |
| django-14404 | 通过 | 未过 | 未过 | 7分4秒 |
| requests-2931 | 通过 | 未过 | **通过** | 14分33秒 |
| django-14771 | 通过 | 未过 | **通过** | 4分28秒 |

目前是**3道历史回退题中恢复2道、仍失败1道**。这些题按已知失败和耗时选取，且修复包含共同prompt变化，不是随机样本或单因素因果实验；不能据此估计百题收益，也不是IS新增超过baseline的2道收益。历史百题仍保持baseline70/100、统一v3 IS63/100，不进行择优覆盖。

本题产物：`results/swebench/qwen38-thinking-is-c100-envfix-django14771-20260923/`，包含`comparison.json`、轨迹、record、源码及配置快照、官方评测日志和报告。没有自动启动其余8道回退题；Requests镜像的httpbin fixture问题也没有在本次被顺带修改。

### 14.11 两轮联合结果与环境修复后共同失败27题补跑（2026-09-23）

逐题核对官方评测后，历史混合版本69/100与完整v3的63/100共有59题通过，联合通过为 **73/100**，共同未通过 **27题**。若只比较未经9题补跑替换的原始完整v2（62/100）与完整v3（63/100），共有54题通过，联合通过为 **71/100**。两者都不是同版本独立重复采样的严格pass@2；近期三道环境修复单题补跑不计入这两个历史统计。

用户确认继续后，于 **2026-09-23 15:04:10（北京时间）** 启动共同失败27题的独立补跑。注意：这是两轮联合未通过的27题，**不是第二轮单独未通过的37题**。选题完全依据历史官方报告，未使用近期补跑结果排除题目，因此django-14404、requests-2931、django-14771也各重新运行一次，不复用此前补跑成绩。

| 项目 | 本次设置 |
| --- | --- |
| 方法 | Thinking Conditional IS＋Consilience；正文普通生成 |
| 采样参数 | M=4、K=2、chunk=100；temperature=1、top_p=1；seed=20260916 |
| 预算 | 整题累计选中输出L=131,072；上下文133,120；安全余量256 |
| 其他限制 | 每题不限时；250轮/工具调用上限；50,000次API请求上限；单次API超时1,800秒、重试0 |
| 双服务 | 8000 / GPU4–7：14题；8001 / GPU0–3：13题；每服务串行处理题目 |
| 修复范围 | 与最近三道单题验证相同的testbed环境激活、预检和共同prompt修复；未额外改变算法或安装fixture |
| 启动验证 | 两端preflight通过；34项相关测试通过；两分片manifest均为swebench-is-mh-v6 |
| 初始进度 | 两分片均已进入第一题模型采样：astropy-13236、astropy-14365；此时尚无官方判分 |

本批沿用固定排序交错分片，上一轮相同题目的runner累计耗时分别约4.92小时和4.41小时。据此暂估双服务生成及判题约 **5–7小时**，但这不是超时承诺；模型轨迹变化、长尾题或磁盘保护等待均可能延长。系统盘启动时仅余约4.5GiB，保留4GiB磁盘保护，不通过删除历史结果或降低保护阈值强行推进。

- 配置：`configs/qwen38_swebench_thinking_is_envfix_failed27.toml`。
- 固定题目清单：`configs/qwen38_swebench_thinking_is_envfix_failed27_instances.txt`。
- 选题证据：`configs/qwen38_swebench_thinking_is_envfix_failed27_selection.json`，含历史官方报告路径、SHA256、通过集及上一轮耗时。
- 后台入口：`experiments/swebench/run_envfix_failed27_dual_background.sh`；独立会话启动，脱离当前交互会话运行。
- 结果入口：`results/swebench/qwen38-thinking-is-c100-envfix-failed27-20260923-dual/`，实际写入`/data/users/jenkins/inference_scaling-results/qwen38-thinking-is-c100-envfix-failed27-20260923-dual/`。
- 运行代码：结果目录下的独立源码工作树与源码快照，包含未提交修复，避免当前工作目录后续修改影响本批；关键四模块SHA256与启动代码一致。
- 完成后各分片自动官方判题，成功结束后生成`summary.json`及逐题`case_timings.csv`。新增救回数以本批官方resolved为准，流程错误单独报告；不得据此覆盖历史百题成绩或宣称修复后的无选择百题通过率。

### 14.12 共同失败27题最终结果与后续流程修复

本机日志记录本批于 **2026-09-24 00:36:00（北京时间）** 正常完成：
`shard_a=0 shard_b=0 summary=0`。官方结果为 **8/27通过（29.63%）**、
16题测试未通过、2题空补丁、1题补丁应用错误。运行总墙钟约9小时32分钟，包含磁盘保护等待，
不能把这一数值直接作为模型推理耗时。单题agent平均约22分46秒、中位数约9分35秒。

通过题目：`django-11532`、`django-11848`、`django-14404`、`django-14771`、
`django-15973`、`requests-2931`、`sphinx-9711`、`sympy-17139`。

| 统计口径 | 最终值 | 含义 |
| --- | ---: | --- |
| 最近完整v3百题 | 63/100 | 历史单轮成绩不变 |
| 最近完整v3＋本次选择性补跑 | **71/100** | 63＋8；不是统一新协议的百题单轮成绩 |
| 历史混合69与完整v3的联合＋本次补跑 | **81/100** | 73＋8；是多轮累计覆盖，不是严格pass@2 |

两题空补丁为`pytest-10356`和`sympy-18211`，均耗尽250轮。
`django-10554`提交了73字节的解释性文本而非diff，官方无法应用；不能将其归因为评测机器故障，
也不能把生成阶段的`Submitted`视为已验证的有效补丁。

本批结束前后，工作目录另行完成四项保护修复，未修改本批冻结源码或历史结果：

1. 提交前检查git diff语法，空内容、解释性文本和损坏diff返回工具反馈，在原预算内允许纠正。
2. 工具shell启用pipefail，避免测试管道末端成功掩盖上游失败；仍需检查测试输出和组合命令行为。
3. 默认最后5轮提醒收尾，不切换IS采样、不延长预算；未提交终止默认最多10秒只读补丁审计，
   审计内容绝不替代正式答案。
4. Thinking IS采样明细分离为带SHA256引用的gzip文件，保留无损读取入口，避免主record反复承载GB级明细。

新协议为`swebench-is-mh-v7`/`swebench-testbed-v2`。211项回归测试通过，真实任务容器的
无模型调用验证通过；历史记录副本的压缩/还原校验通过，原文件未改动。
全目录ruff另发现既有`tests/test_swebench_pilot_split.py`的未使用导入，本次未修改该无关文件；
本次修改文件的ruff通过。详细行为、局限和复现方法见实验设计文档第13节。
当前未用v7启动新的模型解题实验，因此不能将上述8题救回归因于这些最新保护修复。

## 15. 最新完整100题对照（2026-09-24，含环境修复补跑）

**Baseline 70/100；最近完整v3 63/100；补跑合并后71/100。相对baseline：救回6题、回退5题，净差＋1个百分点。**

### 15.1 统计口径

固定同一100题。27题由历史混合69与完整v3共同失败集确定，不是完整v3的全部37道失败题。
合并表采用73条完整v3记录＋全部27条testbed-v1环境修复补跑记录（成功和失败全部替换），
不使用另三次单题验证、不使用历史混合版本中额外通过的题、不使用刚开发的v7保护代码。
因27题原v3均未通过，合并通过集恰为63＋8=71。v3未过但历史混合版本通过的另外10题未补跑，仍保留本轮失败结果。
这是选择性补跑后的混合协议对照，不是同版本重跑百题，也不是严格pass@2或同预算因果收益。
baseline仍为历史89＋11题合并70/100，不混入后来两题单独baseline补测。

| 指标 | Baseline | 完整v3 | 补跑合并后 |
| --- | ---: | ---: | ---: |
| 通过/100 | 70 | 63 | **71** |
| 与baseline共同通过 | — | 59 | **65** |
| baseline未过、IS通过 | — | 4 | **6** |
| baseline通过、IS未过 | — | 11 | **5** |
| 两者均未通过 | — | 26 | **24** |
| 相对baseline净差 | — | −7个百分点 | **＋1个百分点** |

合并后保留baseline成功65/70=92.86%，原失败救回6/30=20.00%。71题通过与70题通过的总数接近，但不是同一批成功题。
合并后失败分类：25题官方未通过、2题空补丁、2题评测错误，均计入固定100题分母。
评测错误为django-10554（本次）和sympy-22456（保留的v3），均是补丁应用失败，不是服务宕机。
空补丁为pytest-10356、sympy-18211，均为250轮耗尽。官方未通过类包含原报告可能标注的歧义失败，不自行改判。

### 15.2 救回与回退

**相对baseline救回6题：** `django__django-11532`、`django__django-11848`、`django__django-15525`、`matplotlib__matplotlib-24637`、`scikit-learn__scikit-learn-14894`、`sympy__sympy-17318`。

**相对baseline回退5题：** `astropy__astropy-13236`、`astropy__astropy-14508`、`django__django-13406`、`matplotlib__matplotlib-24570`、`sympy__sympy-18211`。

本次补跑救回8题中，django-11532、django-11848属于baseline未通过的新增成功；其余6题属于恢复baseline已有成功。
因此不能将8题全称为相对baseline的算法增益；相对baseline救回从4增至6、回退从11降至5。

### 15.3 耗时与成本

下表是runner时间，包含agent与少量初始化/保存开销，不包含官方判题、服务启动和磁盘等待。P90采用最近秩法。
“合并100条”只统计最终采用的记录；“实际127次”保留原100题和额外27次的全部花费，不能把被替换的失败成本抹掉。

| 指标 | Baseline100 | 完整v3百题 | 补跑27题 | 合并100条 | 实际127次IS尝试 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 累计runner小时 | 6.10 | 50.60 | 10.26 | 51.52 | 60.85 |
| 平均runner分钟 | 3.66 | 30.36 | 22.80 | 30.91 | 28.75 |
| 中位runner分钟 | 2.55 | 9.36 | 9.64 | 9.36 | 9.37 |
| P90 runner分钟 | 7.44 | 109.76 | 53.87 | 109.76 | 106.60 |
| 最长runner分钟 | 23.50 | 269.73 | 141.98 | 269.73 | 269.73 |
| agent超过30分钟次数 | 0 | 26 | 7 | 29 | 33 |
| API请求数 | 3,242 | 41,515 | 10,921 | 43,744 | 52,436 |
| 累计输入tokens | 44,007,454 | 763,261,363 | 242,289,909 | 893,550,605 | 1,005,551,272 |
| 累计输出tokens | 606,360 | 5,761,613 | 1,123,102 | 5,810,367 | 6,884,715 |
| 工具调用数 | 3,238 | 3,395 | 1,207 | 3,818 | 4,602 |
| API失败次数 | 1 | 0 | 0 | 0 | 0 |

API tokens包括候选和rollout，不等于接入主轨迹的L；整题L=131,072、上下文=133,120、M=4、K=2、chunk=100，正文普通生成，每题不限时。
本次27题双服务墙钟约9小时32分钟（9月23日15:04至9月24日00:36），包含约3小时磁盘等待；合并100条没有对应的一段统一实测墙钟。

### 15.4 全部100题逐题结果

时间列为该次runner分钟；补跑“—”表示未选入本次27题。合并使用所有补跑终态，不仅替换成功题。CSV另含最终采用记录耗时、总尝试耗时、API成本和逐题来源。

| # | instance_id | Baseline | 完整v3 | 本次补跑 | 合并结果 | 对照 | Base分钟 | v3分钟 | 补跑分钟 |
| ---: | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: |
| 1 | `astropy__astropy-12907` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 2.87 | 4.93 | — |
| 2 | `astropy__astropy-13236` | 通过 | 未通过 | 未通过 | 未通过 | 回退 | 1.09 | 4.56 | 3.40 |
| 3 | `astropy__astropy-14365` | 未通过 | 未通过 | 未通过 | 未通过 | 共同未过 | 1.76 | 3.51 | 2.49 |
| 4 | `astropy__astropy-14508` | 通过 | 未通过 | 未补跑 | 未通过 | 回退 | 5.23 | 8.62 | — |
| 5 | `astropy__astropy-14995` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 1.77 | 5.54 | — |
| 6 | `astropy__astropy-7671` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 2.89 | 6.37 | — |
| 7 | `astropy__astropy-8872` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 1.43 | 5.24 | — |
| 8 | `django__django-10554` | 未通过 | 未通过 | 评测错误 | 评测错误 | 共同未过 | 23.50 | 119.10 | 141.98 |
| 9 | `django__django-11099` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 0.50 | 0.97 | — |
| 10 | `django__django-11211` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 1.94 | 12.89 | — |
| 11 | `django__django-11477` | 未通过 | 未通过 | 未通过 | 未通过 | 共同未过 | 2.11 | 4.96 | 5.64 |
| 12 | `django__django-11532` | 未通过 | 未通过 | 通过 | 通过 | 救回 | 2.30 | 2.57 | 3.75 |
| 13 | `django__django-11603` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 1.37 | 3.38 | — |
| 14 | `django__django-11728` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 4.07 | 11.25 | — |
| 15 | `django__django-11848` | 未通过 | 未通过 | 通过 | 通过 | 救回 | 1.20 | 106.60 | 20.53 |
| 16 | `django__django-11951` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 0.40 | 0.86 | — |
| 17 | `django__django-11964` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 2.53 | 39.77 | — |
| 18 | `django__django-12155` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 2.41 | 3.17 | — |
| 19 | `django__django-12273` | 未通过 | 未通过 | 未补跑 | 未通过 | 共同未过 | 8.32 | 129.54 | — |
| 20 | `django__django-12325` | 未通过 | 未通过 | 未补跑 | 未通过 | 共同未过 | 4.04 | 15.76 | — |
| 21 | `django__django-12419` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 1.54 | 2.94 | — |
| 22 | `django__django-13195` | 未通过 | 未通过 | 未通过 | 未通过 | 共同未过 | 1.55 | 9.97 | 3.34 |
| 23 | `django__django-13212` | 未通过 | 未通过 | 未通过 | 未通过 | 共同未过 | 2.85 | 4.58 | 11.44 |
| 24 | `django__django-13279` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 2.96 | 8.32 | — |
| 25 | `django__django-13315` | 未通过 | 未通过 | 未补跑 | 未通过 | 共同未过 | 2.57 | 22.92 | — |
| 26 | `django__django-13346` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 4.85 | 109.76 | — |
| 27 | `django__django-13363` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 1.24 | 1.09 | — |
| 28 | `django__django-13406` | 通过 | 未通过 | 未通过 | 未通过 | 回退 | 6.21 | 62.93 | 29.98 |
| 29 | `django__django-13569` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 3.61 | 6.03 | — |
| 30 | `django__django-13658` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 0.36 | 1.16 | — |
| 31 | `django__django-13810` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 2.22 | 5.95 | — |
| 32 | `django__django-13837` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 4.55 | 23.05 | — |
| 33 | `django__django-14017` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 3.81 | 16.38 | — |
| 34 | `django__django-14089` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 0.39 | 0.70 | — |
| 35 | `django__django-14315` | 未通过 | 未通过 | 未通过 | 未通过 | 共同未过 | 0.57 | 1.84 | 4.49 |
| 36 | `django__django-14404` | 通过 | 未通过 | 通过 | 通过 | 共同通过 | 3.96 | 0.73 | 12.57 |
| 37 | `django__django-14493` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 3.61 | 2.12 | — |
| 38 | `django__django-14534` | 未通过 | 未通过 | 未通过 | 未通过 | 共同未过 | 2.86 | 14.83 | 3.10 |
| 39 | `django__django-14580` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 1.45 | 6.37 | — |
| 40 | `django__django-14771` | 通过 | 未通过 | 通过 | 通过 | 共同通过 | 2.19 | 3.23 | 3.60 |
| 41 | `django__django-15098` | 空补丁 | 未通过 | 未补跑 | 未通过 | 共同未过 | 2.48 | 157.40 | — |
| 42 | `django__django-15380` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 1.37 | 7.57 | — |
| 43 | `django__django-15382` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 10.87 | 78.23 | — |
| 44 | `django__django-15525` | 空补丁 | 通过 | 未补跑 | 通过 | 救回 | 3.77 | 65.59 | — |
| 45 | `django__django-15554` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 11.12 | 269.73 | — |
| 46 | `django__django-15695` | 未通过 | 未通过 | 未通过 | 未通过 | 共同未过 | 3.50 | 22.04 | 36.81 |
| 47 | `django__django-15973` | 通过 | 未通过 | 通过 | 通过 | 共同通过 | 2.69 | 18.53 | 8.57 |
| 48 | `django__django-16333` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 0.45 | 2.10 | — |
| 49 | `django__django-16662` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 2.14 | 3.10 | — |
| 50 | `django__django-16801` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 1.19 | 4.93 | — |
| 51 | `django__django-16938` | 未通过 | 未通过 | 未补跑 | 未通过 | 共同未过 | 3.37 | 8.72 | — |
| 52 | `django__django-17087` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 1.57 | 3.37 | — |
| 53 | `django__django-9296` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 0.55 | 1.74 | — |
| 54 | `matplotlib__matplotlib-13989` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 1.67 | 9.35 | — |
| 55 | `matplotlib__matplotlib-20676` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 2.68 | 15.00 | — |
| 56 | `matplotlib__matplotlib-20826` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 17.61 | 111.09 | — |
| 57 | `matplotlib__matplotlib-23476` | 未通过 | 未通过 | 未通过 | 未通过 | 共同未过 | 3.69 | 25.47 | 50.86 |
| 58 | `matplotlib__matplotlib-24570` | 通过 | 未通过 | 未补跑 | 未通过 | 回退 | 1.95 | 42.62 | — |
| 59 | `matplotlib__matplotlib-24637` | 未通过 | 通过 | 未补跑 | 通过 | 救回 | 4.58 | 16.70 | — |
| 60 | `matplotlib__matplotlib-25332` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 6.61 | 13.99 | — |
| 61 | `matplotlib__matplotlib-25960` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 7.83 | 118.45 | — |
| 62 | `matplotlib__matplotlib-26291` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 2.58 | 14.69 | — |
| 63 | `matplotlib__matplotlib-26466` | 未通过 | 未通过 | 未通过 | 未通过 | 共同未过 | 2.89 | 12.58 | 3.91 |
| 64 | `pallets__flask-5014` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 1.01 | 1.13 | — |
| 65 | `psf__requests-2931` | 通过 | 未通过 | 通过 | 通过 | 共同通过 | 2.99 | 3.14 | 14.26 |
| 66 | `pydata__xarray-6599` | 未通过 | 未通过 | 未补跑 | 未通过 | 共同未过 | 8.22 | 109.95 | — |
| 67 | `pydata__xarray-6938` | 未通过 | 未通过 | 未通过 | 未通过 | 共同未过 | 2.40 | 14.00 | 17.75 |
| 68 | `pydata__xarray-7393` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 2.17 | 3.44 | — |
| 69 | `pytest-dev__pytest-10356` | 未通过 | 未通过 | 空补丁 | 空补丁 | 共同未过 | 6.46 | 38.35 | 53.87 |
| 70 | `pytest-dev__pytest-5787` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 7.00 | 22.10 | — |
| 71 | `pytest-dev__pytest-7236` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 2.45 | 13.18 | — |
| 72 | `scikit-learn__scikit-learn-11310` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 1.36 | 5.10 | — |
| 73 | `scikit-learn__scikit-learn-14894` | 空补丁 | 通过 | 未补跑 | 通过 | 救回 | 0.97 | 2.37 | — |
| 74 | `scikit-learn__scikit-learn-25102` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 12.78 | 42.04 | — |
| 75 | `scikit-learn__scikit-learn-25931` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 3.23 | 4.05 | — |
| 76 | `sphinx-doc__sphinx-10614` | 未通过 | 未通过 | 未补跑 | 未通过 | 共同未过 | 7.44 | 190.24 | — |
| 77 | `sphinx-doc__sphinx-11445` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 2.83 | 39.74 | — |
| 78 | `sphinx-doc__sphinx-7454` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 4.87 | 5.06 | — |
| 79 | `sphinx-doc__sphinx-7889` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 1.28 | 44.23 | — |
| 80 | `sphinx-doc__sphinx-8548` | 未通过 | 未通过 | 未通过 | 未通过 | 共同未过 | 16.37 | 27.70 | 99.68 |
| 81 | `sphinx-doc__sphinx-8551` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 2.04 | 41.14 | — |
| 82 | `sphinx-doc__sphinx-8721` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 3.80 | 22.22 | — |
| 83 | `sphinx-doc__sphinx-9258` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 4.22 | 9.37 | — |
| 84 | `sphinx-doc__sphinx-9658` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 4.51 | 35.75 | — |
| 85 | `sphinx-doc__sphinx-9673` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 1.87 | 50.51 | — |
| 86 | `sphinx-doc__sphinx-9711` | 通过 | 未通过 | 通过 | 通过 | 共同通过 | 2.43 | 3.49 | 2.42 |
| 87 | `sympy__sympy-13372` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 1.26 | 2.24 | — |
| 88 | `sympy__sympy-13615` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 3.31 | 53.57 | — |
| 89 | `sympy__sympy-14711` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 1.35 | 4.72 | — |
| 90 | `sympy__sympy-15976` | 未通过 | 未通过 | 未通过 | 未通过 | 共同未过 | 3.95 | 10.45 | 9.64 |
| 91 | `sympy__sympy-16597` | 未通过 | 未通过 | 未通过 | 未通过 | 共同未过 | 2.30 | 7.88 | 34.04 |
| 92 | `sympy__sympy-17139` | 通过 | 未通过 | 通过 | 通过 | 共同通过 | 0.82 | 3.37 | 4.97 |
| 93 | `sympy__sympy-17318` | 未通过 | 通过 | 未补跑 | 通过 | 救回 | 2.05 | 45.39 | — |
| 94 | `sympy__sympy-18211` | 通过 | 未通过 | 空补丁 | 空补丁 | 回退 | 2.41 | 28.21 | 31.25 |
| 95 | `sympy__sympy-18763` | 未通过 | 未通过 | 未通过 | 未通过 | 共同未过 | 1.27 | 5.47 | 1.23 |
| 96 | `sympy__sympy-20801` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 3.86 | 6.08 | — |
| 97 | `sympy__sympy-21847` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 0.85 | 5.56 | — |
| 98 | `sympy__sympy-22456` | 空补丁 | 评测错误 | 未补跑 | 评测错误 | 共同未过 | 12.09 | 132.25 | — |
| 99 | `sympy__sympy-22914` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 0.68 | 1.73 | — |
| 100 | `sympy__sympy-23413` | 通过 | 通过 | 未补跑 | 通过 | 共同通过 | 5.10 | 183.02 | — |

### 15.5 来源与复核

- 原完整百题：`results/swebench/qwen38-thinking-is-random100-v3-unlimited-dual-20260922-r1/`。
- 本次27题：`results/swebench/qwen38-thinking-is-c100-envfix-failed27-20260923-dual/`。
- 机器可读100行表：`results/analysis/swebench-random100-envfix-20260924/paired100.csv`。
- 汇总与官方报告SHA256：`results/analysis/swebench-random100-envfix-20260924/summary.json`。
- 可复核生成脚本：`results/analysis/swebench-random100-envfix-20260924/build_report.py`。
- 逐题baseline通过状态已与两个原官方报告核对，完整v3和补跑通过状态已与官方报告、case_timings交叉核对。
- 两次历史联合＋本次补跑为81/100，仅作多轮累计覆盖参考，不混入本节71/100主表。
- 新v7提交/收尾/pipefail/压缩保护尚未用于新的模型解题实验，本节收益不得归因于这些后续修复。

### 15.6 最终5道回退题的最新逐题归因

以下依据第15.4节每题**最终采用的记录**、对应轨迹、baseline补丁及官方逐题报告复核。
不能直接沿用第14.2节旧v3归因：Django13406和SymPy18211在本次补跑的失败方式已改变。

**选题边界：5题中只有3题进入了本次27题环境修复补跑。** Astropy14508和Matplotlib24570在历史
混合69结果中曾通过，因此不属于“两轮共同失败”的27题。本表对这两题保留最新完整v3的旧失败，
不是证实环境修复无效，更不能声称它们已经用最新v7验证过。

| 题目 | 最终来源与耗时 | 官方直接失败原因 | 补丁与轨迹证据 |
| --- | --- | --- | --- |
| astropy-13236 | 环境修复补跑，3.40分钟 | 2个FAIL_TO_PASS失败：`test_ndarray_mixin[False]`、`test_structured_masked_column` | 目标是移除结构化数组自动变为NdarrayMixin的行为；IS只添加弃用warning，仍保留`data.view(NdarrayMixin)`。baseline直接移除该转换。补跑实际成功导入Astropy并调用真实Table，但自写验证只断言warning出现，验证了自己实现的行为而非要求的行为，未执行项目测试。 |
| astropy-14508 | 完整v3旧结果，8.62分钟；未补跑 | 1个PASS_TO_PASS失败：`test_invalid_float_cards2` | IS用`str(value)`，只在长度超过20的回退分支处理指数格式；短字符串的科学计数法可能保留小写`e`，破坏FITS格式。baseline在短字符串路径也转为大写`E`。旧轨迹导入缺少erfa，随后抽出函数自测，没有跑真实项目测试。 |
| django-13406 | 环境修复补跑，29.98分钟 | 3个FAIL_TO_PASS及3个PASS_TO_PASS失败 | 本次IS不是旧版的iterable保存方案，而是在`Query.__getstate__`里对`values_select`和组合查询直接抛`PicklingError`，把“恢复后应返回正确字典”改成“禁止序列化”。baseline在QuerySet的query setter按values_select恢复ValuesIterable。补跑跑了`queries.tests`及普通查询子集，却未覆盖真正相关的`queryset_pickle`契约，误以为普通测试通过就代表正确。 |
| matplotlib-24570 | 完整v3旧结果，42.62分钟；未补跑 | 2个FAIL_TO_PASS失败：`test_packers[bottom]`、`test_packers[top]` | IS仅在HPacker局部交换top/bottom，未修复公共对齐逻辑及VPacker相关行为；baseline修改公共`_get_aligned_offsets`。旧轨迹缺matplotlib/numpy，转而用简化函数自测，遗漏真实打包器行为。 |
| sympy-18211 | 环境修复补跑，31.25分钟 | 达到250轮`agent_step_limit`，正式submission为空 | 当前不是旧v3的内部符号泄漏补丁，而是没有交卷。轨迹反复查找求解器及测试入口，尝试当前checkout不存在的`sympy.testing`、缺失的pytest与安装操作，最终仍在查看源码。baseline在等式不能直接求解时返回ConditionSet，并正确恢复原符号。正确激活testbed并不保证模型能找到该旧版本的正确测试入口。 |

Django13406的3个目标失败为`test_annotation_values`、`test_annotation_values_list`、
`test_annotation_with_callable_default`；3个原有功能回归为`test_in_lookup_query_evaluation`、
`test_pickle_subquery_queryset_not_evaluated`、`test_specialized_queryset`。
这说明它不是只遗漏某个隐藏边界，而是直接破坏了应保留的序列化能力。

**综合判断：** 当前5题可拆成2题旧环境下未复测、2题需求语义/验证目标错误、1题预算耗尽无提交。
这些证据说明“更多thinking＋自洽奖励”不保证补丁正确，也不能据此证明核心IS权重或logprob计算有错；
若要追究候选选择是否导致退化，还需要独立审计同一节点的候选与最终行为，不能由最终失败倒推算法实现错误。

**建议的后续验证，不自动启动：** 优先用统一v7协议补跑尚未验证的Astropy14508和Matplotlib24570；
对Astropy13236、Django13406重点观察是否按需求保留/改变正确的行为并选择相关测试；对SymPy18211观察
5轮收尾提醒能否避免空提交，同时确认旧版本正确的原生测试入口。不能把baseline补丁或官方隐藏测试答案
注入agent来制造通过。提交校验和pipefail能减少流程错误，但不会自动纠正语义错误或保证这5题全部救回。

## 16. 第二轮完整Baseline已启动（2026-09-24）

北京时间2026-09-24 11:27:50启动，固定原100题，不重新抽样、不复用旧补丁。
本轮只运行Baseline，无Conditional IS或Consilience；两个服务各串行处理50题。

| 项目 | 本轮设置 |
|---|---|
| 模型与服务 | 原Qwen3.8-27B服务；8000/GPU4–7，8001/GPU0–3 |
| 题目清单 | `configs/qwen38_swebench_random100_instances.txt`，排序后交替分片 |
| seed / temperature / top_p | `20260924 / 1.0 / 1.0` |
| 整题累计完整输出L / 单轮上下文 | `131072 / 133120` tokens，上下文安全余量256 |
| 单次输出请求上限 | 131072，并受剩余整题预算与本轮上下文空间动态约束 |
| 轮数 / 工具调用上限 | `250 / 250` |
| 整题墙钟限制 | 不设置；单次API超时1800秒，API重试0次 |
| 当前运行保护 | 环境激活与预检、提交补丁语法校验、pipefail、剩余5轮收尾提醒、10秒退出审计 |
| 源码 | HEAD `4c93169a7f221de2f1ed01863df4bf23afcadadc` 加启动时工作区源码；包括已有独立reasoning兼容改动 |
| 配置 | `configs/qwen38_swebench_random100_baseline_second_20260924.toml` |
| 后台入口 | `experiments/swebench/run_baseline_random100_second_dual_background.sh` |
| 结果目录 | `results/swebench/qwen38-baseline-random100-second-v7-20260924-dual`，软链接到数据盘 |

已保存源码快照、工作区diff、HEAD、配置与输入SHA256、依赖版本及固定分片。
两路预检均为ok；首题分别为`astropy__astropy-12907`与`astropy__astropy-13236`。
启动器为独立后台会话，不依赖当前聊天连接；两路分别生成，官方评测使用锁串行执行，
完成后汇总`summary.json`与`case_timings.csv`。磁盘可用空间低于4 GiB时暂停等待，不能保证无人干预一定完成。

预计约4–6小时，仅依据旧Baseline累计runner耗时6.10小时及双服务分片估算；
本轮运行保护已变更、无整题超时，长尾题和磁盘等待可能延长耗时，当前没有新通过率结论。
配置与分片检查通过，相关配置/双服务测试31项通过。

最终应分别统计本轮单次通过率、原Baseline70题通过集合与本轮的并集、两轮共同通过/各自独有通过，
并对照修复后两轮IS的并集81/100。
这里的“两次至少一次通过”是观察到的集合覆盖率；旧Baseline由原始运行和11题兼容修复重跑合并，
IS两轮也包含选择性修复重跑，且本轮使用统一v7保护，因此不能称为同协议、严格等预算的pass@2对照。

### 16.1 第二轮Baseline最终结果

2026-09-24 17:04:08全部完成，生成、评测与汇总退出码均为0；从启动计墙钟耗时5小时36分18秒。
A路35/50通过，B路39/50通过，合计74/100；25题测试未通过，1题
`sympy__sympy-22456`触发250轮上限且无提交。API失败和官方评测执行错误均为0。
平均runner耗时4.29分钟，中位数2.54分钟，最长30.50分钟。

| 固定100题对照 | 第一轮 | 第二轮 | 两轮至少一次通过 |
|---|---:|---:|---:|
| Baseline | 70 | 74 | 79 |
| Thinking IS（历史修复合并口径） | 69 | 71 | 81 |

两轮Baseline共同通过65题，本轮新增通过9题、回退5题、共同未通过21题。
两轮IS并集较Baseline并集多2题；IS独有通过7题，Baseline独有通过5题。
上述并集为描述性覆盖率，不代表同协议、等预算下的严格pass@2估计。

## 17. Rebase后完整Thinking IS百题（2026-09-26，运行中）

北京时间2026-09-26 14:36:30启动新一轮完整100题，不重新抽样、不复用旧补丁，
不替换历史两轮结果。使用当前SWE-bench适配器的分块Conditional IS，正文普通生成；
不是切换为上游其他动态预算算法。本轮保持此前IS的seed，主要观察当前修复后完整流程，
不宣称是新增独立seed试验。

| 项目 | 本轮冻结设置 |
|---|---|
| 源码 | `cdf857bb799461e43148861da8ca781762cd142f`＋启动时工作区，已包含rebase后的Consilience接口兼容改动 |
| 上游基线 | `9b1db76` |
| 模型/服务 | 原Qwen3.8-27B；8000/GPU4–7与8001/GPU0–3，各串行50题 |
| 题目 | `configs/qwen38_swebench_random100_instances.txt`，原100题排序交替分片 |
| 方法 | thinking Conditional IS＋Consilience；正文普通生成 |
| chunk / M / K_rollout | `100 / 4 / 2` |
| Consilience | top-5，skip=0.05，window=0.2，initial_penalty=3；奖励温度2，仅评分thinking段 |
| seed / temperature / top_p | `20260916 / 1.0 / 1.0` |
| 整题累计选中输出L / 上下文 / 安全余量 | `131072 / 133120 / 256` tokens；L包含thinking与正文，不是所有候选/rollout的总消耗 |
| 轮数 / 工具次数 | `250 / 250` |
| 整题时限 / API超时 / 重试 | 不设整题时限；1800秒/次；重试0次 |
| 运行保护 | v7环境预检、提交语法校验、pipefail、剩余5轮收尾提醒、10秒退出审计；零thinking修复 |
| 配置 | `configs/qwen38_swebench_thinking_is_random100_rebased_v7_20260926.toml` |
| 后台脚本 | `experiments/swebench/run_thinking_is_random100_rebased_v7_dual_background.sh` |
| 结果 | `results/swebench/qwen38-thinking-is-c100-random100-rebased-v7-20260926-dual`，链接至数据盘 |

已保存HEAD、工作区diff、完整源码快照、配置/清单/关键模块SHA256、依赖版本、固定分片。
上游Consilience构造器改为`scope="full"`仅为使用已截出的thinking置信度轨迹计算分数；
SWE适配器仍在调用轨迹评分前切除正文，没有扩大到正文奖励。
237项SWE-bench测试通过；两个服务真实预检均确认exact token prefix与top-5 logprobs，
首题`astropy__astropy-12907`和`astropy__astropy-13236`已产生IS选择事件。

采用独立后台会话，聊天断开不影响进程；每片生成结束后自动官方评测，评测串行加锁，
最终生成`summary.json`和`case_timings.csv`。历史完整IS墙钟约29.1小时、累计runner约50.6小时，
本轮初步按24–36小时估计；无整题时限，长尾和磁盘等待均可能延长。
启动前系统盘仅余约5.1 GiB、数据盘约41 GiB，低于4 GiB时暂停等待，不自动删除其他数据。
当前仅确认成功启动，尚无本轮百题通过率。

### 17.1 人工跳过django-10554（2026-09-27）

用户要求停止并跳过`django__django-10554`。已仅暂停、终止原B路工作进程，
归档该题容器信息、当前tracked diff、11个未跟踪复现/调试脚本和此前B路日志，
随后清理该题专属容器；A路及两个模型服务均未停止或重启。
归档目录：`results/swebench/qwen38-thinking-is-c100-random100-rebased-v7-20260926-dual/interventions/skip-django10554-20260927`。

**续跑和统计：** 原B路已提交3题保留，目标题写入明确的`status=cancelled`、
`exit_status=user_requested_skip`、空提交记录，百题分母不变，最终按未解决计入。
剩余46题沿用原冻结源码、配置、分片和输出路径续跑，已确认下一题`django__django-11211`
产生IS选择事件。原代码没有单题取消接口，因此采用归档的独立恢复入口，只允许跳过与
人工取消凭证完全匹配的该条记录；没有改写采样算法或原源码快照。

原启动器的B路退出非零是本次人工终止的预期结果；后续应检查归档目录内
`recovery_exit.txt`和结果根目录`recovery_pipeline_exit.txt`，而不是只看原`pipeline_exit.txt`。
恢复入口会在B路完成后自动官方评测，等待原A路结束，再汇总100题结果。

**现场证据和初步分析：**

- 暂停时记录到第73轮、345次已完成的IS分块选择；最长一轮22步。
  每步最多4个候选短块及8次rollout，rollout不是100-token短块，其上限为本轮剩余生成预算。
  因此分块选择次数远大于agent轮数，慢不是单纯的“73次模型调用”。
- 整题30分钟限制已取消，也未启用单轮IS时限或独立rollout长度上限；250轮尚未用完，
  而131072约束选中轨迹，不包含所有被丢弃的候选/rollout算力，故无法限制实际耗时。
- 现场tracked diff为0字节，仅有11个复现/调试脚本。题目描述涉及排序后的union查询与派生
  queryset互相影响；脚本多次使用SQLite并手动开启数据库特性标志，试图模拟原始报错场景。
  这支持“复现/定位阶段长时间未收敛”的判断，但不能凭最终工作区断言之前从未编辑或回退过源码。
- 345次选择的ESS均值约3.38/4，其中128次高于3.8。部分步骤候选权重接近均匀，
  Consilience并不验证需求是否满足或测试是否通过，因此不能自动识别这种低进展探索。
- 停止前模型服务持续返回成功响应，没有排队；这是持续消耗推理资源的长尾，不是已证实的死锁。

**审计限制：** 运行中完整trajectory和候选诊断只在内存，终止旧进程无法恢复完整API/token计数；
这些字段如实标记为null，而不是0。约616.6分钟的耗时使用容器启动至02:02:20现场时间近似计算，
包括少量暂停取证时间；`agent_seconds`未知。后续资源总量不能声称覆盖这一题的全部实际消耗。
本次是明确记录的人工干预，本轮不能再称为完全无人干预的统一协议百题运行。

### 17.2 本轮最终结果（2026-09-28）

截至2026-09-28 09:02:39，两路官方判分全部完成；从2026-09-26 14:36:30启动计，
生成及判分墙钟耗时42小时26分09秒。

| 指标 | 最终结果 |
|---|---:|
| 本轮Thinking IS通过率 | **67/100（67%）** |
| A路 | 33/50 |
| B路 | 34/50 |
| 测试未通过 | 32题 |
| 人工跳过、计为未解决 | 1题（django-10554） |
| 正常提交 | 99题 |
| 官方评测执行错误 | 0 |
| 有完整记录的99题API失败 | 0；跳过题未知 |

此前第一/第二轮Baseline分别70%、74%，历史修复合并后的第一/第二轮IS分别69%、71%。
本轮67%较第二轮Baseline低7个百分点，较历史第二轮修复合并IS低4个百分点。
逐题对照第二轮Baseline，本轮救回7题、回退14题；对照历史第二轮合并IS，
本轮新增通过9题、回退13题。因此本轮未体现单轮准确率提升，且存在明显长尾耗时。
不同代码/修复合并方式、seed及本轮人工跳过均须保留说明，不能将这些数字当作严格控制变量结论。

**后处理说明：** 官方报告先已成功保存，随后旧`evaluation_summary.py`尝试将人工取消题的
未知token计数`null`转换为整数，导致原恢复脚本退出1；这是汇总错误，不是官方评测失败。
2026-09-28 10时补执行独立汇总，已生成结果根目录`summary.json`、`case_timings.csv`及
`recovery_pipeline_exit.txt`，没有重跑模型或测试，也没有把未知token计数伪填为0。
原错误日志保留；最终结果以两路官方报告和恢复后的汇总为准。

### 17.3 第三轮IS对第二轮Baseline：7题救回、14题回退诊断

2026-09-28只读核查双方官方报告、最终补丁、agent轨迹和IS候选诊断，没有重跑模型、执行新评测或修改采样代码。
比较源为`qwen38-baseline-random100-second-v7-20260924-dual`与
`qwen38-thinking-is-c100-random100-rebased-v7-20260926-dual`两个结果目录；
逐题证据在各自`record.json`、`trajectory.json`和官方评测目录的`report.json`、`test_output.txt`。

**首先排除误归因。** 两轮共同通过60题，仅Baseline通过14题，仅IS通过7题，共同未通过19题。
14个回退题全部`Submitted`、补丁成功应用、官方`infra_failure=false`，并非空thinking拒绝、
响应重建、补丁应用失败、轮数/长度耗尽或人工取消。其IS轮数范围14–201，累计选中输出均低于L。
人工跳过的django-10554在第二轮Baseline也未通过，不属于这14题，不能解释净下降7个百分点。

两份冻结源码中的`miniagent.py`、`baseline.py`、`task_environment.py`、`runner.py`逐字相同；
IS接口兼容改动为Consilience导入路径和构造参数，thinking边界截取逻辑未变。
主要实验配置差异为方法和seed（Baseline=20260924，IS=20260916），没有整题30分钟限制。
所以本轮有实际补丁质量退化，但不能仅凭这次不同seed的结果断言“IS机制必然降低7个百分点”，
更不能将所有退化归因于rebase破坏了环境或提交流程。

#### 14个回退题：逐题证据

| 题目 | 本轮IS与成功Baseline的关键差异 | 官方失败证据/解释 |
|---|---|---|
| astropy-13236 | Baseline删除结构化数组自动转NdarrayMixin；IS只增加FutureWarning，仍保留转换 | `test_ndarray_mixin[False]`、`test_structured_masked_column`失败；只提示未来修复，没有改变目标行为 |
| django-11728 | IS只修命名捕获组；Baseline同时修命名与非命名组 | `test_simplify_regex`的尾部非命名组仍输出`(\\w+)`而非`<var>`；修复不完整 |
| django-11848 | Baseline使用`datetime.utcnow`；IS换为`time.strftime`取当前年份 | 官方用mock冻结datetime，未冻结time；出现2070/2071与预期1970/1971不符。属于时钟接口/测试契约敏感案例，不宜简单判为完全不会处理年份 |
| django-12273 | Baseline在设置pk时同步父链接；IS在保存阶段增加`self._state.adding`条件 | 清空pk创建新实例和多重继承测试失败；修改了错误阶段，未正确同步父子主键 |
| django-13406 | Baseline恢复为ValuesIterable；IS额外保存并恢复原values_list类型 | 官方期望字典，得到tuple、标量或namedtuple；额外设计改变了应保持的返回约定 |
| django-14771 | IS将`sys._xoptions.items()`排序，Baseline保留原顺序 | `test_xoptions`只显示`-Xa=b`与`-Xutf8`顺序不一致；属于顺序契约，不等价于-X参数丢失 |
| matplotlib-20826 | IS通用保存/恢复tick可见性；Baseline采用另一种clear处理 | 目标FAIL_TO_PASS全部通过，但`test_markevery_polar[png/pdf]`回归；修好了原问题却破坏已有行为 |
| matplotlib-25332 | Baseline让Grouper可序列化；IS在pickle时删除对齐组、恢复时重建空组 | `test_complete[png]`失败；消除了弱引用报错，却丢失对齐状态 |
| matplotlib-25960 | IS直接使用GridSpec位置生成子图bbox；Baseline计算父图归一化间距 | `test_subfigures_wspace_hspace`出现边界`[80,278.4]`与`[0,288]`不符；位置/边距参照处理不正确 |
| sphinx-7454 | Baseline修Python域注解生成；IS仅放宽intersphinx解析 | `test_parse_annotation`失败；绕到下游补救，未修正确节点类型 |
| sphinx-9258 | Baseline修Python域type字段拆分；IS修Napoleon的NumPy风格解析 | `test_info_field_list_piped_type`失败；修错模块，目标路径未覆盖 |
| sympy-15976 | Baseline修MathML节点嵌套；IS把尾随数字改为普通文本而非下标 | `test_presentation_symbol`失败；改变符号显示约定，没有修根本结构问题 |
| sympy-17318 | Baseline在_sqrt_match中拒绝不适用输入；IS在split_surds中补默认返回 | `_sqrt_match(4 + I) == []`断言失败；兜底值改变了上层匹配契约 |
| sympy-23413 | Baseline修HNF遍历行数；IS改为记录并提取主元列，仍保留旧行数限制 | `test_hermite_normal`等失败；没有修掉漏遍历行的根因 |

注：Django11728的官方报告还列出一个PASS_TO_PASS失败，但原始日志存在并行测试输出拼接；
本分析以明确可复核的非命名组断言失败为主要依据，不将该额外项当作已确认的功能回归。
Matplotlib20826评测输出中还有非目标集合的失败，本文只使用官方判定所需的两个polar回归。

#### 验证为何没有拦住错误

- **错入口/零测试：** Django11728先遇到pytest缺失，再把`admin_docs`测试模块写成`admindocs`，
  还出现`Ran 0 tests ... OK`；最终只验证命名组。SymPy23413多次原生test runner调用显示
  `0 passed`甚至返回True，却没有实际跑到相关测试。解释器激活修复并不能自动保证测试入口和收集数量正确。
- **测错模块：** Sphinx9258运行Napoleon测试得到48 passed，但题目需要Python domain字段解析，
  这些通过不能证明目标功能正确。Sphinx7454修改intersphinx而不是注解构造，验证同样偏离根因。
- **修复有效但覆盖不足：** Matplotlib20826确实做了多轮验证，包括95 passed、81 passed的筛选测试；
  完整较大测试曾被工具60秒超时打断，后续筛选漏掉polar回归。不能将它说成完全没有测试。
- **旧测试通过不代表新契约覆盖：** Django11848在agent环境跑旧有45项测试成功，官方新增的冻结年份用例仍失败。
  Django14771的额外排序也未被本地验证发现。这两题尤其应区分功能语义错误与严格测试契约差异。

**剩余流程薄弱点：** 当前提交保护检查的是补丁语法，不是“已成功运行多少相关测试”。
系统提示虽要求区分0测试、依赖失败和真实通过，但并未程序化强制验证证据，错误测试入口仍可能被agent忽略。
这不是零thinking处理再次失败，也不是完整评测崩溃；是验证能力不足导致错误补丁正常提交。

#### 7个救回题：同样存在真实收益

| 题目 | Baseline失败与IS成功的差异 |
|---|---|
| django-14534 | Baseline在缺少id时仍回退生成旧id；IS直接使用widget提供的id，避免错误兜底 |
| django-16938 | Baseline只修改Python序列化器且改变迭代值类型；IS同时修Python/XML路径并解除select_related与only冲突 |
| matplotlib-20676 | Baseline尝试恢复dataLim；IS直接以当前坐标轴边界初始化SpanSelector手柄，修到触发源 |
| matplotlib-24570 | Baseline只在HPacker局部互换top/bottom；IS修共享_get_aligned_offsets，对齐行为覆盖更完整 |
| sphinx-11445 | Baseline依赖后续标题下划线启发式；IS修docinfo识别正则，区分字段与域角色标题 |
| sympy-13615 | Baseline改Interval层判断；IS在通用有限集合补集中区分确定属于、不属于与未知成员关系 |
| sympy-22456 | Baseline耗尽250轮、无补丁；IS在105轮提交并通过，修String参数不变性及相关遍历。此题是无提交到有效解答的恢复，不是两个已提交补丁的纯语义对比 |

#### 为什么更多thinking没有稳定变好

| 14个回退题合计 | Baseline第二轮 | IS第三轮 |
|---|---:|---:|
| runner耗时 | 104.18分钟 | 448.64分钟（约4.31倍） |
| API请求 | 725 | 8308（约11.46倍） |
| 累计生成输出tokens，含候选/rollout | 159349 | 802903（约5.04倍） |
| 最终选中轨迹输出tokens | 159349 | 141192 |

因此更多计算主要花在被丢弃的候选/rollout，而不是必然形成更完整的最终推理。
Consilience只依据thinking的top-K置信度轨迹，不执行候选工具动作、不检查需求覆盖或补丁正确性，
它可以偏好一个流畅但错误的诊断方向。错误方向一旦接入前缀，后续动作和自测可能继续围绕它展开；
Sphinx两题和Astropy13236提供了最终方向偏离的具体证据。
但本分析没有对同一节点的所有未选中候选做反事实执行，因此不能断言这些错误一定由某次奖励选择直接造成。

回退题SymPy17318的201次选择平均ESS约3.79/4，说明其中候选区分较弱；
14个回退题里11题从未触发`empty_thinking_uniform`，因此不能把全部退化归咎于零thinking的均匀选择策略。
另3题存在该合法分支，也没有证据显示适配异常或截断导致失败。

**改进优先级（尚未实施）：**
1. 先补测试执行证据：记录原生runner、收集数、成功/失败/超时，0测试和导入错误不得标为验证成功；
   对有公开原生测试的项目提供可靠入口，不向agent注入官方隐藏测试或参考补丁。
2. 选取上述差异题做受控诊断：固定代码、题目、采样设置，用多个预登记seed同时跑两组；
   开发集上的修复需再用完整固定100题验证，不能把选择性救回当作新的无偏总分。
3. 把Consilience与“测试是否实际覆盖目标”的反馈分开记录，再单独设计消融，避免直接改奖励后声称有效。
4. 另设候选/rollout总计算预算或单轮保护来控制长尾；这属于效率方案，不能保证修复准确率下降。

### 18. 冻结源码对齐的第三轮Baseline（2026-09-28）

对照第三轮IS的冻结源码快照`cdf857bb`及其未提交工作树归档，保持同一100题清单、
两台模型服务及运行时指纹、mini-swe-agent配置、seed=`20260916`和全部时间/上下文限制。
配置仅变更实验tag和采样方法：`is_thinking`（M=4、K=2、chunk=100）改为
`base`（chunk=131072）；协议与快照哈希见
`results/swebench/qwen38-baseline-random100-aligned-is3-v7-20260928-dual/protocol.json`。
源目录及官方报告保存在同一结果目录（结果文件位于数据盘，仓库路径是软链接）。

| 对齐结果 | Baseline | 第三轮IS |
|---|---:|---:|
| 通过/100 | **69** | **67** |
| 单轮通过率 | **69%** | **67%** |
| 官方评测错误 | 0 | 0 |
| 正常提交 | 100 | 99（另1题人为跳过，按未通过计） |
| 累计输出tokens（含IS的全部候选/rollout） | 640020 | 6237225（99题有记录） |
| API请求 | 3512 | 43531（99题有记录） |

逐题：共同通过59题、仅IS通过8题、仅Baseline通过10题、共同未通过23题。
Baselines第三轮新通过3题（`django__django-12325`、`sympy__sympy-16597`、
`sympy__sympy-22456`）。历史三轮合并覆盖率：Baseline **82/100**（单轮70/74/69），
Thinking IS **84/100**（单轮69/71/67）；第一、二轮包含修复补跑，不属于同协议的
严格pass@3估计。对齐Baseline总批次耗时4小时37分14秒，单题agent用时均值236.06秒，
中位数131.42秒，最大1681.51秒，100题无推理错误或人为跳过。

对齐后单轮IS仍低2个百分点，但IS有8题在对齐Baseline中未通过，不能断言两种方法
完全等价或从逐题差异直接推出奖励错误。两组计算量相差显著，尚非等算力对照；IS人为跳过
`django__django-10554`，该题本次Baseline也未通过。先冻结协议、对全百题日志做离线
奖励区分度和算力分析，再决定是否开展新消融，不根据个别失败题继续修改agent行为。
