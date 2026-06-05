# Technical Stack & Engineering Highlights

本文档梳理 Study Agent 的技术栈、核心技术点和适合对外展示的项目表述口径。

## 1. Project Positioning

Study Agent 是一个本地运行的 AI 学习助理系统，面向个人学习复盘、项目推进和知识整理场景。

它不是单纯的 AI 问答工具，而是围绕“长期学习陪伴”构建的一套轻量 Agent 架构，包含：

- 多 Provider LLM 接入
- 模型路由与性能模式
- Markdown 长期记忆
- 本地 RAG MVP
- 角色群聊式学习交互
- 联网新闻检索与来源追溯
- 课后总结与记忆候选写入
- 安全写入、日志批量落盘和 CI 质量门禁

一句话概括：

> A local-first AI learning assistant built with Streamlit and OpenAI-compatible APIs, featuring role-based group chat, Markdown long-term memory, model routing, source-traced web search, and CI-backed engineering safeguards.

---

## 2. Technology Stack

| Layer | Technology / Module | Responsibility |
|---|---|---|
| UI | Streamlit | 本地 Web App、聊天面板、微信群聊面板、侧边栏、状态栏、课后总结面板 |
| UI Performance | `st.fragment` | 拆分局部重渲染边界，降低整页 rerun 成本 |
| LLM Access | OpenAI Python SDK / OpenAI-compatible API | 统一接入 OpenAI、DeepSeek、OpenRouter、SiliconFlow、本地模型 |
| Config | `.env` + `python-dotenv` | 管理 Provider、API Key、base_url、模型名、timeout、max_retries |
| Runtime State | YAML + Markdown views | `config/runtime_state.yaml` 作为运行状态真源，同步 Markdown 视图 |
| Long-term Memory | Markdown files | 用 `summary.md`、`current_focus.md`、`learner_profile.md` 等文件保存长期记忆 |
| Context Control | fast / light / deep / archive tiers | 按性能模式选择不同记忆文件组，控制 token 成本 |
| Routing | Rule-based router + optional LLM router | 根据任务类型、用户选择和性能模式决定角色、学习模式和模型档位 |
| RAG MVP | `src/rag/*`, `src/ui/rag_panel.py`, `src/api.py`, JSON index | 本地 Markdown / TXT / DOCX / PDF 加载、分块、关键词 / 本地向量原型 / hybrid / backend-vector 检索、可配置 embedding provider、可选 Chroma adapter、引用上下文拼装、来源块、Streamlit 检索/调试面板、聊天注入和 FastAPI RAG endpoints |
| News Search | Feed registry / RSS / Google News / Bing News / RSSHub-style sources | 多源新闻聚合、源健康记录、去重、排序、来源追溯 |
| Article Extraction | `trafilatura`, `readability-lxml`, `lxml` | 新闻网页正文读取与降级解析 |
| Security | URL safety matrix, SSRF validation, redirect checks, secret scanning | 防止读取本地/内网资源，降低密钥误提交风险 |
| File Persistence | `safe_writer.py` | 临时文件写入、原子替换、覆盖前备份、PermissionError 重试 |
| Logging | Batched session logger | fast/standard/deep 按不同间隔批量 flush，减少频繁写盘 |
| Testing / Quality | pytest, ruff, mypy soft check, detect-secrets, GitHub Actions | 单元测试、Lint、非阻断类型检查、密钥扫描、CI 自动检查 |
| Packaging | `tools/package_project_helper.py` | 排除日志、缓存、密钥、本地数据和运行产物，生成可分发包 |

---

## 3. Core Engineering Highlights

### 3.1 Streamlit Fragment-based UI Architecture

`app.py` 作为轻量入口，负责页面配置、主题注入、状态初始化、健康检查和 UI 面板分发。项目将侧边栏、状态栏、单人聊天、微信群聊和课后总结拆分到不同模块，并使用 `st.fragment` 控制渲染边界。

价值：

- 避免所有交互都触发整页重渲染
- 降低聊天输入、状态栏刷新、侧边栏设置变化之间的耦合
- 让 `app.py` 保持入口编排职责，而不是变成巨型脚本

---

### 3.2 Multi-provider LLM Client

LLM 接入层通过 OpenAI-compatible API 封装统一调用方式，支持：

- OpenAI
- DeepSeek
- OpenRouter
- SiliconFlow
- Local OpenAI-compatible server

主要能力：

- 通过 `LLM_PROVIDER_PROFILE` 选择 Provider
- 各 Provider 使用独立环境变量前缀
- 支持 flash / pro 两档模型配置
- 支持 timeout、max_retries、temperature、max_tokens、response_format
- 支持 streaming 与非 streaming 两种调用方式
- 根据配置签名缓存 client，配置变化后自动重建

价值：

> 将模型供应商差异收敛到一个统一客户端，方便在成本、速度、质量和本地部署之间切换。

---

### 3.3 Model Routing & Performance Modes

项目提供 `fast`、`standard`、`deep` 三种性能模式，并结合 `flash` / `pro` 模型档位实现路由。

路由输入包括：

- 用户手动选择的角色、模式、模型
- 当前 performance mode
- 用户输入中的任务关键词
- 可选 LLM Router 结果

典型规则：

- 代码、bug、论文、架构、机制类任务更倾向使用 pro
- 复盘、总结、简单问答、闲聊类任务更倾向使用 flash
- fast 模式默认偏向低成本，但可以对高风险任务自动升档
- deep 模式优先使用更完整上下文和高质量模型

价值：

> 通过任务类型与性能模式动态选择模型，避免所有请求都走高成本模型，也避免复杂任务被低能力模型处理。

---

### 3.4 Markdown Long-term Memory

项目采用文件系统作为长期记忆存储，不依赖数据库或向量库。

主要记忆文件：

- `index.md`
- `current_focus.md`
- `summary.md`
- `learner_profile.md`
- `progress.md`
- `project_context.md`
- `task_board.md`
- `archive_summary.md`
- `agent.md`
- `system_detail.md`

记忆分层：

| Context Tier | Files | Purpose |
|---|---|---|
| fast | index + current focus | 极低成本，快速响应 |
| light | index + focus + summary + learner profile | 日常对话默认上下文 |
| deep | light + progress + project context + task board | 项目推进、复杂分析 |
| archive | deep + archive/system detail | 完整历史和系统级分析 |

价值：

> 用 Markdown 保持长期记忆可读、可编辑、可备份，同时通过 context tier 控制上下文规模和 token 成本。

---

### 3.5 Context Builder

上下文构建器负责将以下内容组装为 system prompt：

- 当前角色 prompt
- 学习模式规则
- 互动氛围
- runtime 内部状态
- 长期记忆文件
- 最近聊天历史窗口

它不是简单拼接全部历史，而是根据 context tier 选择记忆文件，并限制聊天历史窗口，避免上下文无限膨胀。

价值：

> 将角色、模式、状态和记忆统一装配为可控上下文，为后续模型路由和成本控制提供基础。

---

### 3.6 Role-based Group Chat

项目支持微信群聊式学习交互，多个角色围绕同一问题进行讨论。

核心模块：

- `wechat_state.py`：群聊状态、文件 I/O、生命周期管理
- `wechat_generator.py`：开场、互动回复、新闻讨论生成
- `wechat_prompt.py`：prompt 模板加载
- `wechat_format.py`：角色文本解析与格式修复
- `wechat_memory.py`：从群聊中提取长期记忆候选
- `wechat_panel.py`：Streamlit 群聊 UI
- `wechat.py`：兼容旧导入的 facade

价值：

> 用多角色讨论替代单一助手回答，让学习过程同时具备解释、质疑、复盘、鼓励和任务收束能力。

---

### 3.7 News Search Pipeline with Source Tracing

联网搜索链路：

```text
User query
  -> feed registry / RSS / News source fetch
  -> dedup + sort
  -> link resolution
  -> article text extraction
  -> LLM digest
  -> role-based group discussion
  -> source block + pipeline trace
```

链路还记录 feed health 和 pipeline trace：

- `logs/news_feed_state.json` 保存 feed 成功/失败、item_count、ETag、Last-Modified、错误类型和 seen entry key
- `src/news/pipeline.py` 将每条结果整理为 evidence level、跳转链、域名策略和 unsafe redirect 状态
- `src/news/audit.py` 为每轮新闻任务保存 JSON + Markdown 审计产物，便于复盘和调试
- source block 显示证据等级、跳转链数量、域名策略和真实来源域名

正文读取采用多级降级：

1. 本地 HTML 抓取
2. `trafilatura` 抽取正文
3. `readability-lxml` fallback
4. 原始段落文本 fallback
5. 可选 self-hosted reader fallback
6. 可选 hosted reader fallback
7. 失败时退回标题、来源和发布时间

价值：

> 将联网搜索结果转化为可追溯的摘要和群聊讨论，减少“只看标题就讨论”的不可靠输出。

---

### 3.8 SSRF Protection for Article Fetching

新闻正文读取模块内置 SSRF 防护：

- 仅允许 HTTP / HTTPS
- 拒绝 localhost
- 拒绝私网 IP、loopback、link-local、multicast、reserved、unspecified 地址
- 对域名进行 DNS 解析并校验解析结果
- 自定义 redirect handler，对每一跳重定向重新校验
- 限制最大重定向深度
- 限制正文读取字节数和字符数

边界：`link_resolver.py` 只做纯 URL 安全预检和重定向目标记录，不做 DNS 解析；真实网络读取进入 `article_fetcher.py` 时才执行 DNS/IP 校验。

价值：

> 在本地联网读取模块中加入基础安全边界，防止被恶意 URL 诱导访问本机或内网资源。

---

### 3.9 Safe Writer & Batched Logging

文件写入统一通过 `safe_writer.py`：

- 覆盖前自动备份
- 写入临时文件
- 原子替换目标文件
- PermissionError 重试
- finally 清理临时文件

会话日志采用批量 flush：

- fast 模式每 4 条 pending entry flush
- standard / deep 模式每 2 条 pending entry flush
- debug 模式每条 flush
- stale session 超时提醒
- 结束会话时完整保存 session log

价值：

> 减少文件损坏风险和频繁写盘开销，提高本地长期运行稳定性。

---

### 3.10 Local RAG MVP

当前 RAG 是一个可验证的本地 MVP，而不是完整向量库系统。

已实现：

- `.md` / `.markdown` / `.txt` / `.docx` / `.pdf` 文档加载
- 文本规范化、空文档拒绝和 PDF 安全边界（文件大小、页数、抽取文本长度、加密文件拒绝）
- 带 `source_path`、标题、chunk 序号和行号范围的分块
- 本地关键词 / TF-IDF-style 检索
- deterministic hash-vector 本地向量原型与 hybrid 检索模式
- `EmbeddingProvider` / `VectorBackend` 抽象，默认 local backend，可选 Chroma adapter，可显式配置 OpenAI-compatible embedding provider
- 简单中文 CJK bigram 匹配
- JSON index 保存与加载，默认路径为 `logs/rag_index.json`
- `build_rag_context()` 将检索结果拼装为带引用的 LLM 上下文块
- Streamlit `本地资料检索` 面板支持上传资料、输入本地路径、建立索引、检索和查看引用上下文
- Streamlit 面板显示当前索引、文档列表、chunk preview、检索参数和 score breakdown
- 单人聊天和微信群互动回复可通过 `用于聊天回答` 开关把检索结果注入 system prompt，并显示 RAG 引用来源块
- FastAPI `GET /health`、`POST /rag`、`POST /rag/index`、`POST /rag/query`

未实现边界：

- 默认仍是 local-first；生产 embedding 需要显式 API/env 配置，Chroma 需要额外安装 `chromadb`；FAISS、pgvector 或其他生产向量库仍未接入
- FastAPI 目前覆盖 health 和 RAG；`/chat`、`/memory` 仍是后续服务化任务
- 尚未自动注入所有生成路径；当前覆盖单人聊天和微信群互动回复，不覆盖新闻讨论或课后反馈

价值：

> 先用可测试、可引用、可回滚的本地检索链路打底，再逐步把本地向量原型替换为 embedding / vector store，避免在没有引用闭环前过早包装成完整 RAG。

---

### 3.11 CI, Testing & Packaging Guards

项目通过 GitHub Actions 自动运行：

- pytest
- ruff
- package helper
- detect-secrets（hard gate for unallowlisted findings）
- mypy soft check（当前本地 `python -m mypy --explicit-package-bases src` clean；CI 中仍作为非阻断检查运行）

自定义打包脚本会排除：

- `.env` 和环境变量文件
- logs / backups / exports / release / build 等运行产物
- chat archive
- pyc / tmp / bak / zip
- docx 和部分本地素材目录
- 可能包含密钥的文件内容

价值：

> 用 CI 和打包检查降低密钥泄露、运行产物误提交、缓存文件污染和格式回归风险。

---

## 4. Resume / Portfolio Wording

### Chinese Version

**Study Agent｜本地 AI 学习助理系统**

- 基于 **Python + Streamlit** 构建本地 AI 学习助理，拆分单人对话、角色群聊、课后总结、状态栏和侧边栏等 UI 模块，并使用 `st.fragment` 降低页面重渲染成本。
- 设计 **OpenAI-compatible 多 Provider LLM 接入层**，支持 OpenAI、DeepSeek、OpenRouter、SiliconFlow 与本地模型，通过 `.env` 管理 base_url、模型名、超时、重试和任务级 token 预算。
- 实现 **规则路由 + 性能模式** 的模型选择机制，根据用户输入、任务类型、手动配置和 fast / standard / deep 模式动态选择角色、学习模式与 flash / pro 模型。
- 设计基于 **Markdown 文件的长期记忆系统**，按 fast / light / deep / archive 分层读取 `summary`、`current_focus`、`learner_profile`、`project_context` 等上下文，降低 token 消耗。
- 实现 **本地 RAG MVP**，支持 Markdown / TXT / DOCX / PDF 加载、来源行号分块、关键词检索、本地向量原型、hybrid / backend-vector 检索、可配置 embedding provider、可选 Chroma adapter、引用上下文拼装、来源块、Streamlit 检索面板、单人聊天和微信群互动回复注入，并提供 FastAPI health / RAG endpoints；FAISS、pgvector 和更完整的来源面板仍作为后续演进。
- 实现 **联网新闻检索与群聊讨论链路**，支持 RSS 聚合、链接解析、正文抽取、LLM 摘要、角色讨论和来源追溯。
- 在网页正文抓取模块加入 **SSRF 防护**，校验 HTTP scheme、DNS 解析结果、私网 IP、loopback、reserved 地址和重定向目标，提高本地联网模块安全性。
- 封装 **安全文件写入工具**，通过临时文件、原子替换、覆盖前备份和 PermissionError 重试保障记忆与日志写入可靠性。
- 配置 **GitHub Actions CI**，集成 pytest、ruff、mypy soft check、detect-secrets 硬门禁和自定义打包检查，减少密钥误提交、运行产物误打包和格式回归风险。

### English Version

**Study Agent | Local AI Learning Assistant**

- Built a local AI learning assistant with **Python and Streamlit**, separating single chat, role-based group chat, after-session review, status bar and sidebar modules, with `st.fragment` used to reduce unnecessary UI reruns.
- Implemented a unified **OpenAI-compatible multi-provider LLM layer** supporting OpenAI, DeepSeek, OpenRouter, SiliconFlow and local models, with environment-based model, timeout, retry and token-budget configuration.
- Designed a **rule-based model routing system** with fast / standard / deep performance modes to dynamically select role, learning mode and flash / pro model tier based on task type and user configuration.
- Built a **Markdown-based long-term memory system** with fast / light / deep / archive context tiers to balance personalization and token cost.
- Implemented a **local RAG MVP** for Markdown / TXT / DOCX / PDF loading, source-line chunking, lexical retrieval, a local vector prototype, hybrid / backend-vector retrieval, configurable embedding providers, an optional Chroma adapter, citation-first context formatting, source blocks, a Streamlit retrieval panel, optional single-chat / WeChat interactive injection, and FastAPI health / RAG endpoints; FAISS, pgvector and a richer source panel remain planned.
- Implemented a **source-traced news pipeline** covering RSS aggregation, link resolution, article extraction, LLM digest generation and role-based group discussion.
- Added **SSRF protection** to the article-fetching module by validating URL scheme, DNS resolution results, private IP ranges and redirect targets.
- Encapsulated **safe file persistence** with temporary writes, atomic replacement, automatic backup and retry on permission errors.
- Configured **GitHub Actions CI** with pytest, ruff, mypy soft check, a detect-secrets hard gate and custom packaging guards to reduce regression, accidental secret commits and runtime-output packaging risks.

---

## 5. Display Priority

For README, resume and project defense, the recommended emphasis order is:

1. Multi-provider LLM client and model routing
2. Markdown long-term memory and context tiers
3. Local RAG MVP with citation-first retrieval
4. Role-based group chat interaction
5. News search pipeline with source tracing
6. SSRF protection for article fetching
7. Safe writer and batched session logging
8. Streamlit fragment-based UI optimization
9. CI, tests and packaging guards

---

## 6. Summary

Study Agent 的技术价值不在于“调用一个大模型 API”，而在于围绕本地学习场景补齐了长期记忆、模型路由、上下文分层、本地 RAG MVP、联网检索、安全边界、写入可靠性和 CI 工程化检查。

它更接近一个轻量级、local-first 的个人学习 Agent 原型，而不是普通聊天 demo。
