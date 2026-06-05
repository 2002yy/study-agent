# Study Agent 优化方向与版本路线图

> 本文档记录 Study Agent 后续优化方向。目标不是继续堆功能，而是把项目从 Streamlit 原型整理成一个可演示、可测试、可部署、可写进简历的 AI 应用工程项目。

## 1. 项目定位

Study Agent 建议定位为：

> 本地优先的 AI 学习助理系统，支持长期记忆、课程资料检索、多模型接入、学习会话总结和可追踪知识沉淀。

这个定位要区别于普通聊天机器人，重点突出：

- 本地优先：学习资料、记忆文件、会话记录可控。
- 长期记忆：支持学习进度、用户偏好、当前目标的持续沉淀。
- RAG 检索：能够基于本地知识库和上传资料回答问题。
- 多模型接入：通过 OpenAI-compatible Provider 抽象适配不同模型。
- 会话总结：每轮学习结束后能生成总结与待写回记忆。
- 可追踪：回答来源、记忆写回、会话日志、测试结果都应可追踪。

## 2. 总体优化主线

后续优化分为六条主线：

1. 产品主线收束
2. 架构解耦
3. 性能优化
4. 记忆与 RAG 升级
5. 前端产品化
6. 工程化交付与简历包装

当前最重要的不是继续增加娱乐化角色或复杂按钮，而是先把核心链路稳定下来：

```text
用户输入
→ UI 接收
→ 读取长期记忆
→ 检索本地知识库
→ 构建上下文
→ 选择模型 Provider
→ 调用模型并流式输出
→ 展示引用来源
→ 会话总结
→ 用户确认写回长期记忆
```

## 3. P0：产品主线收束

### 3.1 主线功能

优先保证以下闭环可稳定演示：

- 用户能进行学习对话。
- 系统能读取当前学习目标和长期记忆。
- 系统能按需检索本地资料。
- 回答能展示引用来源。
- 下课后能总结本轮学习内容。
- 记忆写回需要用户确认，避免自动污染长期记忆。

### 3.2 降级为特色功能的内容

以下功能可以保留，但暂时不作为主线核心：

- 群聊角色
- 亲近/陪伴风格
- 新闻闲聊
- 多角色表演
- 复杂 UI 皮肤

这些功能适合作为产品特色，但不应干扰“本地学习助理 + 长期记忆 + RAG”的主线。

## 4. P0：架构解耦

Streamlit 可以继续保留作为原型 UI，但业务逻辑必须逐步抽离。建议目录结构如下：

```text
study_agent/
├─ app_streamlit/          # Streamlit UI，只做展示层
├─ core/                   # 核心业务逻辑
│  ├─ chat_engine.py
│  ├─ context_builder.py
│  ├─ memory_manager.py
│  ├─ rag_service.py
│  ├─ tool_router.py
│  └─ session_service.py
├─ providers/              # 模型接入层
│  ├─ base.py
│  ├─ openai_compatible.py
│  ├─ mock_provider.py
│  └─ provider_config.py
├─ tools/                  # 工具能力
│  ├─ web_search.py
│  ├─ news_fetcher.py
│  ├─ file_reader.py
│  └─ summarizer.py
├─ memory/                 # Markdown / JSON memory
├─ rag/                    # 向量库、索引、文档切分
├─ tests/
├─ docs/
└─ README.md
```

核心原则：

- Streamlit 不直接管业务逻辑。
- UI 只负责输入、展示、按钮和状态反馈。
- ChatEngine 负责对话主流程。
- ContextBuilder 负责上下文组合。
- MemoryManager 负责记忆读写、备份、diff、回滚。
- Provider 层负责模型调用。
- ToolRouter 负责工具路由。
- RAGService 负责知识库入库、检索和引用来源。

## 5. P0：性能优化

### 5.1 Memory 读取优化

Streamlit 每次交互都会 rerun，不能每轮全量读取所有 memory 文件。

建议：

- 启动时读取 MemorySnapshot。
- 记录每个 memory 文件的 mtime。
- 文件未变化时复用缓存。
- 写回时局部更新。
- 对大型归档文件按需读取，不进入每轮默认上下文。

建议抽象：

```text
MemorySnapshot
- profile
- current_focus
- progress
- revision_notes
- session_summary
- loaded_at
- file_mtime_map
```

### 5.2 日志写入优化

不要每条消息后立即重写完整 session 文件。

建议：

- 聊天中写入内存 buffer。
- 每 N 条消息批量 flush。
- 点击“下课”时完整归档。
- 异常退出时写 crash recovery。

### 5.3 上下文构建分层

上下文不要每次都塞满历史和全部记忆。建议分层：

| 层级 | 内容 | 每轮是否必带 |
|---|---|---|
| fast context | 用户画像、当前学习目标 | 是 |
| recent context | 最近几轮对话摘要 | 是 |
| retrieved context | RAG 检索结果 | 按需 |
| archive context | 历史归档 | 很少 |
| debug context | 调试信息 | 只在开发模式 |

### 5.4 首 token 体验优化

用户点击发送后要立刻看到反馈：

```text
正在读取长期记忆...
正在检索知识库...
正在调用模型...
正在生成回答...
```

即使总耗时没有明显下降，也能显著改善交互感。

## 6. P1：长期记忆系统升级

### 6.1 记忆分类

建议将长期记忆分为：

| 类型 | 内容 |
|---|---|
| 用户画像 | 学习偏好、技术方向、当前阶段 |
| 长期目标 | 求职方向、项目路线 |
| 项目状态 | 当前项目版本、待办、里程碑 |
| 学习进度 | Java、RAG、前端、Godot 等方向 |
| 会话摘要 | 每次学习后的总结 |
| 待确认记忆 | AI 建议写入但需要用户确认的内容 |

### 6.2 人工确认式写回流程

推荐固定流程：

```text
本轮对话结束
→ LLM 提取候选记忆
→ 按类型分类
→ 显示 diff
→ 用户确认
→ SafeWriter 写入
→ 生成写回日志
```

设计目标：避免 LLM 自动写入导致记忆污染。

### 6.3 版本与回滚

建议 memory 目录：

```text
memory/
├─ current/
│  ├─ profile.md
│  ├─ progress.md
│  └─ current_focus.md
├─ archive/
│  ├─ 2026-06-03_session.md
│  └─ ...
└─ backups/
   ├─ profile_20260603_103000.md
   └─ ...
```

每次写入前备份一次，出现记忆污染时可以回滚。

## 7. P1：RAG 闭环升级

Study Agent 后续的核心竞争力应该来自 RAG，而不是普通聊天。

最小闭环：

```text
上传文件
→ 解析文本
→ 切分 chunk
→ 生成 embedding
→ 存入向量库
→ 用户提问
→ 检索相关 chunk
→ 回答时展示引用来源
```

优先支持文件类型：

- Markdown
- txt
- PDF
- docx
- 代码文件

向量库建议：

| 阶段 | 方案 |
|---|---|
| 原型 | FAISS / Chroma |
| 后端项目化 | pgvector |
| 大规模扩展 | Milvus |

回答必须带来源，例如：

```text
参考来源：
1. docs/java_backend.md，第 3 节
2. uploads/rag_notes.pdf，第 5 页
3. memory/current_focus.md
```

## 8. P1：工具调用优化

工具能力建议分三类：

1. 信息获取工具：网页搜索、新闻、文档读取。
2. 学习辅助工具：总结、出题、错题整理、计划生成。
3. 项目辅助工具：README 生成、代码分析、测试清单生成。

推荐调用链：

```text
用户问题
→ IntentRouter 判断类型
→ 需要工具则调用工具
→ 工具结果进入 ContextBuilder
→ LLM 生成最终回答
```

不要让模型无限制自由调用工具，而是先用可控路由实现稳定 Agent 工作流。

## 9. P8：FastAPI 服务化

不建议立刻推翻 Streamlit。推荐三步走：

### 阶段 1：保留 Streamlit，抽 core

```text
Streamlit UI → core/chat_engine.py
```

### 阶段 2：增加 FastAPI

当前基础接口已经落地：

```text
GET  /health
POST /chat
POST /memory/preview
POST /memory/commit
POST /rag/upload
POST /rag/query
GET  /rag/status
POST /rag/local-knowledge
GET  /sessions
POST /sessions/{session_id}/flush
```

仍需补齐：streaming chat、auth、CORS、统一错误响应、OpenAPI 示例和 Docker 部署配置。

### 阶段 3：补前端

前端建议进入 P9 后使用 React + Vite + TypeScript。理由是：

- React 生态更适合后续做聊天流、引用面板、调试抽屉和状态组件拆分。
- Vite 开发服务器启动快，生产构建输出静态 `dist`，可以独立部署，也可以由 FastAPI 挂载静态目录。
- TypeScript 能把 API response、RAG source、memory preview、session row 等数据结构固定下来，减少前后端联调时的隐性字段漂移。

最低页面：

| 页面 | 作用 |
|---|---|
| 聊天页 | 主交互 |
| 文件上传页 | RAG 入库 |
| 知识库列表 | 查看已导入资料 |
| 来源引用面板 | 展示 RAG 证据 |
| 会话历史 | 查看过往学习记录 |
| 设置页 | Provider、模型、API Key、本地路径 |
| 调试面板 | 查看上下文、token、耗时、检索结果 |

## 10. P2：UI 与产品体验

推荐布局：

```text
左侧：会话 / 知识库 / 模式
中间：聊天主窗口
右侧：记忆状态 / 引用来源 / 调试信息
底部：输入框 + 工具按钮
```

回答卡片可以拆为：

```text
回答正文
关键点
引用来源
建议下一步
可写入记忆候选
```

必须补齐的状态：

| 状态 | 示例 |
|---|---|
| loading | 正在思考、正在检索 |
| error | API 失败、网络失败、文件解析失败 |
| empty | 没有知识库、没有会话 |
| success | 上传成功、写入成功 |
| warning | 检索结果不足、上下文过长 |

## 11. P2：测试体系

必备测试：

| 测试类型 | 测试内容 |
|---|---|
| Provider 测试 | OpenAI-compatible 调用、Mock Provider |
| Memory 测试 | 读取、写入、diff、备份、回滚 |
| RAG 测试 | chunk、入库、检索、引用来源 |
| Tool 测试 | 新闻检索、文件读取、摘要 |
| ContextBuilder 测试 | 不同模式下上下文是否正确 |
| API 测试 | /chat、/health、/rag/query、/rag/upload、/rag/status、/memory/preview、/memory/commit、/sessions |
| UI smoke 测试 | 页面能打开、基本交互不崩 |

最关键的是 Mock Provider。真实模型用于演示和实际使用，Mock Provider 用于自动测试和 CI，避免测试依赖外部 API。

## 12. 文档体系补齐

建议 docs 目录补齐：

```text
docs/
├─ 01_项目立项与定位.md
├─ 02_需求说明_PRD.md
├─ 03_架构设计.md
├─ 04_长期记忆设计.md
├─ 05_RAG设计.md
├─ 06_Provider抽象设计.md
├─ 07_API接口文档.md
├─ 08_测试计划与测试报告.md
├─ 09_部署说明.md
├─ 10_Release_Notes.md
└─ 11_待升级补强清单.md
```

其中最适合支撑简历的是：

- 架构设计
- 长期记忆设计
- RAG 设计
- Provider 抽象设计
- 测试报告
- 部署说明

## 13. 推荐版本路线

### v0.7：稳定化版本

目标：先把现有原型收口。

任务：

1. 抽离 core/chat_engine.py
2. 抽离 memory_manager.py
3. 抽离 provider 层
4. 优化 memory 缓存
5. 优化 session 日志批量写入
6. 补 Mock Provider
7. 补基础测试
8. 整理 README

### v0.8：RAG 闭环版本

目标：升级为真正的学习资料助手。

任务：

1. 支持 Markdown / txt / PDF 上传
2. 文档切分 chunk
3. 向量检索
4. 回答附来源
5. 知识库列表
6. RAG 回归测试
7. 编写 docs/RAG设计.md

### v0.9：FastAPI 服务化版本

目标：从 Streamlit 原型转向软件系统。

任务：

1. [x] 增加 FastAPI
2. [x] 实现 /health
3. [x] 实现 /chat（当前为非流式）
4. [x] 实现 /rag/upload
5. [x] 实现 /rag/query
6. [x] 实现 /memory/preview
7. [x] 实现 /memory/commit
8. [x] 补 API 测试
9. [ ] 补 streaming chat / auth / CORS / Docker Compose

### v1.0：前端产品化版本

目标：能演示、能截图、能部署、能写简历。

任务：

1. React + Vite + TypeScript 前端
2. 聊天页
3. 文件上传页
4. 知识库列表页
5. 来源引用面板
6. 会话历史
7. 设置页
8. Docker 一键启动
9. 完整 Release Notes

## 14. 简历包装方向

可以包装为：

> Study Agent：本地优先的 AI 学习助理与知识库系统。基于 FastAPI、OpenAI-compatible Provider、RAG、Markdown 长期记忆和前端聊天界面，实现多模型接入、学习资料检索、长期记忆写回、来源引用展示和会话归档；设计 Provider 抽象、ContextBuilder、MemoryManager 和 ToolRouter 等模块，并通过 Mock Provider、RAG 回归测试和 CI 保证核心链路稳定。

核心亮点：

1. 多模型 Provider 抽象
2. 长期记忆写回与人工确认机制
3. RAG 知识库检索与来源引用
4. FastAPI + 前端 + Docker + 测试的工程化交付

## 15. 当前最建议执行的下一步

当前主流程已经可以按 FastAPI 边界继续收口：

```text
用户输入
→ Streamlit 或 Web UI 接收
→ FastAPI /chat
→ memory 读取
→ context 构建
→ local knowledge tool 判断
→ provider 调用
→ response 输出
→ session 记录
→ memory 写回确认
```

推荐推进顺序：

1. [x] Provider 抽象稳定
2. [x] Memory / ContextBuilder 基础稳定
3. [x] SessionLogger 批量写入
4. [x] RAG MVP 与 local knowledge tool
5. [x] FastAPI 基础服务层
6. [ ] streaming chat / auth / CORS / Docker
7. [ ] React + Vite + TypeScript 前端
