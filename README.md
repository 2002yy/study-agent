# Study Agent

> **面向通用聊天与研究的 AI Agent**：目标是提供接近 GPT-6 Chat 的自然对话、自主研究、持续交互、智能界面、多模态输入和工具执行体验；**长期学习与教学是其上的专业场景**，而不是全部产品定义。
>
> [当前实际进度与唯一下一步](docs/PROJECT_STATUS.md) · [静态/动态双循环产品验收](docs/PRODUCT_ITERATION_POLICY.md) · [完整文档索引](docs/README.md) · [Agent 开发约束](AGENTS.md)

## 产品目标与工程边界

Study Agent 希望从“用户提问 → 生成文字”发展为可持续推进真实任务的 Agent：理解问题和后续补充，选择搜索、阅读和工具，结合证据更新回答，并以适当的交互界面呈现结果。

六项通用能力方向：

- **自然聊天**：多轮上下文、追问、纠错，以及中断后继续。
- **自主研究**：按需搜索、阅读、比较与核实来源；区分已知、未证实和冲突。
- **持续交互**：在任务执行中提供有用的阶段性内容，响应新增条件；阶段进度不能冒充正式答案。
- **智能界面**：让表格、图表及受控交互组件服务于实际问题，不以静态展示替代可操作性。
- **统一多模态**：将附件、文档、图片与消息正确关联；不能把“收到文件”当作“已理解文件”。
- **工具型 Agent**：模型提出行动和研究策略，程序负责真正调用工具、权限、预算、状态和结果回填。

**现状不是六项全都达到产品级验收。** 已有代码模块和自动测试只证明相应工程边界；新的对话循环尚需完成生产宿主接线（CL-M3），真实模型/搜索/工具/UI 联动的动态质量仍未取得产品 GO。进展、缺口、CI 和下一门只以 [PROJECT_STATUS](docs/PROJECT_STATUS.md) 为准，不能拿历史绿灯或展示视频推断当前体验。

**责任分工**：模型负责语义、规划与研究/回答策略；程序负责读取、工具执行、证据与引用资格、可恢复状态、费用上限以及正式发布。静态知识快照和动态事件修订使用不同的证据合同。

## 当前工程架构

```text
React / TypeScript（聊天、研究、学习界面）
    ↓ HTTP / SSE
FastAPI（接口与服务端授权）
    ↓
应用服务 / 有界对话与研究模块
├─ EvidenceRuntime（搜索、RAG、来源与证据）
├─ LearningSessionRuntime（聊天、学习状态与恢复）
└─ ExtensionRuntime（实验性工具与工作流）
    ↓
SQLite（会话、操作、证据与账本的持久状态）
```

此图是主要层级，**不是所有新模块均已接管生产请求的声明**。研究模块有 Lookup / Standard / Deep 分层；通用新对话循环与现有 `/chat` 兼容路径的具体接线资格见 [架构](docs/ARCHITECTURE.md) 和 [当前状态](docs/PROJECT_STATUS.md)。

## 一键启动与人工验收

Windows 下可直接双击 [`tools/start-study-agent.bat`](tools/start-study-agent.bat)，或在仓库根目录运行：

```powershell
.\tools\start-study-agent.bat
```

启动器会：

1. 读取 `.env`，在首次运行时创建 `.venv` 并按需安装前后端依赖；
2. 启动 Docker Desktop（若需要），并通过仓库固定 digest 的 Compose 基线复用/恢复仅绑定 `127.0.0.1:8080` 的 `study-agent-searxng`；
3. 启动 FastAPI `127.0.0.1:8000` 与 React/Vite `127.0.0.1:5173`；
4. 验证服务身份，显示后端、前端、SearXNG 和真实检索探针状态；
5. 输出桌面、窄屏、屏幕阅读器、对比度和实体手机人工检查清单，然后打开浏览器。

如果 Docker/SearXNG 暂时不可用，学习工作台仍会启动并明确显示联网研究降级；如果 `8080` 被非 SearXNG 服务占用，启动器会 fail-closed。普通启动不会更新或拉取镜像；首次迁移或未来 digest 升级必须显式运行 `tools\upgrade-searxng.bat`，由 `18080` candidate 通过健康与真实搜索后再切换。实体手机验收需要另行部署手机可达地址，并按 [`docs/MOBILE_ACCEPTANCE_D4D.md`](docs/MOBILE_ACCEPTANCE_D4D.md) 留下人工记录；本机一键启动不会冒充这项证据。

可选参数：

```powershell
.\tools\start-study-agent.bat -Install   # 强制刷新依赖
.\tools\start-study-agent.bat -NoBrowser # 启动但不自动打开浏览器
.\tools\manage-searxng.bat -Action Status -ProbeSearch # 查看固定版本与真实搜索状态
.\tools\upgrade-searxng.bat # 显式 candidate 升级；不会自动删除旧容器
```

SearXNG 的仓库配置、ignored secret/proxy layering、备份、回滚与 7 天 retained-container 清理流程见 [`docs/WEB_SEARCH_SETUP.md`](docs/WEB_SEARCH_SETUP.md)。

## 访问令牌（必填）

服务端现在要求每个私有 API 请求都带令牌；**没有配置令牌时所有私有接口返回 401**，包括本机访问。这不是可选加固，而是默认策略：反向代理可能让外部请求看起来来自 `127.0.0.1`，因此“只绑定本机”不能作为认证边界。

1. 在 `.env` 里设置一个足够长的随机值：`STUDY_AGENT_API_TOKEN=<你的令牌>`（可用 `python -c "import secrets;print(secrets.token_urlsafe(32))"` 生成）。
2. 重启后端。
3. 打开前端，在 **设置 → 访问令牌** 里粘贴同一个值并保存。

令牌只保存在你本机浏览器（localStorage），随请求以 `X-Study-Agent-Token` 发送；它**不会**被打进前端构建产物，也没有任何接口会在未认证时下发它。换浏览器或清理站点数据后需要重新粘贴。`/health` 与 `/assets/` 保持公开，否则页面无法加载到可以输入令牌的地步。

## 已整合能力与待验收边界

| 方向 | 已有工程能力 | 仍不能宣称 |
| --- | --- | --- |
| 聊天 / 生成 | 旧聊天兼容路径、受控模型生成、流式阶段事件与对话循环模块 | 新循环已经接管所有生产请求 |
| 联网研究 / 答案 | Lookup / Standard / Deep、读取事件、证据绑定、静态知识与动态修订合同 | 每次研究都能交付正确完整的正式答案 |
| 附件 / 工具 | 消息附件绑定与重试回归、受限计算及实验工具模块 | 所有图片、附件与工具均已通过真实模型联动 |
| 费用 / 恢复 | SQLite 持久状态、保守费用预留、重复请求拒绝与回归测试 | 已有完整费用结算/退款链路 |
| 智能 UI | 阅读、进度和受控交互组件，以及自动前端测试 | 已具有 ChatGPT 同级的模型驱动动态界面 |

工程成功与产品成功分别验收：静态循环用可重现的失败用例、测试和 CI 验证合同；动态循环需在用户授权与预算限制下跑真实任务，核对**用户真正看见的最终答案**，再与真实 ChatGPT 基准作公平比较。详见 [产品迭代规则](docs/PRODUCT_ITERATION_POLICY.md)。

### 长期学习场景

作为专业场景，已有学习会话、证据化理解验证、长期状态恢复等能力。源码学习的 `SourceEvidence`、`LearningClaim`、`LearningHypothesis` 等对象受 [领域模型](domain_models.md) 与 [状态不变量](state_invariants.md) 约束。学习记忆和教学角色不能代替通用聊天的事实核验与工具结果，也不能反向修改已确认的证据事实。

常规学习界面与 Lab 中的群聊、受控工具、诊断入口应区分；**存在实验模块不等于已正式发布**。

## 文档入口

| 需要了解 | 入口 |
|---|---|
| 当前做到哪里、下一步做什么 | [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md) |
| 文档治理与完整索引 | [`docs/README.md`](docs/README.md) |
| 当前架构与 owner | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |
| 领域对象与生命周期 | [`domain_models.md`](domain_models.md) |
| 必须永远成立的规则 | [`state_invariants.md`](state_invariants.md) |
| 状态持久化/临时状态边界 | [`docs/STATE_MODEL.md`](docs/STATE_MODEL.md) |
| RAG 与 evidence provider | [`docs/RAG.md`](docs/RAG.md) |
| 记忆系统 | [`docs/MEMORY_SYSTEM.md`](docs/MEMORY_SYSTEM.md) |
| 上下文层级 | [`docs/CONTEXT_TIERS.md`](docs/CONTEXT_TIERS.md) |
| 模型路由 | [`docs/MODEL_ROUTING.md`](docs/MODEL_ROUTING.md) |
| 性能与缓存 | [`docs/PERFORMANCE.md`](docs/PERFORMANCE.md) |
| 测试策略 | [`docs/TESTING.md`](docs/TESTING.md) |

旧 roadmap、旧迁移计划与旧架构文本统一保存在 [`docs/archive/`](docs/archive/)；它们只用于历史追溯，不再拥有当前进度或架构真值。

## 文档治理与当前任务

1. [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md) 是唯一当前进度与下一门入口。
2. [`docs/PRODUCT_ITERATION_POLICY.md`](docs/PRODUCT_ITERATION_POLICY.md) 是静态/动态双循环与产品验收的稳定合同。
3. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) 解释运行时与所有权；领域模型及不变量分别由对应文件维护。
4. 专项方案、旧路线图和有日期的实验记录保留作历史依据，不覆盖当前进度；完整索引见 [文档导航](docs/README.md)。

**接下来的工程门：CL-M3 生产宿主接线与真实行为验收。** 首先以不调用付费模型的替身检验实际路由、持久操作身份、中断/取消、恢复、费用预留及最终发布约束。只有在独立授权、持久预算和真实任务证据齐全后才进行动态比较。全量 L3 对最新 AR 集成仍是明确欠账；普通 CI 成功不等于 L3 或产品质量通过。

