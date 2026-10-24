# Study Agent 当前架构

> **稳定架构 owner。** 当前进度看 [`PROJECT_STATUS.md`](PROJECT_STATUS.md)。旧 Streamlit 架构原文保存在 [`archive/ARCHITECTURE_STREAMLIT_REFERENCE.md`](archive/ARCHITECTURE_STREAMLIT_REFERENCE.md)。

## 1. 产品定义

Study Agent 的**通用产品目标**是体验接近 GPT-6 Chat 的智能聊天与研究 Agent：自然聊天、自主研究、持续交互、智能 UI、统一多模态和工具执行是六项核心能力。长期学习、教学与学习状态恢复是专业场景，不再充当整个项目的定义。

```text
用户问题 / 后续条件 / 附件
    ↓
模型提出回答或行动策略
    ↓
应用层核对真实上下文、权限与费用预算
    ↓
搜索 / 阅读 / 工具执行 / 状态与证据修订
    ↓
已授权的正式答案 + 有用的阶段性展示 + 可恢复的记录
```

**能力实现 ≠ 生产路由启用 ≠ 真实模型动态验收。** 当前新 conversation loop 已有模块但仍待 CL-M3 生产宿主接线；旧 `/chat` 兼容路径继续保留，不能把可选模块、流式进度或静态测试当作真实任务完整答复。精确进度与产品 GO/NO-GO 只看 [`PROJECT_STATUS.md`](PROJECT_STATUS.md)。

## 2. 运行时层级

```text
┌──────────────────────── React ────────────────────────┐
│ WorkspaceView / stable learning surfaces / Lab       │
└──────────────────────────┬────────────────────────────┘
                           │ HTTP / SSE
┌──────────────────────────▼────────────────────────────┐
│ FastAPI routes / middleware assembly                 │
└──────────────────────────┬────────────────────────────┘
                           │ narrow application ports
┌──────────────────────────▼────────────────────────────┐
│ EvidenceRuntime                                      │
│ LearningSessionRuntime                               │
│ ExtensionRuntime                                     │
└──────────────────────────┬────────────────────────────┘
                           │ repositories
┌──────────────────────────▼────────────────────────────┐
│ SQLite durable entities                              │
└───────────────────────────────────────────────────────┘
```

### EvidenceRuntime

拥有 RAG、资料上传、Research/RAG run、sources、source-code evidence 与 evidence recovery。GitHub/RAG/Web 是 Evidence Provider，不是第二运行时 truth owner。

### LearningSessionRuntime

拥有 chat/session、学习设置、memory interaction、LearningClosure、学习恢复与学习 artifact 编排。P2-D 领域对象逐步在这里形成稳定应用语义，但“合同已冻结”不等于“所有 UI/持久化已上线”。

`LearnerModelSnapshot` 是该 runtime 的有界只读 projection：它在读取时组合当前 LearningTruth、与当前目标匹配的 PedagogyEvalRun 汇总，以及 learner-profile 中已确认的 allowlist 内容。它没有独立持久化、写回或 mastery 推断权限。

### ExtensionRuntime

拥有 group/tool/workflow 等实验 capability。普通模式只有一个 `lab` surface；`group / tools / timeline` 作为 capability ID 存在不代表它们拥有独立 drawer surface。

### WorkspaceCoordinator

只负责真正跨域的 cancel/reset/cleanup 顺序，通过窄端口调用各 runtime；不得维护 Evidence/Learning/Extension 的第二份状态。

### 通用对话与研究的责任边界

- **模型**：语义理解、规划、研究与回答策略；模型输出的动作和声明均不自动获得执行或事实发布资格。
- **应用服务与运行宿主**：可信消息/附件绑定、真实来源读取、工具权限、持久操作身份、费用预留、中断恢复、正式发布判定。
- **研究**：Lookup / Standard / Deep 复用现有研究执行基础设施，静态知识快照与动态事件修订分开管理。动态事件只能提出修订，不能绕过证据门。
- **展示层**：区分已核验的正式答案与 provisional 的过程/阶段事件；智能 UI 组件只能展示受限数据和本地交互，不反向赋予证据资格。
- **学习专业场景**：在以上通用链路上组织 LearningClaim、LearningClosure、教学法和恢复流程，不建立第二套“事实真相”。

## 3. 状态真值

```text
SQLite durable truth
     ↑
application services
     ↑
React derived/view state
```

- SQLite：durable runtime truth；
- React：交互与派生 view state；
- Markdown：导出、资料、历史文本，不作为并发 runtime truth；
- Persona：表达与教学策略，不拥有学习 truth；
- cache：性能层，不升级成 durable truth。

详见 [`STATE_MODEL.md`](STATE_MODEL.md)。

## 4. 学习真值分层

```text
Truth Layer
  SourceEvidence / project decision / external fact
        ↓
Learning Layer
  Topic / Goal / Claim / Revision / Understanding / NextStep
        ↓
Pedagogy Layer
  explanation / exercise / validation strategy
        ↓
Persona Layer
  voice / pacing / examples / social style
```

下层不得反向改写上层。

## 5. P2-D Source Learning Pipeline

```text
Resolve exact repository commit
        ↓
SourceSnapshot (commit cache)
        ↓
RepositoryStructureIndex
        ↓
lexical match line
        ↓
innermost containing symbol
        ↓
Evidence Candidates
        ↓
deterministic convergence
        ↓
EvidenceSet
  Primary exactly 1
  Supporting 0..4
        ↓
LearningClaim / LearningHypothesis
```

### 自动探索边界

Primary symbol 只允许一跳自动结构扩展：direct caller/callee/import/implementation/test/config/contract。更深探索创建新的显式 evidence retrieval。严格机械 forwarding 可以穿透，但不能借“透传”名义跨业务分支、状态变更或语义变换。

## 6. CI / Validation 架构

```text
SourceEvidence (immutable source identity)
          │
          └── ValidationObservation (time-varying)
                 └─ GitHub Checks / workflow run / provider state
```

- exact-SHA association；
- CI failure/unavailable 不使 source invalid；
- SourceSnapshot/structure index 按 exact commit 强缓存；
- CI Observation 独立短 TTL，可显式刷新；
- 普通 source learning 不应等待/依赖 CI 刷新成功；
- 当前 P2-D-1 不引入 durable CI history。

## 7. Provider 与 truth domain

没有 `GitHub > RAG > Web` 这种全局优先级。

| Truth domain | 常见主证据 |
|---|---|
| implementation | exact-commit GitHub / runtime evidence |
| project_decision | 正式项目文档 / durable decision |
| external_fact | 权威 Web 来源 |

RAG 是“访问用户资料”的 provider，不是 truth domain。设计与实现冲突显示 divergence，不投票；同一域高质量来源仍无法解析则进入 EvidenceConflict。

## 8. LearningGoal 与恢复

Agent 不以聊天消息位置作为主恢复点。

```text
LearningResumePoint
├─ Topic
├─ active Goal
├─ last confirmed Claim
├─ current unresolved
├─ NextStep
└─ source context
```

首页信息层级：`NextStep → Goal → Topic`。只突出一个主要继续动作；Topic 目录与统计退居次级。

## 9. Evidence UI

三级渐进披露：

1. Claim + Primary symbol；
2. path/line + Supporting；
3. exact commit + CI Observation + Revision history。

移动端默认隐藏 SHA、完整 path 与深层审计信息。Study Agent 不是 IDE。

## 10. Persona

所有角色读取同一 durable learning state。角色可以选择不同解释、例子、语气、验证措辞，但不能重新裁决 truth/mastery/freshness。

## 11. 平台配置

平台配置必须单 owner：环境解析、origin normalization、危险组合拒绝等规则由明确 policy owner 维护；API assembly 只消费结果，不复制规则。

## 12. 退场能力

产品 surface 退场必须同时证明：route/UI/CSS/DOM class/compat naming/runtime owner 均不再承担生产责任。保留的 durable entity、API contract 或 capability 不自动证明旧 product surface 仍存在。
