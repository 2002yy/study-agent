# Study Agent 当前状态

> **唯一进度入口：当前权威能力、验收边界与下一门。**
> 快照日期：2026-10-24；整理前功能基线 main = `a717d0c120f742b0d5309cf85de60c2ebf0277f8`；该提交的 [main CI #40014614495](https://github.com/2002yy/study-agent/actions/runs/40014614495) = SUCCESS。它是**整理前基线**，不是本次文档合并 SHA。
> 产品定义：**Study Agent 是体验接近 GPT-6 Chat 的智能聊天与研究 Agent。自然聊天、自主研究、持续交互、智能 UI、统一多模态、工具执行是六项通用核心能力；长期学习与教学是其上的专业场景。**

本文件只保留当前快照、明确阻断和唯一下一门，不再不断追加每次 CI、诊断与其他项目日志。整理前的交接内容没有删除，而是**完整保存在以下两份历史快照**：

- [2026-10-24 当前 main 整理前完整正文](archive/PROJECT_STATUS_HANDOFF_PRE_CLEANUP_2026-10-24.md)：原 `docs/PROJECT_STATUS.md` blob `38439199c16dba836945890b2987496aa2667e71`（999 行）。包括 2026-10-24 AR 候选、测试及各阶段原始交接，其旧日期的“尚未合并”只属于当时历史状态。
- [2026-10-23 旧 #282 草稿归档](archive/PROJECT_STATUS_HANDOFF_PRE_CLEANUP_2026-10-23.md)：原 blob `f067534fa01a68de234eeaea0dc2216dc0462cf3`（520 行）。更早历史见 [2026-10-06 归档](archive/PROJECT_STATUS_PRE_177_FINAL_REVIEW_2026-10-06.md) 与 Git 提交。

## 0. Current Handoff（cold-start 入口）

### 当前 main 与未验收能力分开记录

| 方向 | 已证实进入 main | 尚未取得的资格 |
| --- | --- | --- |
| **聊天、模型生成与流式接口** | #249、#251–#255、#257 已合并；仓库存在有界回答、DeepSeek 服务/传输、阶段 SSE 和受控入口等模块。旧 `/chat` 兼容路径仍保留。 | **模块在 main 不等于新对话循环已实际接管生产请求。** 下一步 CL-M3 检查真实路由/宿主、恢复、取消与正式发布。#256 已关闭但未单独合并，不以其 PR 状态认定功能完整。 |
| **静态/动态回答、研究与证据** | [#272](https://github.com/2002yy/study-agent/pull/272) 已合入 `a717d0c120f742b0d5309cf85de60c2ebf0277f8`：逐次 read events、可核实发布绑定、独立修订与持久费用账本；#259/#265 的完整旧 HEAD 是 #272 集成候选的祖先，已作为重复 PR 归档。精确 PR CI #40011252034 与合并后 main CI #40014614495 均成功。 | 工程合并和自动 CI **不等于真实模型的动态语义质量、正式发布权威或产品 GO**。可读来源、claim support、publication authority 必须分开。 |
| **费用、存储与附件** | v25→26 增量账本迁移、保守预留与重复请求拒绝；附件重试采用服务端绑定，删除/上传选择更新及受限指数运算有回归测试。 | 账本**尚无结算/退款 API**；已发送请求发生超时/取消仍保留预留。CL-M3 新调用路径须再次检查计费；数据库回滚应使用迁移前备份。 |
| **交互 UI 与开发工具** | main 保留中文输入法保护、阅读跳转、聊天附件与进度 UI；studyctl #270/#280 已合并。 | 静态演示、fake-provider 验收、付费模型动态效果互不替代。 |
| **验证** | `a717d0c120f742b0d5309cf85de60c2ebf0277f8` 普通 main CI 全绿（Python、前端、Ruff/mypy、Golden Journeys、real-stack 及最终结果门）。 | **全量 L3 对本次 AR 集成仍记为欠账**，普通 CI 不等于 L3。历史 Firefox 对照失败是获准的本次整合非阻塞例外，保留旧证据，不宣称 Firefox 历史失败已消失。 |

### 唯一下一门：CL-M3 生产宿主接线与真实行为验收

1. 从 main 实际路由检查新的 conversation loop、DeepSeek 服务、answer handler 是否有真实生产调用方；用 fake-provider 跑端到端路径，而不是仅看文件存在。
2. 保持服务端 turn/operation 身份、唯一 CAS 结算、崩溃恢复和取消语义；断流不是持久取消。阶段 SSE 只能 provisional，正式答案继续通过证据及发布门。
3. 逐个核对新调用方的费用预留和持久账本；**没有真实付费模型调用授权**，不得借用 #272 CI 代替动态质量评测。全量 L3 另行授权。

### 状态更新纪律

- `main`、PR、独立工作树各自标注；CI 只能绑定**本轮精确 HEAD**。合并完成和产品 CLOSED 是两回事。
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
