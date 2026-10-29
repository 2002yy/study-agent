# Study Agent 当前状态

> **唯一进度入口：当前权威能力、验收边界与下一门。**
> **最近一次状态验收基线：2026-10-27 / `4cbcefe2efddb986d71deb1bf5f7d5dff5c571cf`（#289 合并提交）。**
> 本行是那一日期**已核验的基线**，不是“当前 main”。main 此后继续前进不使本节失效，也不构成重写本文件的理由；下表每行的资格以该行自身记录的 head 与 run 为准。
> 产品定义：**Study Agent 是体验接近 GPT-6 Chat 的智能聊天与研究 Agent。自然聊天、自主研究、持续交互、智能 UI、统一多模态、工具执行是六项通用核心能力；长期学习与教学是其上的专业场景。**
> **部署边界：仅支持可信环境下的单用户部署。** 多会话并发安全不等于多用户安全；多用户身份与数据隔离是独立立项，尚未实现。

本文件只保留当前快照、明确阻断和唯一下一门，不再不断追加每次 CI、诊断与其他项目日志。整理前的交接内容没有删除，而是**完整保存在以下两份历史快照**：

- [2026-10-24 当前 main 整理前完整正文](archive/PROJECT_STATUS_HANDOFF_PRE_CLEANUP_2026-10-24.md)：原 `docs/PROJECT_STATUS.md` blob `38439199c16dba836945890b2987496aa2667e71`（999 行）。包括 2026-10-24 AR 候选、测试及各阶段原始交接，其旧日期的“尚未合并”只属于当时历史状态。
- [2026-10-23 旧 #282 草稿归档](archive/PROJECT_STATUS_HANDOFF_PRE_CLEANUP_2026-10-23.md)：原 blob `f067534fa01a68de234eeaea0dc2216dc0462cf3`（520 行）。更早历史见 [2026-10-06 归档](archive/PROJECT_STATUS_PRE_177_FINAL_REVIEW_2026-10-06.md) 与 Git 提交。

## 0. Current Handoff（cold-start 入口）

### 验收基线与未验收能力分开记录

| 方向 | 已证实进入 main | 尚未取得的资格 |
| --- | --- | --- |
| **CL-M3 生产接线（S2 批次）** | [#288](https://github.com/2002yy/study-agent/pull/288) 已合并为 `5b0acbb7656e113ab8737b4e4e633aaee21a4bcf`。精确 PR HEAD `3ab26f83` 的 PR CI #40300791096 全绿（全量 pytest 6343 passed、ruff、mypy 基线、前端、Golden Journeys、real-stack 均 success）；25 条评审线程在逐条核对代码与回归测试后全部收口。 | 合并提交的 main CI（#40310609353）实际为 **failure**：`Install Playwright browsers` 在 40 分钟上限处超时（托管 runner 的 apt 镜像过慢），随后两个浏览器步骤被 `if:` 跳过，汇总门禁如实变红——**当时 main 的浏览器门禁并未真正执行**。该缺陷已由容器化解决（browser 作业改用固定 digest 的 Playwright 镜像，浏览器预装、不再 `--with-deps`，见 `docs/CI_BROWSER_CONTAINER_PLAN.md`），并在 main 上验证为绿：run `40473062649`（`346e2547`）与 run `40484965012`（`c8359685`）。**工程合并不等于产品 GO**。全量 L3 未在该批次单独记录（CI 已执行同一测试集合）。 |
| **访问控制（S1，已合并）** | [#289](https://github.com/2002yy/study-agent/pull/289) 已合并为 `4cbcefe2`。精确 PR HEAD `959f4252` 的 PR CI [40486213770](https://github.com/2002yy/study-agent/actions/runs/40486213770) 五作业全绿（`classify`/`backend`/`frontend`/`browser`/`test` 均 success；Golden Journeys 79 passed、real-stack 24 passed）。能力边界：`STUDY_AGENT_API_TOKEN` 未配置时拒绝所有私有请求；前端改为运行时输入令牌（localStorage），不写入构建产物；锁定状态有明确提示并在保存后自动重载；启动器不再以 `VITE_` 变量把令牌交给前端开发服务器。Windows 启动链哨兵为**本地动态验收**（A 正常脚本 0 泄露且 `/sessions` 401、B 回退旧 `VITE_` 注入时探针在 10 个应用模块检出哨兵、C 去掉安全断言时门禁以 exit 1 如实失败、D UI 输入令牌 401→200），证据见 PR 评论 `6438275491` 与 `D:\study-agent-validation\artifacts\s1-windows-sentinel-2026-10-27\`。 | 哨兵的 **CI 自动化仍是开放项**：现有证据是本地动态验收，不是常设门禁。启动器 `Test-FrontendIdentity` 仍按英文标题 `<title>Study Agent Console</title>` 检查，而实际标题是「学习助手 · 学习工作台」，健康服务会被误判为启动失败（独立 P2，未在本批次修复）。多用户身份、数据归属与配额隔离**尚未实现**。 |
| **多用户隔离** | — | 需要身份、`chat_threads` 等表的归属字段、按用户过滤的查询边界、记忆/附件/研究任务与费用配额隔离。当前版本明确**不是**多用户系统。 |
| **并发稳定性** | 同一会话单操作（CAS）、同一研究任务租约与代际、陈旧写入版本校验、研究事件全局递增序号。 | 聊天操作 300 秒过期回收**没有续租**，多进程同时运行时长任务可能被误判；全局设置读改写存在并发丢更新窗口；搜索线程池超时后线程不能强制终止。均为已确认、待修问题。 |
| **费用、存储与附件** | 保守预留、重复请求拒绝、结算观测与适配器隔离（默认关闭）。 | 账本仍有结算能力边界；付费调用开关保持 OFF，真实调用费用未验证。 |
| **验证** | 精确 HEAD 上的普通 CI 可复现；测试集合与 L3 相同（仓库无 `testpaths`/`addopts`）。 | 普通 CI 不等于 L3 记录；L3 额外提供的是干净检出与精确 SHA 的出处保证。真实模型的动态质量仍未验证。 |

### 当前主线：Search-1 真实检索（P0，2026-10-29 起）

| 项 | 状态 |
| --- | --- |
| 题集 | `tests/fixtures/provider_routing/search_1_queries_v1.json`，31 题（复用 10 题冻结集 + 21 题新增） |
| 证据 | 采集 `SEARCH_1_CAPTURE.json`、回放 `SEARCH_1_REPLAY.json`、人工首条审计 `SEARCH_1_AUDIT.json`，报告 `docs/research_quality/SEARCH_1.md` |
| 结果 | 生产 A 首条答案 1/31；DDG 优先合并不重排 30/31；生产重排 30/31；候选 n-gram 重排 28/31 |
| 判据问题 | 现用锚点 Hit@6 在同一 12 条池子上随机抽 6 条就有 0.96 命中，只能作诊断；主指标改为人工首条审计 |
| 结论 | 差距来自 DDG 自身排序，不是重排；重排会把官方 release 页换成二手教程页（N13）、把非官方仓库推上首位（N12） |
| 下一门 | **D2（DDG 优先回退）**：同快照上 32 次请求、P50 4.14 s、首条与双引擎交错完全一致；先做小规模真实复测，再决定是否改生产入口。边界页降权与中文实体查询写法随后 |

Runtime-1B 四臂运行器（PR #308）按用户决定**暂缓**，不合并；`warnings()` 并发修复同列 P2。

### 唯一下一门：S2 并发与暴露面收口（暂停，等待单独授权）

1. **S1（CLOSED，2026-10-27）**：无令牌一律 401；前端运行时令牌；本地配置方法写进 README；E2E 用真实浏览器验证令牌路径。已合并为 `4cbcefe2`，精确 head 五作业 CI 全绿；剩余开放项只有哨兵 CI 自动化与启动器标题检查（见上表）。
2. **S2（未启动、未授权）**：聊天操作增加 `active_operation_heartbeat_at` 续租、回收改为原子条件更新且只针对心跳过期、旧记录按明确回退规则处理；该切片含迁移，需要一次完整 L3。**当前没有对应 PR，也没有合并授权**，main 仍按 300 秒直接回收。
3. **[#293](https://github.com/2002yy/study-agent/pull/293)（独立搜索可靠性修复，未合并）**：`web:` 让 DuckDuckGo 提供商真正返回结果（POST 表单 + 作用域代理），只触及 `.env.example`、`src/web/tool_gateway.py` 与对应测试。它与 S2 并发续租**无关**，保持开放、未合并、未授权。
4. **S3**：研究取消时序先写负控测试，只有真实复现“取消后仍发起付费调用”才修改生产逻辑。
5. **S4/S5**：全局设置并发、搜索资源回收，保留方案不改代码。
6. **S6**：多用户隔离独立立项。

### 并发与多用户边界（2026-10-26 远端静态审查）

静态审查确认的问题与当前处置：未认证放行（S1 已合并 `4cbcefe2`）、`chat_threads` 无归属字段（S6）、300 秒误恢复（S2 待授权）、设置读改写竞态（S4）、线程池超时不可终止（S5）、研究取消层间空窗（S3 先测）。
已有保护不可忽略：单会话操作 CAS、研究任务租约与代际、陈旧写入版本校验、事件全局序号。

### 状态更新纪律

- `main`、PR、独立工作树各自标注；CI 只能绑定**本轮精确 HEAD**。合并完成和产品 CLOSED 是两回事。
- 本文件记录**验收基线**，不追随 main 的最新 SHA：main 前进不需要重写头部，只有当某项能力或其证据变化时才更新对应行，并在该行写明新的 head/run。
- 本文件只维护状态表及唯一下一门；逐次测试、CI 与候选取证留在 PR/历史归档，不能用旧句子覆盖新的事实。
- **模型负责语义、规划与研究/回答策略；程序负责真实读取、工具执行、状态、费用上限与发布资格。** 静态知识与动态事件使用不同证据合同。
- #282 只允许文档及历史归档变化，禁止擅自改 src/tests/workflow、开启模型或运行全量 L3。

## 0A. 冻结研究路线

```text
Lookup → VERIFIED / SAFE_ABSTAIN / pending ESCALATE_STANDARD
Standard（CLOSED）→ 多源补全、比较与冲突；现有生产 runtime 消费
Deep（Deep-1/2/3T/3/4A CLOSED；Deep-4B NO-GO）
  → plan / gap / Evidence Gain / saturation / interruption-resume
  → 复用 ActiveResearchRuntimeExecutor，禁止第二套研究引擎
```

`usable/read_backed/relevant` ≠ claim support ≠ publication authority。各历史结论按其**记录日期**理解，最新状态以当前 main、精确 CI 和本节为准。
