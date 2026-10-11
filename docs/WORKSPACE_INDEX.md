# 工作区索引

本文件只定位目录、保留引用和整理证据；当前执行权仍由 [PROJECT_STATUS.md](PROJECT_STATUS.md) 的 Current Handoff 持有。

## 日常入口

| 用途 | 路径 |
| --- | --- |
| 正式 main 工作区 | `C:/Users/Zhang/Desktop/study agent` |
| 工作树清单与所属 PR | [2026-10-11 快照](workspace/WORKTREES_2026-10-11.md) |
| 本轮机器可读清单、保留文件 SHA256 | `D:/study-agent-validation/consolidation-20261011-records/inventory.json` |
| 原 main 六个未提交文件、头像备份和 UI 截图 | `D:/study-agent-validation/preserved-mixed-main-20261011` |
| 原根目录四份散落日志 | `logs/archive-20261011/` |
| 隔离组合验收候选 | `D:/study-agent-validation/consolidation-20261011` |
| 原 notebook 设计参考 | [NOTEBOOK_PAGE_SPEC.md](design/NOTEBOOK_PAGE_SPEC.md) |

## 保存与整理原则

- 原 main 提交 `28f2ce6a259ea82dbdbf2ac5b8151461d50bc2cd` 保留在 `codex/preserve-mixed-main-20261011`。六文件补丁有 Git stash 和独立工作树双份保留；两者 diff 已核对相同。26 份头像/预览图片随该工作树保存，SHA256 写入 inventory。
- 原 main 的 Playwright 1.62.1 依赖与 SearXNG 修复已经有远端后继，不再次覆盖 main。旧状态段落与纯格式化补丁保留在快照，不把历史交接覆盖到当前状态。
- B-Search 当前快照 `ac78c74a14f3e6b8a2a6bcf151a0b09c7d171d30` 已推送到独立引用 `codex/preserve-b-search-20261011-ac78c74a`，remote SHA 已匹配。Answer Reliability 当前 `c60a0ab1cefe78f44623c329e33061b135d945d4` 已有独立远端引用 `codex/answer-verification-shadow-1c-c60a0ab1`。这些是保存引用，不是生产资格证据。
- `conversation-first-ui`、`reading-notebook-ui`、B-Search 实验线、Answer Reliability 线存在旧祖先及重叠实现，按干净增量迁移；不直接整条合并。
- 未删除工作树、分支、虚拟环境、运行时数据库或已忽略证据。`unique_commits` 是祖先计数；squash 合并后不归零，不能据此判断功能未合入。
- notebook 六份规范/图片/JSON 从 `bd2e4a8d4c973ddb41469e19459302cf703129f5` 原样提取；不携带 #176 的过时状态段落，不把生成图当浏览器验收。

## 已知合并阻断

- #203：两条 P1 尚未关闭；结构性写入者扫描不能替代合同要求的研究/模拟 UI 动作与 durable 快照负控。Learning State-1 L2–L6 继续 NOT CLOSED。
- #204：CI 失败在 secrets 门；目前定位到 manifest 的 `source_heads` Git SHA 被熵扫描标记。证据原字节保持不动，需独立完成窄范围误报处理及归档审阅。
- #207、#214 的新 head 或运行中 CI 必须各自完成，不能借旧绿灯合并。#207 修正标题断言作用域，允许用户 Markdown 正文保留一级标题。
- RP-1、Deep-4B 与 B-Search 的研究质量资格门保持原裁定；基础设施或展示层回归通过不能替代真实研究验收。

清单是 2026-10-11 的本机快照。其他窗口可继续推进；后续先检查具体目录的当前 HEAD 和 dirty，再按增量更新本索引。
