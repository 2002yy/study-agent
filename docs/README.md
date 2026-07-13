# Study Agent 文档导航

本目录采用“一个当前状态入口 + 分层参考文档 + 历史记录”的结构。

## 1. 日常只看这里

- [`PROJECT_STATUS.md`](PROJECT_STATUS.md)：唯一当前状态真值，包含做到哪里、还差什么、下一步做什么。

不要再同时阅读多个 status/roadmap/plan 来判断进度。它们只承担专项参考或历史记录。

## 2. 用户与项目入口

- [`../README.md`](../README.md)：项目定位、能力概览、快速开始。
- [`../USER_GUIDE.md`](../USER_GUIDE.md)：用户使用说明。
- [`TECH_STACK.md`](TECH_STACK.md)：技术栈与可对外展示的工程亮点。

## 3. 稳定架构与工程参考

这些文档描述相对稳定的 owner、边界、数据模型或技术约束，不维护当前进度：

- [`ARCHITECTURE_STATUS.md`](ARCHITECTURE_STATUS.md)：架构 owner、sealed/partial 边界附录。
- [`STATE_MODEL.md`](STATE_MODEL.md)：源码、配置、用户数据、缓存和迁移范围。
- [`RAG.md`](RAG.md)：RAG 设计、能力边界和使用说明。
- 其他 API、测试、安全、迁移和工程说明文档也归入本类。

## 4. 设计规范

目录：`superpowers/specs/`

用途：

- 记录某项功能“应该是什么”；
- 固定目标、用户流程、边界和验收；
- 不承担当前进度维护；
- 实现变化时可修订规范，但不得把 spec 当状态看板。

## 5. 实施计划与历史记录

目录：`superpowers/plans/`

分类规则：

- 仍被 `PROJECT_STATUS.md` 明确列为当前切片的计划，作为实现细节参考；
- 已完成、被替代或失效的计划，保留为历史记录；
- 历史计划中的未勾选 checkbox 不代表当前代码未完成；
- 每个计划顶部必须注明 `active / superseded / archived`。

当前几个历史/专项文件：

- `2026-07-12-study-agent-consolidated-roadmap.md`：G1–G17 详细需求目录，不再是日常状态入口。
- `2026-07-12-learning-loop-deepening.md`：学习闭环专项记录。
- `2026-07-12-learning-workspace-redesign.md`：方案 B 实现记录，已归档。

## 6. 审计与报告

审计文档应满足：

- 写明审计日期和代码基线；
- 区分事实、推断和建议；
- 审计结论更新到 `PROJECT_STATUS.md` 后，原报告转为历史证据；
- 不单独维护长期“下一步”列表。

后续新增审计报告时，优先放入 `reports/` 或对应专题目录，不再直接堆在 `docs/` 根目录。

## 7. 文件命名规则

- 当前真值：固定名称 `PROJECT_STATUS.md`。
- 稳定参考：使用主题名，如 `RAG.md`、`STATE_MODEL.md`。
- 设计规范：`YYYY-MM-DD-<topic>-design.md`。
- 实施计划：`YYYY-MM-DD-<topic>-implementation.md`。
- 审计报告：`YYYY-MM-DD-<topic>-audit.md`。
- 历史文件不改写日期来伪装成新文档。

## 8. 维护规则

1. 代码状态只在 `PROJECT_STATUS.md` 更新一次。
2. README、USER_GUIDE 和技术参考通过链接引用当前状态，不复制状态表。
3. 架构文档只在 owner、边界或不变量改变时更新。
4. spec、plan、audit 顶部必须明确文档类别和生命周期。
5. 完成一个代码切片时，同时更新测试、用户文档和 `PROJECT_STATUS.md`。
6. 禁止新增与 `PROJECT_STATUS.md` 并列的长期状态文档。
