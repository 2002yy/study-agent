# Study Agent 文档索引与治理

> 更新：2026-08-26
>
> **唯一进度入口：[`PROJECT_STATUS.md`](PROJECT_STATUS.md)。** 当前事实、证据、缺口和执行顺序只在该文件维护；新窗口先读其顶部 **Current Handoff**。

## 1. 文档所有权

| 文档 | 唯一职责 | 是否拥有当前阶段 |
|---|---|---|
| [`PROJECT_STATUS.md`](PROJECT_STATUS.md) | 当前事实、可复核证据、缺口、执行顺序 | **是，唯一** |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | 当前 runtime、application owner、数据与工具边界 | 否 |
| [`../domain_models.md`](../domain_models.md) | 稳定领域对象、关系与生命周期 | 否 |
| [`../state_invariants.md`](../state_invariants.md) | 重构后仍必须成立的硬约束 | 否 |
| [`STATE_MODEL.md`](STATE_MODEL.md) | durable / ephemeral / derived state 所有权 | 否 |
| 专项文档 | 对应子系统合同、配置或验收方法 | 否 |
| [`archive/`](archive/) | 历史方案、旧 roadmap、旧架构快照 | **禁止** |

## 2. 当前文档

### 核心合同

- [`ARCHITECTURE.md`](ARCHITECTURE.md)：React + FastAPI + SQLite 当前架构。
- [`../domain_models.md`](../domain_models.md)：LearningTopic、Goal、Claim、Revision、Evidence、Hypothesis、NextStep 等稳定语义。
- [`../state_invariants.md`](../state_invariants.md)：学习真值、证据、Persona、多 provider、恢复等不变量。
- [`STATE_MODEL.md`](STATE_MODEL.md)：状态所有权与持久化边界。
- [`TESTING.md`](TESTING.md)：自动门禁、Golden Learning Journey 与真实链路验收。

### 子系统与运维

| 文档 | 范围 |
|---|---|
| [`RAG.md`](RAG.md) | 用户资料检索、RAG evidence provider、引用与冲突边界 |
| [`WEB_SEARCH_SETUP.md`](WEB_SEARCH_SETUP.md) | 普通联网研究与 NewsRun 的 provider 配置、健康检查和降级顺序 |
| [`RESEARCH_PROVIDER_PORTFOLIO.md`](RESEARCH_PROVIDER_PORTFOLIO.md) | **post-RQ1-C** discovery provider portfolio 2.0：General Web / Semantic / Specialized 分层、调度原则与扩展顺序；**不属于当前 frozen qualification 配置** |
| [`NEWS_PIPELINE.md`](NEWS_PIPELINE.md) | durable NewsRun workflow 的实现合同与历史兼容面 |
| [`MEMORY_SYSTEM.md`](MEMORY_SYSTEM.md) | 长期记忆与 committed learning truth 的边界 |
| [`CONTEXT_TIERS.md`](CONTEXT_TIERS.md) | prompt/context 分层与预算优先级 |
| [`MODEL_ROUTING.md`](MODEL_ROUTING.md) | provider/model 路由；不拥有学习真值 |
| [`PERFORMANCE.md`](PERFORMANCE.md) | cache、延迟和预算合同 |
| [`SECURITY.md`](SECURITY.md) | 安全与外发数据边界 |
| [`TECH_STACK.md`](TECH_STACK.md) | 当前技术栈参考 |
| [`MOBILE_ACCEPTANCE_D4D.md`](MOBILE_ACCEPTANCE_D4D.md) | 延期中的实体手机人工验收记录表 |
| [`G12_ACCEPTANCE.md`](G12_ACCEPTANCE.md) | G12 会话附件切片的人工验收记录（已交付，仅作证据引用） |

### Research Quality 权威路线

以下两份文档已于 2026-08-26 完成 docs-only 路线统一；**当前状态与执行入口由 `PROJECT_STATUS.md` 顶部 Current Handoff + 其最新 RQCE Stop report 独占**，不得再固定指向某个会过期的章节号：

- [`RESEARCH_QUALITY_CODEX_TASKBOOK.md`](RESEARCH_QUALITY_CODEX_TASKBOOK.md)：联网研究质量整改总合同（C1–C100 / Shared Research Quality Engine / RQCE-P0/P1/P2）
- [`RESEARCH_QUALITY_OPENCODE_EXECUTION_PLAN.md`](RESEARCH_QUALITY_OPENCODE_EXECUTION_PLAN.md)：对应的小批施工与验收协议

统一解释：RQ1-A 是已交付的 Pre-RQCE 真值止血；C1–C100 是 quick / bounded / deep 三个 preset 的共享控制平面；旧 RQ1-B 并入 bounded preset。两份施工文档不得覆盖 `PROJECT_STATUS.md` 的 Current Handoff、当前 Gate 或执行授权。

### 冻结参考

- [`ANSWER_CLAIM_PROVIDER_REPLAY.md`](ANSWER_CLAIM_PROVIDER_REPLAY.md)：real-provider replay 稳定实验合同；运行结果只写状态 owner。
- [`INTERVIEW_NOTES.md`](INTERVIEW_NOTES.md)：项目表达素材，不是架构或状态 owner。
- [`superpowers/`](superpowers/)：2026-07 的设计与实施记录；其中 checkbox、前置事实和执行顺序均按历史时间理解。

## 3. 仓库其他 Markdown

这些文件属于运行数据、内容或历史，不合并进产品文档：

- `changelog/` 与根 `CHANGELOG.md`：版本历史，保留当时语义；旧绝对路径不参加当前链接验收。
- `memory/`、`memory.example/`：运行记忆与示例数据。
- `roles/`、`templates/`：产品提示词、角色和运行模板。
- `tests/fixtures/` 与测试目录中的 Markdown：测试夹具与期望输出。
- `assets/`：资源说明与授权信息。

## 4. 历史归档

旧 roadmap、迁移计划、架构状态和旧根目录 PRD/README 的完整正文统一保存在 [`archive/`](archive/)。原来的 14 个短兼容指针已于 2026-08-13 删除：仓库内没有消费者继续引用它们，保留空壳只会产生第二套导航；需要追溯旧路径时使用 archive 或 Git 历史。

## 5. 阅读顺序

想知道项目当前做到哪里：

```text
README.md
→ docs/PROJECT_STATUS.md（先读顶部 Current Handoff）
→ 若当前 initiative 为 RQCE：读取 PROJECT_STATUS 最新 RQCE Stop report
→ docs/ARCHITECTURE.md
```

继续学习真值、源码证据或恢复链路开发：

```text
domain_models.md
→ state_invariants.md
→ docs/STATE_MODEL.md
→ docs/ARCHITECTURE.md
→ docs/TESTING.md
```

排查联网研究：

```text
docs/WEB_SEARCH_SETUP.md
→ docs/PROJECT_STATUS.md（Current Handoff + 最新实测/RQCE 状态）
→ docs/RESEARCH_QUALITY_CODEX_TASKBOOK.md（若涉及 Research Quality）
→ docs/RESEARCH_QUALITY_OPENCODE_EXECUTION_PLAN.md（若准备施工）
→ docs/NEWS_PIPELINE.md（仅 NewsRun 专项）
```

核对 Grill 结论与实现授权：

```text
docs/PROJECT_STATUS.md（先读 Current Handoff，再读最新相关 Stop report）
→ domain_models.md（已冻结领域语义）
→ state_invariants.md（不可突破的硬边界）
→ docs/STATE_MODEL.md（状态 owner 与持久化边界）
→ docs/RAG.md（检索取消与 embedding 边界）
→ docs/SECURITY.md（逐调用外发与授权边界）
→ docs/TESTING.md（完成门与失败矩阵）
```

Grill 的逐题对话不是长期事实源。访谈完成后，只把最终决定、明确拒绝的替代方案、约束和验收门写回以上 owner；未决问题保留为 `AUDIT REQUIRED / NO-GO`，不得由实现者自行补齐。

## 6. 永久治理规则

- 进度事实只写 `PROJECT_STATUS.md`，不得新增并列 STATUS / ROADMAP / NEXT_PHASE / AUDIT。
- 设计决策固定后写入稳定 semantic docs，不复制到多份 roadmap。
- 专项文档只链接当前状态，不维护自己的“全局下一步”。
- archive、changelog、测试夹具和运行内容不参与当前事实投票。
- 文档与代码冲突时，先区分 implementation truth、project decision、external fact，再修正对应 owner。