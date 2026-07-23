# Study Agent

<p>
  <a href="https://github.com/2002yy/study-agent/actions/workflows/ci.yml"><img src="https://github.com/2002yy/study-agent/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/python-3.12-blue" alt="Python 3.12">
</p>

A local-first AI learning workbench: pedagogy-driven study sessions with a
visible learning state, traceable evidence, and long-term memory.

## One-minute Overview

Study Agent 不是又一个 AI 问答工具，而是把 LLM 接入完整的学习闭环：识别学习阶段、验证你的理解、指出缺口，并在确认后沉淀长期记忆。

- **教学法驱动**：苏格拉底 / 费曼 / 项目 / 普通四种教学协议，配合学习状态机、学习者应答评估和掌握度门控
- **学习状态可见**：左侧为会话列表，学习目标/阶段/已确认点/缺口压缩在对话顶部可展开的学习状态条
- **证据可追溯**：本地 RAG 引用 + 模型自主联网搜索/阅读，每条回答下方可展开证据轨迹
- **跨会话恢复**：学习状态、逐轮证据、中断生成都能准确恢复
- **长期记忆**：Markdown memory + safe writer，课后总结确认后写入
- **多 Provider LLM 接入**：OpenAI / DeepSeek / OpenRouter / SiliconFlow / local models
- **工程安全**：SSRF protection、detect-secrets、配置模板、pytest / Ruff / CI

## Highlights

- **Pedagogy-driven learning**: Socratic / Feynman / Project / Direct protocols over a learning-state machine, with learner-response evaluation and mastery gating
- **Visible learning state**: objective, phase trail, confirmed points, current gap, and this-turn pedagogical move in a persistent learning panel
- **Traceable evidence**: local RAG citations plus model-directed web search/read, expandable under each answer; per-turn evidence survives refresh
- **Cross-session recovery**: learning state, per-turn evidence, and interrupted generation all restore accurately
- **Long-term memory**: tiered Markdown memory with safe preview/commit writer
- **Multi-provider LLM client**: OpenAI / DeepSeek / OpenRouter / SiliconFlow / local models with context-tier routing
- **Local knowledge base**: Markdown / TXT / DOCX / PDF indexing, lexical / hybrid / vector / backend-vector retrieval, configurable embeddings, optional Chroma
- **Engineering safety**: SSRF protection, detect-secrets in CI, pytest / Ruff / mypy / GitHub Actions
- **Performance budget**: mode-based `max_tokens` bounds on chat, group-chat, and news LLM paths

For a detailed breakdown of the stack and engineering highlights, see [Technical Stack & Engineering Highlights](docs/TECH_STACK.md).

---

**一个本地优先、证据可追溯、能够持续推进学习目标的 AI 学习工作台** — 支持角色群聊、联网搜索、长期记忆和课后总结。

> 不是又一个 AI 问答工具，而是一个会识别学习阶段、验证理解、追溯证据并沉淀记忆的学习工作台。

---

## 为什么做这个

通用 AI 对话工具擅长回答问题，但不擅长「陪伴学习」：

- 它们不知道你**当前学到哪个阶段**，也无法验证你是否真的理解
- 它们不记得你**昨天**学了什么、**上周**卡在了哪里
- 它们不会主动帮你**总结**学习进展并把知识沉淀下来

Study Agent 的定位很明确：**一个运行在你本地的、教学法驱动的 AI 学习工作台**。它用四种教学协议（苏格拉底引导、费曼诊断、项目推进、普通讲解）配合学习状态机持续推进你的学习目标，必要时调用本地资料和联网证据，每轮回答都可追溯依据，课后总结确认后写入长期记忆。角色群聊和新闻研究是延伸的学习空间，而非主入口。

---

## Why It Is Not Just a Prompt Demo

普通 AI demo 通常只是把用户输入转发给模型。Study Agent 重点解决的是：

| 问题 | 工程方案 |
|---|---|
| 模型供应商更换困难 | Provider profile + OpenAI-compatible client |
| 上下文越来越长 | context-tier routing |
| 学习记录无法沉淀 | Markdown long-term memory |
| 写入记忆不安全 | safe writer + preview/confirm |
| 联网内容不可追溯 | source-traced news pipeline |
| 运行不稳定 | caching, batched logging, tests, CI |

---

## Demo

| 界面 | 截图 |
|------|------|
| 首页 — 状态看板、当前重点、版本信息 | ![home](assets/screenshots/home.png) |
| 微信群聊 — 三位角色群内讨论 | ![group-chat](assets/screenshots/group-chat.png) |
| 联网搜索 — 多源新闻聚合与来源追溯 | ![news-search](assets/screenshots/news-search.png) |
| 记忆候选 — 课后更新预览与确认写入 | ![memory-capture](assets/screenshots/memory-capture.png) |

---

```
建立学习目标
    │
    ├── 教学法推进（苏格拉底 / 费曼 / 项目 / 普通）
    │       │
    │       ├── 本地 RAG 检索 ──-> 引用来源
    │       └── 模型自主联网 ──-> 搜索 / 阅读 / 来源追溯
    │       │
    │       └── 证据按教学协议受控披露 -> 生成回答（下方可展开证据轨迹）
    │
    ├── 验证理解 -> 记录已确认点 / 当前缺口 / 阶段推进
    │
    └── 课后总结 -> 确认 -> 写入长期记忆 -> 下次准确恢复
```

---

## 核心功能

| 功能 | 说明 |
|------|------|
| **教学法驱动学习** | 苏格拉底 / 费曼 / 项目 / 普通四种教学协议 + 学习状态机 + 学习者应答评估 + 掌握度门控 |
| **学习状态可见** | 左侧会话列表导航；学习目标/阶段轨迹/已确认点/缺口/本轮动作在对话顶部可展开条 |
| **证据可追溯** | 本地 RAG 引用 + 模型自主联网搜索/阅读，每轮回答下方展开证据轨迹 |
| **跨会话恢复** | 学习状态、逐轮证据、中断生成均可恢复继续 |
| **本地知识库** | Markdown / TXT / DOCX / PDF 索引；lexical / hybrid / vector / backend-vector 检索；文档管理与删除 |
| **长期记忆** | current_focus / progress / summary / learner_profile / project_context，safe writer 预览确认写入 |
| **课后总结** | 学习完成后生成总结候选，用户确认后写入记忆 |
| **角色群聊（延伸）** | 四位角色（三月七、刻晴、纳西妲、流萤）群聊讨论，延伸学习空间 |
| **新闻研究（延伸）** | 多源聚合 + 正文提取 + LLM 摘要 + 来源追溯 |
| **多 Provider** | OpenAI / DeepSeek / OpenRouter / SiliconFlow / 本地模型 |

---

## 架构

当前主架构是 **React + FastAPI + application services + SQLite**。
Streamlit 入口（`app.py`）已移除，`src/ui` 待清理；前端统一为 React。迁移状态的唯一事实源见
[Architecture Status](docs/ARCHITECTURE_STATUS.md)。

![architecture](assets/screenshots/arch.png)

```text
React feature controllers
        ↓
FastAPI routes
        ↓
Application services
        ↓
Repositories / SQLite / provider gateways
```

---

## 快速开始

```bash
git clone <repo-url> study-agent
cd study-agent
cp .env.example .env
# 编辑 .env，填入 API Key

# 初始化记忆文件（新用户首次运行，应用会自动创建；也可手动复制模板）
cp -r memory.example/* memory/ 2>/dev/null || :

# 稳定安装（推荐，锁定版本）
pip install -r requirements.txt
pip install -r requirements-dev.txt

tools\start-study-agent.bat
```

浏览器打开 `http://127.0.0.1:5173`。旧 Streamlit 入口仅用于兼容验证。

### 依赖管理

本项目使用 [pip-tools](https://github.com/jazzband/pip-tools) 管理依赖：

- [`requirements.in`](requirements.in) / [`requirements-dev.in`](requirements-dev.in) — **人类维护**，写范围版本
- [`requirements.txt`](requirements.txt) / [`requirements-dev.txt`](requirements-dev.txt) — **自动生成**，写精确版本（lock 文件）

修改依赖后重新生成 lock 文件：

```bash
pip install pip-tools
pip-compile requirements.in        # 重新锁定主依赖
pip-compile requirements-dev.in    # 重新锁定开发依赖
```

---

## 环境配置

通过 `LLM_PROVIDER_PROFILE` 切换 LLM 提供商（`openai` / `deepseek` / `openrouter` / `siliconflow` / `local`），每个 provider 读写独立的环境变量：

| Provider | 环境变量前缀 | 默认 Base URL |
|----------|-------------|---------------|
| `deepseek` | `DEEPSEEK_*` | `https://api.deepseek.com/v1` |
| `openrouter` | `OPENROUTER_*` | `https://openrouter.ai/api/v1` |
| `siliconflow` | `SILICONFLOW_*` | `https://api.siliconflow.cn/v1` |
| `local` | `LOCAL_*` | `http://127.0.0.1:8000/v1` |
| `openai` | `OPENAI_*` | — |

参数优先级：代码显式参数 → 任务级环境变量 → 任务默认值 → 全局环境变量 → provider 级环境变量。完整配置见 [`.env.example`](.env.example) 和 [用户指南](USER_GUIDE.md)。

RAG 向量后端默认使用 `local`，不需要额外服务；可选 `chroma` adapter 需要用户自行安装 `chromadb`。Embedding provider 默认 `local_hash`，生产检索可显式切到 OpenAI-compatible embeddings：

```bash
RAG_VECTOR_BACKEND=local
# RAG_VECTOR_BACKEND=chroma
# RAG_CHROMA_PATH=logs/chroma
# RAG_CHROMA_COLLECTION=study_agent

# Deterministic test/offline fallback only.
RAG_EMBEDDING_PROFILE=local_hash
RAG_EMBEDDING_PROVIDER=local_hash
# Production multilingual profile.
# RAG_EMBEDDING_PROFILE=openai_multilingual
# RAG_EMBEDDING_PROVIDER=openai
# RAG_EMBEDDING_MODEL=text-embedding-3-small
# RAG_EMBEDDING_DIMENSIONS=1536
# RAG_EMBEDDING_API_KEY=...
# Optional local reranker with explicit budgets.
RAG_RERANKER=disabled
# RAG_RERANKER=lexical_overlap
# RAG_RERANK_TOP_N=20
# RAG_RERANK_LATENCY_BUDGET_MS=250
# RAG_RERANK_COST_BUDGET=0
```

---

## 项目结构

```
├── src/
│   ├── llm_client.py       # LLM 调用（chat / stream）
│   ├── llm_router.py       # 模型路由分发
│   ├── context_builder.py  # 上下文构建
│   ├── mode_manager.py     # 模式管理（版本/性能/氛围）
│   ├── api.py              # FastAPI health / chat / memory / sessions / RAG / tools / workflows endpoints
│   ├── role_manager.py     # 角色加载与管理
│   ├── performance_budget.py # 性能预算（max_tokens 分级）
│   ├── memory.py           # 记忆系统
│   ├── memory_tools.py     # 记忆工具
│   ├── memory_writer.py    # 记忆写入
│   ├── wechat_format.py    # 群聊文本格式化
│   ├── wechat_state.py     # 群聊 I/O、状态管理
│   ├── wechat_generator.py # LLM 生成逻辑
│   ├── wechat_prompt.py    # Prompt 模板加载
│   ├── wechat_memory.py    # 群聊记忆提取
│   ├── after_session.py    # 课后总结
│   ├── session_logger.py   # 会话日志
│   ├── config.py           # 全局配置
│   ├── router.py           # 路由配置
│   ├── news/               # 新闻聚合链路
│   ├── rag/                # 本地 RAG MVP：加载、分块、索引、关键词/向量原型/embedding/可选后端检索
│   ├── tools/              # 受控工具边界：本地知识检索等
│   └── ui/                 # Streamlit UI 组件
├── tests/                  # pytest 测试套件
├── frontend/               # React + Vite + TypeScript console
├── docs/                   # 设计文档与工程说明
│   ├── TECH_STACK.md       # 技术栈与项目亮点
│   ├── RAG.md              # RAG MVP 状态与边界
│   └── STATE_MODEL.md      # 状态模型
├── chat/                   # 群聊记录
├── memory/                 # AI 长期记忆
├── roles/                  # 角色人设
├── templates/              # Prompt 模板
├── config/                 # YAML 配置
├── requirements.in         # 依赖声明（范围版本）
└── assets/                 # 视觉资源
```

---

## 测试

```bash
pytest tests/ -v
pytest tests/ --cov=src     # 覆盖率
ruff check src/ tests/      # linting
mypy --explicit-package-bases src/  # type check
```

CI 通过 GitHub Actions 在 push / pull request 上运行，集成 `pytest`、`ruff`、打包检查、`detect-secrets` 扫描，以及 `mypy` soft check。当前验证状态见 [docs/TESTING.md](docs/TESTING.md)。

---

## 版本历史

### v0.8.0 — 文档同步 + UI 中文标签 + 工程收口

文档版本同步（5 份文档统一升级）；UI 中文标签（模型/性能/状态栏全中文）；合并性能预算系统、依赖锁定、状态模型文档化、CI 门禁升级、入口页新闻流程修复。当前验证状态见 [docs/TESTING.md](docs/TESTING.md)。

### v0.7.8 — 性能预算 + 状态模型 + 工程收口

### v0.7.7 — 模块拆分与服务层解耦

新闻链路拆分为 4 个专注模块 + 兼容门面；服务层直连子模块；UI 逐阶段新闻流；SSRF 安全加固；Session logger 自动 flush 保护。**112 tests，Ruff clean**。

### v0.7.6 — 工程安全与新闻链路收口

完整历史见 [CHANGELOG.md](CHANGELOG.md)。

---

## Roadmap

| 版本 | 方向 |
|------|------|
| v0.8.1 | 稳定性和 UI 打磨 |
| v0.9 | 知识库 / RAG 能力 |
| v0.10 | 多语言支持、导出增强 |
| v1.0 | 插件化架构 + 自定义角色 |

---
## Engineering Roadmap

求职导向的技术演进路线：

- [x] FastAPI service layer foundation: `/health`, `/chat`, `/memory/preview`, `/memory/commit`, `/sessions`, `/rag`, `/rag/index`, `/rag/query`, `/rag/status`, `/rag/upload`, `/rag/local-knowledge`, `/tools` and `/workflows/runs` implemented; optional local API token and CORS allowlist implemented; streaming and broader deployment hardening remain planned
- [x] RAG MVP: Markdown / TXT / DOCX / PDF loading, chunking, local keyword retrieval, local vector prototype, hybrid retrieval, backend-vector retrieval, configurable embedding provider, optional Chroma adapter, controlled local-knowledge retrieval, citation context, source blocks, Streamlit retrieval panel, optional single-chat and WeChat interactive injection
- [ ] RAG document QA (partial): PDF parsing has file-size, page-count, extracted-text and encrypted-file guards; production embedding requires explicit API/env configuration and Chroma remains optional
- [ ] Vector store: Chroma optional adapter implemented; FAISS local prototype and pgvector engineering version remain planned
- [x] P8.4 evaluation sets foundation: retrieval, answer grounding, tool routing, workflow events and safety regression cases before expanding agentic behavior
- [x] P8.5 execution foundation: workflow run / step / event JSONL timeline plus controlled local-knowledge tool use behind typed schemas, permissions and audit logs
- [x] P9 web UI: React + Vite + TypeScript console implemented with non-streaming chat, document upload/indexing, source table, workflow timeline detail, controlled tool preview/call and memory status panels; streaming chat, auth, CORS and production static hosting remain planned
- [ ] P10 hardening and integration: optional local auth/CORS implemented; Docker, OpenAPI examples, optional read-only MCP server, trace_id, token usage, latency, provider fallback logs and streaming remain planned
- [ ] P11 optional RPA: browser automation as a future read-first adapter for no-API learning systems, gated by domain allowlists and human confirmation


## 许可

仅供个人学习使用。
