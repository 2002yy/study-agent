# Study Agent 文档索引

> **唯一当前进度入口：[`PROJECT_STATUS.md`](PROJECT_STATUS.md)。**

仓库文档按**当前状态、稳定合同、专项说明、历史阶段材料**区分。Study Agent 当前定位是通用智能聊天与研究 Agent，长期学习为专业场景；入口 README 和架构文档必须与这一定位一致。历史方案不参与当前事实投票。

## 1. 当前事实与稳定合同

| 文档 | 职责 |
|---|---|
| [`PROJECT_STATUS.md`](PROJECT_STATUS.md) | 当前事实、证据、缺口和唯一下一步 |
| [`PRODUCT_ITERATION_POLICY.md`](PRODUCT_ITERATION_POLICY.md) | 静态/动态双循环、产品优先级与真实体验验收的稳定合同（不拥有当前下一步） |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | 当前 runtime / application owner / 数据边界 |
| [`../domain_models.md`](../domain_models.md) | 稳定领域对象、关系与生命周期 |
| [`../state_invariants.md`](../state_invariants.md) | 重构后仍必须成立的硬约束 |
| [`STATE_MODEL.md`](STATE_MODEL.md) | durable / ephemeral / derived state 所有权 |
| [`TESTING.md`](TESTING.md) | 自动门禁、Golden Journey 与真实链路验收 |
| [`../README.md`](../README.md) | 对外产品目标、当前工程能力和启动入口 |

## 2. 专项文档

- [`RAG.md`](RAG.md)：用户资料检索与 evidence provider。
- [`WEB_SEARCH_SETUP.md`](WEB_SEARCH_SETUP.md)：联网研究 provider、SearXNG、健康检查与降级。
- [`NEWS_PIPELINE.md`](NEWS_PIPELINE.md)：NewsRun durable workflow 与兼容边界。
- [`MEMORY_SYSTEM.md`](MEMORY_SYSTEM.md)：长期记忆与 committed learning truth。
- [`CONTEXT_TIERS.md`](CONTEXT_TIERS.md)：上下文层级与预算。
- [`MODEL_ROUTING.md`](MODEL_ROUTING.md)：模型/provider 路由。
- [`PERFORMANCE.md`](PERFORMANCE.md)：缓存、延迟与预算。
- [`SECURITY.md`](SECURITY.md)：安全与外发数据边界。
- [`TECH_STACK.md`](TECH_STACK.md)：当前技术栈参考。
- [`MOBILE_ACCEPTANCE_D4D.md`](MOBILE_ACCEPTANCE_D4D.md)：实体手机人工验收。
- [`G12_ACCEPTANCE.md`](G12_ACCEPTANCE.md)：G12 人工验收证据。

静态/动态回答语义与交互研究专项：
- [`ANSWER_SEMANTICS_AR1.md`](ANSWER_SEMANTICS_AR1.md)：静态知识、动态事件及修订/发布语义；以 `PROJECT_STATUS.md` 为准判断实际集成资格。
- [`CONVERSATION_AGENT_LOOP_PLAN.md`](CONVERSATION_AGENT_LOOP_PLAN.md)：2026-10-18 起的分阶段开发合同；**旧分支和“待合并”描述是历史快照**，非当前下一门。
- [`INTERACTIVE_ANSWER_DESIGN.md`](INTERACTIVE_ANSWER_DESIGN.md)：受控智能 UI 的设计和历史实现证据。
- [`RESEARCH_APPROACH.md`](RESEARCH_APPROACH.md)：研究开场与过程播报的专项合同；旧 pending 切片不作当前进度判断。

CL-M3 能力链的合同与执行记录保留在：

- [`CL_M3_CAPABILITY_CONTRACT.md`](CL_M3_CAPABILITY_CONTRACT.md)：CL-M3 能力合同，
  含 `CL-M3-RESEARCH-LIFECYCLE` 的验收口径（§10.8）与 R-3/R-4/R-6 的冻结语义（§11）。
- [`CL_M1_REBIND_PREVIEW.md`](CL_M1_REBIND_PREVIEW.md)：CL-M1 重绑预演报告，
  并作为 CL-M3 各切片的逐片执行记录（QD-1b～QD-3e）续写。
- [`CL_M3_QD3E_SURVIVED_ARCHIVE.md`](CL_M3_QD3E_SURVIVED_ARCHIVE.md)：QD-3e 变异验证中
  存活的变异逐项分类与风险裁定。

它们描述合同与施工协议，不拥有“当前下一步”；当前执行权始终以 `PROJECT_STATUS.md` 为准。

Research Quality 的设计合同保留在：

- [`RESEARCH_QUALITY_CODEX_TASKBOOK.md`](RESEARCH_QUALITY_CODEX_TASKBOOK.md)
- [`RESEARCH_QUALITY_OPENCODE_EXECUTION_PLAN.md`](RESEARCH_QUALITY_OPENCODE_EXECUTION_PLAN.md)

## 3. 历史与非文档内容

- [`archive/`](archive/)：旧 roadmap、旧架构、旧迁移计划，仅用于追溯。
- `PRODUCT_LINE_MATURITY_20261018.md` 等带日期的文档是**当日评估快照**；后续 main 整合可改变原结论，不能将历史“NO-GO/尚未合并”直接当成今天的状态。
- 根目录 [`../CHANGELOG.md`](../CHANGELOG.md)：版本历史。旧 `README_v*` 快照已从工作树移除，Git 历史本身即为完整版本来源。
- `memory/`、`memory.example/`：运行记忆与示例数据。
- `roles/`、`templates/`：产品角色、提示词与运行模板。
- `tests/fixtures/`：测试夹具。
- `assets/`：当前仅保留文档/展示截图，不再存放未接入的候选视觉素材。

## 4. 推荐阅读顺序

了解当前项目：

```text
README.md
→ docs/PROJECT_STATUS.md
→ docs/ARCHITECTURE.md
```

继续学习真值 / 源码证据 / 恢复链路开发：

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
→ docs/PROJECT_STATUS.md
→ Research Quality 合同（仅在涉及 RQCE 时）
```

## 5. 文档治理规则

1. `PROJECT_STATUS.md` 是唯一进度 owner，不新增并列 STATUS / ROADMAP / NEXT_PHASE / AUDIT。
2. 稳定设计进入对应合同文档，不复制到多份 roadmap。
3. 专项文档只描述自己的子系统，不宣布全局阶段。
4. archive、测试夹具、运行内容和 Git 历史不参与当前事实投票。
5. 文档与代码冲突时，先区分 implementation truth、project decision、external fact，再修正对应 owner。
