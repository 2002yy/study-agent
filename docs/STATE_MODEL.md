# Study Agent 状态与数据模型

> **文档类别：稳定数据参考，不是当前进度入口。**  
> 当前项目状态统一查看 [`PROJECT_STATUS.md`](PROJECT_STATUS.md)。

本文定义当前 React + FastAPI + SQLite 架构下，各类状态的 authoritative owner、持久化位置、恢复语义、迁移要求和可删除边界。

## 1. 真值层级

Study Agent 不再以单个 YAML 或前端内存作为全局真源。不同状态由不同 owner 管理：

```text
用户输入 / UI 操作
        │
        ├─ 前端临时 UI 状态
        │    reducer / controller / localStorage cache
        │
        ├─ 服务端运行真值
        │    SQLite ChatThread / Runs / Evaluation / IndexState
        │
        ├─ 长期学习记忆
        │    用户确认后的 Markdown memory
        │
        ├─ 本地知识库
        │    document revisions / chunks / active index
        │
        └─ 配置与密钥
             .env + checked-in templates/rules
```

核心原则：

1. 前端状态是展示和恢复缓存，不是服务端业务真值；
2. SQLite 是会话、运行流程、评估和索引状态的 authoritative runtime store；
3. Markdown memory 是用户确认后的长期学习记忆；
4. RAG 文档、revision、chunk 和 active index 有独立生命周期；
5. `.env` 是用户密钥和 Provider 配置，不进入 Git；
6. legacy YAML/Markdown 状态只用于兼容迁移，不承接新功能。

## 2. 源码与仓库内容

| 类别 | 示例 | Git | 分发包 |
|---|---|---|---|
| Python 源码 | `src/**/*.py` | 是 | 是 |
| React/TS 源码 | `frontend/src/**/*` | 是 | 是 |
| 后端测试 | `tests/**/*.py` | 是 | 可选但推荐 |
| 前端测试 | `frontend/src/**/*.test.*` | 是 | 可选但推荐 |
| API/角色/模板 | `roles/`, `templates/`, checked-in config | 是 | 是 |
| 依赖声明 | `requirements*.in/txt`, frontend lockfile | 是 | 是 |
| 文档 | `README.md`, `USER_GUIDE.md`, `docs/` | 是 | 是 |
| CI/工具 | `.github/workflows/`, `tools/` | 是 | 是 |

源码文件不应被运行时流程改写。

## 3. 配置与密钥

| 数据 | Owner | Git | 迁移到新电脑 |
|---|---|---|---|
| `.env.example` | 仓库模板 | 是 | 随仓库 |
| `.env` | 用户 | 否 | 需要重新配置或安全迁移 |
| Provider profile | runtime settings/config loader | 模板可进，真实值不进 | 需要 |
| routing rules | checked-in config | 是 | 随仓库 |
| frontend display settings | server settings + local UI cache | 用户数据 | 可选 |

`.env` 可包含 API Key、Base URL、模型名和本地服务地址。密钥不得进入日志、SQLite evidence、Markdown memory 或前端持久化快照。

## 4. SQLite runtime truth

数据库路径由 `runtime_database_path()` 和 `RuntimeDatabase` 统一解析，不在业务模块中硬编码。

### 4.1 Durable entities

| Entity | 责任 |
|---|---|
| `ChatThread` | 会话状态、settings snapshot、committed learning state |
| `ChatTurn` | 用户/助手消息、完成状态、route/RAG/pedagogy snapshot |
| `GroupThread/Message` | 群聊生命周期、消息、未读和归档 |
| `NewsRun` | 新闻搜索、正文、摘要和讨论阶段 |
| `ToolRun` | 工具参数、预览、确认和结果 |
| `MemoryRun` | 记忆候选、hash、预览、commit 结果 |
| `RagRun` | query/upload/rebuild 的 durable 状态 |
| `WebLookupRun` | 查询上下文、尝试、来源评估、阶段和停止原因 |
| `PedagogyEvalRun` | 学习者主张评估、证据、版本和 final decision |
| `rag_index_states` | active/staging index version 和写入租约 |
| `operations` | 异步 operation scope 和 owner |

### 4.2 事务不变量

- completed ChatTurn、committed learning state 和对应 PedagogyEvalRun 保持一致；
- interrupted/failed turn 不得覆盖 committed objective、phase 或 gap；
- MemoryRun commit 必须校验 preview/hash；
- RAG 新版本只有必需阶段通过才激活；
- run 的 stage transition 使用 expected state/version；
- completed、partial、failed、cancelled 和 empty evidence 不能混用；
- 新建会话不自动归档旧会话。

## 5. Ordered migrations

SQLite 使用 `SCHEMA_VERSION`、`MIGRATIONS` 和 `runtime_migrations` ledger。

每个 migration 必须：

1. 使用新的连续版本号；
2. 在 `BEGIN IMMEDIATE` 事务内执行；
3. 兼容已有数据库；
4. 为新增非空字段提供默认值；
5. 对历史状态做诚实回填；
6. 失败时记录 failed migration，不伪装完成；
7. 有针对 completed、failed、running/interrupted 历史数据的回归测试。

示例：研究字段在 schema 14 加入；schema 15 将旧版残留 `running` WebLookupRun 标记为 `legacy_run_interrupted`，避免误记成空结果。

## 6. 前端状态

### 6.1 React reducer/controller

前端可维护：

- active thread/run ID；
- 当前 drawer；
- input、展开状态、选择项；
- controller busy/error；
- streaming partial reply；
- compact API snapshot。

这些状态用于交互，不得独立决定服务端 run 已完成或学习状态已推进。

### 6.2 localStorage

localStorage 只允许保存可重建的 UI 恢复信息，例如 active run ID、display settings 和草稿。刷新后必须从 FastAPI/SQLite 重新读取 durable truth。

禁止保存：

- API Key；
- 完整敏感本地文档；
- 被当作 authoritative 的 learning mastery；
- 无法与服务端版本校验的 commit 状态。

## 7. 长期 Markdown memory

Markdown memory 的价值是可读、可编辑、可备份。它不是运行中间状态数据库。

典型文件：

- `index.md`；
- `current_focus.md`；
- `summary.md`；
- `learner_profile.md`；
- `progress.md`；
- `project_context.md`；
- `task_board.md`；
- `archive_summary.md`。

写入链路：

```text
LearningClosure / explicit memory request
-> MemoryRun preview
-> user confirm
-> hash/version check
-> safe writer backup + atomic replace
-> commit result persisted
```

规则：

- 未经用户确认不写；
- learner profile 推断默认 pending；
- 运行失败、中断或低置信度评估不写成已掌握；
- 示例 memory 可进仓库，真实用户 memory 默认不进 Git；
- backups 是恢复安全网，不是当前真源。

## 8. RAG 用户数据

RAG 数据分为：

1. 原始上传或本地文件；
2. stable document identity；
3. content/parser revision；
4. normalized chunks；
5. embedding/vector backend 数据；
6. active/staging index state；
7. RagRun 运行记录。

删除文档必须同时处理 local index 和配置的 vector backend。失败重建不得替换 active index。

临时附件和长期知识库的完整生命周期仍需保持独立：临时附件不能因会话结束误删长期资料，也不能默认进入长期记忆或云端模型上下文。

## 9. 会话、日志和审计

| 数据 | 是否真源 | 是否可删除 |
|---|---|---|
| SQLite durable runs/threads | 是 | 否，除非明确清空用户数据 |
| Markdown long-term memory | 是，针对长期记忆 | 否，除非用户明确删除 |
| RAG active index | 可重建但影响运行 | 可删除后重建 |
| application logs | 否 | 通常可删除 |
| debug traces | 否 | 可删除 |
| generated audit reports | 历史证据 | 可归档 |
| backups | 恢复安全网 | 可删除，但失去回滚点 |
| frontend cache | 否 | 可安全删除 |
| `__pycache__`, `.ruff_cache`, build output | 否 | 可安全删除 |

日志不得成为产品状态的唯一记录。用户需要恢复的流程必须持久化为对应 Run。

## 10. Legacy compatibility

以下状态模型只用于旧入口兼容：

- Streamlit `st.session_state`；
- `config/runtime_state.yaml`；
- `memory/internal_state.md`；
- `memory/interaction_settings.md`；
- `chat/wechat_state.md`；
- 旧 Markdown 会话归档。

兼容读取可以存在，但新功能不得写入这些文件作为唯一真源。迁移完成后删除 legacy 前，必须提供：

- 新 owner；
- 数据迁移或安全默认值；
- replacement tests；
- 用户备份说明。

## 11. 换电脑/备份建议

必须迁移：

- `.env` 中仍需使用的 Provider 配置；
- SQLite runtime database；
- 真实 Markdown memory；
- 用户上传的知识文件；
- 无法重建或成本较高的 vector index；
- 自定义角色、模板和用户资源。

通常不必迁移：

- Python/Node cache；
- frontend build output；
-临时日志；
- 可重新生成的测试和打包产物。

迁移前应停止应用，保证 SQLite 和 safe writer 没有正在进行的写操作。

## 12. 数据安全规则

1. 用户数据、密钥和运行数据库默认不进 Git。
2. public repository 提交前运行 detect-secrets。
3. 对外导出包排除 `.env`、SQLite 用户库、memory、uploads、logs 和 backups。
4. 外发模型上下文遵守 web/cloud context policy。
5. 标记为禁止云端的资料不得进入远程 Prompt。
6. EvidenceTrail 可记录来源类型和 Provider，但不保存完整敏感正文。
7. 删除、reset、rebuild 和 archive 等破坏性动作需要明确确认。
