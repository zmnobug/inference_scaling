# SWE-bench Qwen3.8-27B IS/MH 消融实验问题与修复记录

本文记录 Qwen3.8-27B API、原版 mini-SWE-agent、重要性采样（IS）和
Metropolis--Hastings（MH）消融实验从设计、预检到 smoke 运行期间遇到的问题、证据、根因、修复和结果有效性边界。
实验的目标、参数矩阵和统计协议仍以
[实验设计文档](SWEBENCH_QWEN38_27B_IS_MH_ABLATION_DESIGN.md)为准；本文不重新定义实验方法。

记录状态：2026-09-09。当前正式运行版本为 Git commit
`235639a26e47dc66e8c32eb6b3d9b3980d45b832`，实验 tag 为 `qwen38-27b-is-mh-v3`。

## 1. 固定实验边界

问题排查和修复始终保持以下边界：

- 模型通过已经部署的 Qwen3.8-27B OpenAI-compatible API 调用；
- Agent 使用原版 mini-swe-agent `2.4.6`，commit `25941c89cfbc91eb40b3f8756348c91d9977d57e`；
- Agent action 使用官方 `swebench_xml.yaml` 文本/XML 协议；
- 不增加 SWE-agent、OpenHands 或其他 Agent harness；
- IS/MH 在线奖励只读取模型响应中已评分 token 的累计 logprob；
- 中间轨迹不读取 gold patch、测试标签或 verifier 结果；
- 最终 patch 使用官方 SWE-bench `5.0.1` evaluator 计算 `resolved`；
- API token 不做成本配平，但请求、token、工具、checkpoint 和墙钟必须完整记录。

因此，本文中的“代理修复”只处理 OpenAI-compatible 响应契约，“runner 修复”只处理 IS/MH 分支状态和记账，均不改变
MiniAgent prompt、action 语义或 SWE-bench 最终判定规则。

## 2. 问题总览

| 编号 | 现象 | 层级 | 根因 | 处理状态 |
| --- | --- | --- | --- | --- |
| P1 | sampled logprob token 无法重建 `message.content` | API 代理 | vLLM 隐藏了思考边界标记，但 logprobs 仍包含对应 token | 已修复 |
| P2 | `1 unscored output token` | API 代理 | 过滤隐藏 token 后未同步修改 `usage.completion_tokens` | 已修复 |
| P3 | 响应没有 sampled-token logprobs | vLLM 配置 | 自动工具解析从文本中提取了原生 `<tool_call>` | 已修复 |
| P4 | `ReplayDiverged` | IS/MH runner | 新容器从基础镜像重放历史命令，无法复现真实工作区状态 | 已修复 |
| P5 | evaluator 抛出 `KeyError: 'image'` | 数据集契约 | 旧数据 revision 缺少 SWE-bench 5.x evaluator 字段 | 已修复 |
| P6 | 从 checkpoint SHA 启动容器时 Docker exit 125 | Docker 生命周期 | 裸 SHA checkpoint 是 dangling image，可在恢复前被 prune/GC 回收 | 已修复并通过定向回归 |

此外，代码审计还修正了 IS candidate logprob 重复累计风险，并把参数测试从不可承受的全组合改为分阶段漏斗。

## 3. API logprob 响应链

### 3.1 P1：token 无法重建响应文本

初次 smoke 在部分长轨迹响应上出现：

```text
sampled logprob tokens do not reconstruct response content
```

同一代理的短 preflight 和部分完整 case 可以通过，说明这不是固定网络错误或所有请求都不兼容。服务器保存原始响应后确认，
vLLM 的 token 流中偶尔存在被 chat template 隐藏的思考边界标记，例如历史现场中的 `" response"`；该标记没有出现在
`message.content`，但仍出现在 sampled-token logprobs 中，因此逐 token 重建会多出内容。

代理层增加了按 `message.content` 对齐的过滤器：

1. 保持 `message.content` 字节级不变；
2. 优先使用 token bytes 重建可见内容；
3. 丢弃无法对应可见 content 的隐藏标记 token；
4. 把原始和规范化响应写入脱敏 transcript；
5. 将仍无法重建的响应单独落盘。

该修复不改变模型传给 MiniAgent 的 action 文本，只修正 logprob 与可见文本的对应关系。

### 3.2 P2：过滤后 token 计数漂移

过滤隐藏标记后，下一次 smoke 出现：

```text
ValueError: API response contains output tokens without matching logprobs: 1 unscored
```

现场响应原始 `completion_tokens=55`，代理移除了一个隐藏标记并把 EOS 分数转入 `termination_logprob`，但仍报告 55 个
completion tokens。最终只有 54 个 token 有对应评分，固定代码因此正确地拒绝了响应。

代理随后同步修正 usage，并保留两套计数：

```text
raw_completion_tokens
normalized_completion_tokens
dropped_hidden_tokens
raw_total_tokens
```

仓库侧校验以下不变量：

```text
raw_completion_tokens
= normalized_completion_tokens + dropped_hidden_tokens

raw_total_tokens
= prompt_tokens + raw_completion_tokens
```

轨迹长度使用规范化可见 token；自然 API 成本和预算统计使用原始 token，避免因代理过滤而低估服务端生成量。

### 3.3 P3：vLLM 自动工具解析吞掉文本

后续 smoke 的部分响应报错：

```text
API response does not contain sampled-token logprobs
```

transcript 显示模型偶尔输出原生 `<tool_call>` 语法，而服务端启动时启用了：

```text
--enable-auto-tool-choice
--tool-call-parser qwen3_coder
```

vLLM 将该文本解析为原生工具调用字段，从 `message.content` 移除对应内容，同时没有提供 MiniAgent 所需的文本 token
logprobs。原版 MiniAgent 本实验使用 `THOUGHT + <mswea_bash_command>` 文本/XML 协议，并未向 API 发送原生 tools，
因此两套工具协议不兼容。

服务端已关闭上述两个参数。原生 `<tool_call>` 现在作为普通文本保留，由 MiniAgent 自己判断格式是否合法。此后 smoke 中
该类错误降为零。

## 4. IS/MH 工作区状态

### 4.1 P4：历史命令重放产生 `ReplayDiverged`

初版 IS/MH runner 为候选或 proposal 创建全新 SWE-bench 容器，然后从初始镜像重新执行已保存的历史 action，并比较
工具 observation。smoke 出现多次：

```text
ReplayDiverged: MiniAgent tool observation differs during replay
```

插桩重放表明，单条只读命令在干净容器间通常一致，差异来自更早的修复类 action：主链容器已经包含文件修改、生成物和
其他工作区状态，而新分支通过重放命令不能保证得到字节级相同的完整状态。较长的测试命令和全盘扫描只是暴露差异的
位置，不是根因。

Git commit `d19912f` 将分支机制改为 Docker root-filesystem checkpoint：

- action 边界通过 `docker commit` 保存真实容器文件系统；
- `SessionCheckpoint` 同时保存 messages、已执行决策、调用次数、cost、格式错误计数、模型请求索引和 Agent 已用时间；
- IS 从主链 checkpoint 创建 candidate，candidate action 只执行一次；
- rollout 从 candidate 执行后的 checkpoint 继续；
- 被选中的 candidate session 直接提升为主链，不在旧主容器重复执行 action；
- MH proposal 直接从所选 cut 的 checkpoint 创建；
- 接受 proposal 时提升其 session，拒绝时保留原 session；
- runner 不再提供或调用历史工具 action replay 路径。

Docker mount 中的数据不会进入 `docker commit`，因此正式 IS/MH profile 强制使用 Docker 且拒绝包含 mount/volume 的
环境。该修复后的 15-case `v2` smoke 中 `ReplayDiverged=0`。

### 4.2 IS candidate logprob 重复累计

checkpoint 改造审计还发现，旧 IS rollout 的 prefix 边界设置在 candidate 执行之前，导致所谓 suffix 已包含 candidate；
权重计算又显式加了一次 candidate logprob。candidate 因而可能被累计两次。

现在先执行 candidate 并保存 checkpoint，再从 checkpoint 生成纯 continuation suffix：

```text
trajectory_logprob = candidate_logprob + continuation_suffix_logprob
```

测试固定断言 candidate 恰好计入一次。

### 4.3 P6：裸 SHA checkpoint 被回收

`d19912f` 的新 checkpoint 机制解决了历史重放，但第一次完整 `v2` smoke 得到 14/15 completed。唯一错误为：

```text
arm: mh-a1.5-u4-sall-dmultiscale-n1-c819
instance: django__django-12308
error: docker run exit 125
image: sha256:94bec96a...
```

该 case 在失败前已有 45 次 API 请求、46 次成功 snapshot，且 API、代理和 snapshot 创建均无错误。失败发生在较深 MH
更新中恢复一个先前 checkpoint 时；目标 SHA 已不存在。

本地 Docker 验证确认：

- 同一容器连续 commit 会得到不同 image SHA，重复 SHA 引用不是主因；
- 不带 repository tag 的 commit 结果属于 dangling image；
- 带唯一 tag 的 checkpoint 能在默认 dangling-image prune 后保留。

Git commit `235639a` 因此增加以下保护：

1. 每个 checkpoint 创建唯一临时 tag：

   ```text
   inference-scaling-swebench-checkpoint:<factory-uuid>-<sequence>
   ```

2. `SessionCheckpoint` 同时保存不可变 image ID 和用于恢复的 image ref；
3. 分支容器从受保护的 image ref 启动，不再直接引用裸 SHA；
4. 恢复前执行 `docker image inspect`，缺失时报告 ref、ID 和 Docker 原始错误；
5. 新增 `state_restores`、`restore_failures` 和 `restore_seconds`；
6. 正常关闭时按唯一 tag 删除 checkpoint；
7. 结果 schema 升级为 `swebench-is-mh-v4`，实验 tag 升级为 `qwen38-27b-is-mh-v3`。

唯一 tag 能防止默认 dangling-image prune，但不能抵抗运行期间显式执行的 `docker image prune -a` 或
`docker system prune -a`。正式实验期间必须禁用此类清理任务。

2026-09-09 的 `v3` 定向回归重新运行了两个 django/MH case，其中历史失败组合
`mh-a1.5-u4-sall-dmultiscale-n1-c819 / django__django-12308` 在 67 次 API 请求、68 次 snapshot 和 4 次 restore 下
完成，`snapshot_failures=0`、`restore_failures=0`，且没有 Docker exit 125、ReplayDiverged 或代理错误。另一个
`mh-a1-u1-sall-dfull-n1-c819` case 也完成。两次官方 evaluator 均正常退出，运行结束后本次 checkpoint tag 均被清理。
这直接验证了 P6 的修复；两个补丁均未 resolved 属于模型求解结果，不属于基础设施失败。

## 5. 官方 evaluator 数据契约

### 5.1 P5：旧数据缺少 `image`

完成部分 smoke 后，官方 SWE-bench evaluator `5.0.1` 在构造 test spec 时抛出：

```text
KeyError: 'image'
```

进一步检查发现，旧的
`princeton-nlp/SWE-Bench_Verified@c104f840cc67f8b6eec6f759ebc8b2693d585d4a` 不仅缺少 `image`，还缺少：

```text
eval_script
log_parser
eval_type
```

正式数据改为：

```text
SWE-bench/SWE-bench_Verified
revision=78f471bf655a3137b2e8a75af1501690ec009ec3
```

仓库在 preflight、run suite 和 evaluator 前统一验证所需字段、instance ID 唯一性及 canonical Docker image 名称。对旧
诊断结果的评测不会覆盖原 `dataset.parquet`，而是生成 `dataset.evaluation.parquet`，并验证新旧行的以下推理身份字段：

```text
instance_id
repo
base_commit
problem_statement
version
```

`evaluation/dataset_provenance.json` 保存双方 revision、文件 hash、行内容 hash 和补齐字段。正式 `v3` 运行直接使用
5.x-compatible snapshot，不需要兼容迁移。

## 6. 实验规模和参数设计调整

完整参数笛卡尔积包含 135 个 IS 组合和 960 个 MH 组合，不适合作为 SWE-bench 正式计划。实验改用固定漏斗：

| 阶段 | 实例数 | arm 数 | seed 数 | arm-case 数 | 用途 |
| --- | ---: | ---: | ---: | ---: | --- |
| smoke | 3 | 5 | 1 | 15 | API、Docker、Agent 和 evaluator 闭环 |
| calibrate | 5 | 13 | 1 | 65 | reference 附近的单因素校准 |
| stress | 2 | 10 | 1 | 20 | 极端成本和退化检查 |
| screen | 15 | 7 | 1 | 105 | Base、reference、runner-up 正式筛选 |
| seed_check | 20 | 3 | 1 | 60 | 独立 seed 稳定性检查 |
| confirm | 50 | 3 | 2 | 300 | 冻结配置后的盲确认 |
| 合计 | | | | 565 | 不含失败重跑和 evaluator 重评 |

完整 MiniAgent 轨迹输出上限固定为 8192 token。IS chunk 从最初的固定整数讨论调整为完整轨迹上限的约
5%、10% 和 15%：

```text
410 / 819 / 1229
```

chunk 是单次 MiniAgent action 请求上限；多个 action 请求共同组成最多 8192 token 的完整轨迹。共享 token budget 设为
0 表示只记录、不跨候选截断，不代表单次 API 请求没有 `max_tokens`。

## 7. 版本与结果有效性

| 实验版本 | 主要实现 | 结果用途 |
| --- | --- | --- |
| `v1` | 历史 action replay；旧 evaluator 数据契约 | 仅用于定位 API 和 replay 问题 |
| `v2` / `d19912f` | Docker checkpoint，但只保存裸 SHA | 14/15 smoke 仅作 checkpoint 诊断，不进入正式汇总 |
| `v3` / `235639a` | 唯一 tag checkpoint、恢复审计、SWE-bench 5.x 数据 | 当前正式实验版本 |

不同 dataset revision、结果 schema、实验 tag 或 checkpoint state mode 的记录不得合并。尤其不能用 `v2` 的 14 条 completed
记录加一条 `v3` 重跑结果伪装成同一版本的 15/15 smoke。`v3` 必须使用新目录；未完成的 smoke 和定向回归保持独立，
并按下述替代工程准入如实记录。

2026-09-09 的 `v3` 完整 smoke 在 7 个 case 完成且无异常后，为缩短验证时间按人工决策停止；随后两个 django/MH
定向回归全部完成。该组合覆盖 Base、两个 IS arm、两个 MH arm，以及历史失败的 multiscale checkpoint 恢复路径。
这些结果只用于工程准入，不作为正式 resolved-rate 样本，也不表述为 15/15 smoke。

## 8. 当前准入门槛

原计划要求 15/15 smoke 全部通过。为控制前置验证耗时，本轮经人工确认采用“7 个无异常 smoke case + 2 个关键 MH
定向 case”的替代工程准入；进入 calibrate 时必须明确记录该偏离。准入仍要求已执行 case 同时满足：

- 所有已执行的准入 case 均为 `record.status == completed`；
- `ReplayDiverged=0`；
- proxy reconstruction failure 为 0；
- `unscored_output_tokens=0`；
- API response missing logprobs 为 0；
- `snapshot_failures=0`；
- `restore_failures=0`；
- IS/MH case 的 `state_snapshots > 0` 且 `state_restores > 0`；
- 官方 evaluator 无基础设施错误；
- `dataset_provenance.mode == native_swebench_5_dataset`。

smoke 未通过时不得进入 calibrate。calibrate 和 stress 完成后必须先根据 resolved rate、IS ESS、MH acceptance rate、自然
token/API/tool/checkpoint 成本和失败率冻结 reference 与 shortlist，再运行 screen；不能提前用 screen/confirm 结果调参。

## 9. 运维与审计要求

代理位于服务器临时基础设施目录，不在本仓库。每次正式运行必须记录代理文件 SHA、vLLM 启动命令、chat template SHA、
模型 ID、tokenizer/config SHA 和 transcript 起止位置。vLLM 必须保持自动工具解析关闭。

实验期间不得执行：

```text
docker image prune -a
docker system prune
docker system prune -a
```

进程被强制终止后，只能在确认没有同仓库实验运行时清理带实验 label 的残留 checkpoint：

```bash
docker image prune -a -f \
  --filter label=org.inference-scaling.swebench.checkpoint=true
```

出现错误时先保存首个 `record.json`、trajectory、完整 traceback、arm、instance ID、usage、对应 proxy transcript 和 Docker
原始 stderr，再决定是否重跑。基础设施修复导致结果 schema 或执行语义变化时必须使用新 tag 和新结果目录。

## 10. 结论

GSM8K 的单次文本生成链路虽然已经工作，但 SWE-bench 会放大接口和状态问题：一个 case 包含数十到数百次模型请求、工具
调用、文件修改和分支恢复。短 preflight 只能证明单次响应格式，不能证明长轨迹中的隐藏 token、工具解析、工作区状态、
Docker image 生命周期和 evaluator 数据契约全部正确。

本轮排查把这些层级拆开后，形成了以下稳定边界：API 代理负责可见文本与 logprob/usage 对齐；vLLM 只提供文本生成，
不解析原生 tools；runner 使用受保护的 Docker checkpoint 保存分支状态；官方 SWE-bench evaluator 只在轨迹结束后验证
最终 patch。后续参数结论只有在 `v3` 全链路门槛通过后才具有正式实验意义。
