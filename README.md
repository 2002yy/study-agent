# Study Agent

> **个人学习工作台**：长期保持“正在学什么、已经确认什么、还不会什么、下一步是什么”。
>
> 当前进度唯一入口：[`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md)。

Study Agent 不是把聊天记录长期堆积起来的 Chatbot，也不是让多个角色各自维护一套“记忆真相”的角色扮演系统。当前产品主线是把学习过程收敛为可恢复、可验证、可追溯的学习状态：

```text
教学 / 练习
→ 资料与证据
→ 理解验证
→ 已确认 / 未解决
→ 下一步
→ 整理、恢复与继续学习
```

## 当前运行时

```text
React
  ↓
FastAPI
  ↓
Application Runtimes
├─ EvidenceRuntime
├─ LearningSessionRuntime
└─ ExtensionRuntime
  ↓
SQLite durable entities
```

- **React**：当前交互面。
- **FastAPI**：生产 API 与应用服务入口。
- **SQLite durable entities**：运行时事实来源。
- **EvidenceRuntime**：RAG、上传、外部研究、源码证据与恢复端口。
- **LearningSessionRuntime**：会话、聊天、学习设置、记忆、LearningClosure 与学习恢复。
- **ExtensionRuntime**：群聊、受控工具、工作流等实验能力；普通模式只通过单一 Lab 入口访问。

详细 owner 边界见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)。

## 一键启动与人工验收

Windows 下可直接双击 [`tools/start-study-agent.bat`](tools/start-study-agent.bat)，或在仓库根目录运行：

```powershell
.\tools\start-study-agent.bat
```

启动器会：

1. 读取 `.env`，在首次运行时创建 `.venv` 并按需安装前后端依赖；
2. 启动或复用 FastAPI `127.0.0.1:8000` 与 React/Vite `127.0.0.1:5173`（端口可指定，前端不会自动漂移）；
3. 验证当前前端标题、后端身份与前端API代理就绪，然后打开浏览器；
4. 在后台启动 Docker Desktop（若需要），通过固定 digest 的 Compose 基线复用/恢复仅绑定 `127.0.0.1:8080` 的 `study-agent-searxng`，不阻塞工作台打开；
5. 显示运行/配置状态和人工检查清单；实际联网探针可在设置或manager中另行执行。后台服务日志在 `logs/launcher/`。

如果 Docker/SearXNG 暂时不可用，学习工作台仍会启动并明确显示联网研究降级；如果 `8080` 被非 SearXNG 服务占用，启动器会 fail-closed。普通启动不会更新或拉取镜像；首次迁移或未来 digest 升级必须显式运行 `tools\upgrade-searxng.bat`，由 `18080` candidate 通过健康与真实搜索后再切换。实体手机验收需要另行部署手机可达地址，并按 [`docs/MOBILE_ACCEPTANCE_D4D.md`](docs/MOBILE_ACCEPTANCE_D4D.md) 留下人工记录；本机一键启动不会冒充这项证据。

可选参数：

```powershell
.\tools\start-study-agent.bat -Install   # 强制刷新依赖
.\tools\start-study-agent.bat -NoBrowser # 启动但不自动打开浏览器
.\tools\start-study-agent.bat -BackendPort 8001 -FrontendPort 5174 # 指定另一组端口
.\tools\start-study-agent.bat -SkipSearXNG # 本次只启动应用，保留已有检索配置
.\tools\manage-searxng.bat -Action Status -ProbeSearch # 查看固定版本与真实搜索状态
.\tools\upgrade-searxng.bat # 显式 candidate 升级；不会自动删除旧容器
```

SearXNG 的仓库配置、ignored secret/proxy layering、备份、回滚与 7 天 retained-container 清理流程见 [`docs/WEB_SEARCH_SETUP.md`](docs/WEB_SEARCH_SETUP.md)。

本机桌面 `Study Agent 一键启动.cmd` 调用同一仓库入口，默认8001/5174，定位当前验证实例；脚本从自身目录寻找 `study agent`，参数和失败退出码均透传。已有8000/5173实例不会被停止。本机Docker当前有engine.sock故障，桌面默认复用健康SearXNG但不自动拉起Docker，现有备用检索配置继续有效；修复Docker后可向桌面入口传 `-StartSearXNG` 显式后台启动。仓库入口仍按上述默认流程后台准备搜索服务。

## 已完成的核心学习闭环

P2-D 源码学习与验证、P2-E 自动化验收均已进入 `main`。核心原则：

- `SourceEvidence` 固定到 exact commit / file / symbol / line，不被 CI 临时状态污染；
- CI 是独立的 `ValidationObservation`，失败或不可用不自动使源码证据失效；
- `LearningClaim` 使用受限 EvidenceSet：1 个 Primary + 0–4 个 Supporting；
- 用户掌握、源码 freshness、记忆 retention 是三个不同维度；
- 没有可靠 Primary Evidence 时只能形成 `LearningHypothesis`，不能伪装成正式 Claim；
- Persona 只改变教学表达，不改变 truth、evidence、mastery 或 freshness；
- GitHub / RAG / Web 都是 Evidence Provider，不存在全局“来源优先级”。

完整合同见 [`domain_models.md`](domain_models.md) 与 [`state_invariants.md`](state_invariants.md)。

## 产品面

普通用户稳定入口：

- 学习会话；
- 资料与来源；
- 学习成果；
- 设置。

实验能力：

- 群聊；
- 受控工具；
- 开发者诊断。

实验能力统一从 **Lab** 进入，默认休眠。旧 News 独立产品面与旧 Extension drawer 兼容 surface 已退出；仍保留的 durable workflow / capability 不等于独立产品面。

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

## 文档治理规则

1. `docs/PROJECT_STATUS.md` 是唯一当前进度 owner。
2. 不再新增并列的 `STATUS` / `ROADMAP` / `NEXT_PHASE` / `AUDIT` 长期入口。
3. 当前架构事实进入 `docs/ARCHITECTURE.md`；领域语义进入 `domain_models.md`；硬约束进入 `state_invariants.md`。
4. 专项文档只描述自己的子系统，不宣布全局当前阶段。
5. 历史计划保留，但必须明确标记为 archive/reference。

## 当前开发状态

P2-D 与 P2-E 自动化批次已经完成；实体手机、真实屏幕阅读器与视觉对比度仍待人工验收。Learner Model 目前只有只读派生 API，没有 UI 或长期画像写回。联网 provider 与快速查询预算已有自动证据，但 2026-08-26 实测发现明确研究意图仍可能落入零正文读取的摘要路径；当前按 SX1 → RQ1 → G17-LAN 顺序修复。实时基线、证据和下一切片只看 [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md)。
