# 状态模型

> 本文档定义 Study Agent 中**每个文件**的角色归属：哪些是源码、哪些是用户数据、哪些是缓存、哪些可以删除、哪些换电脑要迁移。

---

## 1. 总览

```
项目根目录
├── 源码（进 Git，只读不改）
│   ├── app.py, src/*.py, tests/*.py
│   ├── config/routing_rules.yaml
│   ├── .env.example, requirements*.txt
│   ├── README.md, CHANGELOG.md, USER_GUIDE.md
│   ├── roles/*.md, templates/*.md
│   └── tools/*.ps1, tools/*.py
│
├── 配置模板（进 Git，运行后由用户派生）
│   └── .env.example → 用户复制为 .env
│
├── 真源（运行生成，不进 Git/包）
│   ├── config/runtime_state.yaml
│   └── memory/pending_updates/*.json
│
├── 视图（由真源同步，可改但会被覆盖）
│   ├── memory/internal_state.md
│   ├── memory/interaction_settings.md
│   └── chat/wechat_state.md
│
├── 用户数据（不进 Git，默认不进包）
│   ├── .env
│   ├── config/runtime_state.yaml
│   ├── memory/*.md（不含 pending_updates/）
│   ├── chat/*.md（不含 archive/）
│   └── assets/*（头像/背景/横幅）
│
├── 缓存/临时（可安全删除）
│   ├── logs/
│   ├── backups/
│   ├── memory/pending_updates/
│   └── *.bak, *.tmp
│
└── 打包产物（进 .gitignore）
    └── release/
```

---

## 2. 逐文件分类

### 2.1 源码（Source Code）

| 文件 | 说明 | 进 Git | 进包 |
|------|------|--------|------|
| `app.py` | Streamlit 入口 | 是 | 是 |
| `src/*.py` | 全部 Python 模块 | 是 | 是 |
| `tests/*.py` | 测试套件 | 是 | 可选 |
| `config/routing_rules.yaml` | 路由规则配置 | 是 | 是 |
| `.env.example` | 环境变量模板 | 是 | 是 |
| `requirements*.txt` | 依赖声明 | 是 | 是 |
| `roles/*.md`, `templates/*.md` | 角色人设和 Prompt 模板 | 是 | 是 |
| `tools/*.ps1`, `tools/*.py` | 打包/辅助工具 | 是 | 是 |
| `docs/*.md` | 设计文档 | 是 | 是 |
| `README.md`, `CHANGELOG.md`, `USER_GUIDE.md` | 项目文档 | 是 | 是 |

源码的特征：**提交后不改，不依赖运行时状态**。

### 2.2 配置模板 vs 用户配置

| 文件 | 真源 | 进 Git | 进包 | 可删除 |
|------|------|--------|------|--------|
| `.env.example` | 手动维护 | **是** | 是 | 否 |
| `.env` | 用户复制自 `.env.example` | **否** (.gitignore) | 否 (显式排除) | 是（需重新配） |

`.env` 是唯一承载 API Key、Base URL 等敏感信息的文件。
换电脑迁移时必须复制。

### 2.3 运行时状态（真源）

| 文件 | 真源角色 | 写入方 | 进 Git | 进包 |
|------|---------|--------|--------|------|
| `config/runtime_state.yaml` | **维一的运行时真源** | `mode_manager._write_runtime_state()` | **不应进** | 不推荐 |
| `memory/pending_updates/*.json` | 群聊记忆候选真源 | `wechat_memory.save_candidates()` | **否** (.gitignore) | 否 |

#### 真源层级说明

`config/runtime_state.yaml` 包含版本、运行模式、交互设置、微信群状态。
它的写入路径是：

```
mode_manager.update_*()
  → _apply_state_updates()
    → _write_runtime_state()     # 先写 YAML（真源）
      → _sync_runtime_state_markdown_views()  # 再同步到以下视图
```

**为什么 YAML 是真源？** 因为 YAML 结构化、可程序化读写；MD 视图仅供人工阅读和 Streamlit 展示。
**为什么不进 Git？** 因为 performance_mode、memory_mode、wechat_mode 等字段随每次使用变化，提交会产生噪音。

> **当前问题**：`.gitignore` 未排除 `config/runtime_state.yaml`，有意外提交风险。建议添加。

### 2.4 视图（View Only，由真源同步）

| 文件 | 真源来源 | 被谁读取 | 可手动编辑 |
|------|---------|---------|-----------|
| `memory/internal_state.md` | `config/runtime_state.yaml` → synced | `mode_manager._read_md_state_migration()` | 可改，但会被 YAML 覆盖 |
| `memory/interaction_settings.md` | 同上 | `mode_manager._read_md_state_migration()` | 同上 |
| `chat/wechat_state.md` | 同上 | `wechat_state.py` | 同上 |
| `memory/pending_updates/wechat_memory_candidates.md` | `.../*.json` | 人工预览 | 改也没用，JSON 是真源 |

这些视图的存在意义：**让人眼可读、让 Streamlit cache 可缓存**。修改视图不会影响真源，下次同步会覆盖。

### 2.5 用户数据（User Data）

| 文件 | 内容 | 进 Git | 进包 | 可恢复 | 迁移要求 |
|------|------|--------|------|--------|---------|
| `memory/index.md` | 记忆索引 | 示例可进 | 默认排除 | 有备份 | 需迁移 |
| `memory/current_focus.md` | 当前学习焦点 | 示例可进 | 默认排除 | 有备份 | 需迁移 |
| `memory/summary.md` | 学习摘要 | 示例可进 | 默认排除 | 有备份 | 需迁移 |
| `memory/learner_profile.md` | 学习者画像 | 示例可进 | 默认排除 | 有备份 | 需迁移 |
| `memory/progress.md` | 学习进度 | 示例可进 | 默认排除 | 有备份 | 需迁移 |
| `memory/project_context.md` | 项目上下文 | 示例可进 | 默认排除 | 有备份 | 需迁移 |
| `memory/task_board.md` | 任务看板 | 示例可进 | 默认排除 | 有备份 | 需迁移 |
| `memory/agent.md` | Agent 配置 | 示例可进 | 默认排除 | 有备份 | 需迁移 |
| `memory/system_detail.md` | 系统详情 | 示例可进 | 默认排除 | 有备份 | 需迁移 |
| `memory/archive_summary.md` | 归档摘要 | 示例可进 | 默认排除 | 有备份 | 需迁移 |
| `chat/wechat_group.md` | 群聊记录 | **否** (.gitignore) | 否 | 可恢复（有 archive） | 可选 |
| `chat/wechat_unread.md` | 未读消息 | **否** (.gitignore) | 否 | 丢 | 不迁 |
| `chat/archive/*.md` | 历史群聊归档 | **否** (.gitignore) | 否 (显式排除) | 是 | 可选 |
| `assets/*` | 头像/背景/横幅 | 建议不进（版权） | 否 (无扩展名排除) | 可重下 | 可选 |

**关于 memory 进 Git 的约定**：`memory/*.md` 未被 `.gitignore` 排除。项目的预期行为是：
- 示例/初始内容可提交一次进 Git
- 真实学习数据**不进 Git**（用户自行维护 `.gitignore` 或在 `git add` 时留意）
- 当前 `.gitignore` 只排除了 `memory/pending_updates/`

#### 写入链路

```
app.py (用户操作)
  → after_session / wechat_memory
    → memory_writer.append_memory() / .write_current_focus()
      → is_memory_write_allowed() 权限检查
        → safe_writer.safe_write_text()  # 先备份旧文件到 backups/，再原子写入
```

#### 恢复方式

1. **从 backups 恢复** — 每次 `safe_write_text` 写入前自动备份旧文件到 `backups/memory_backups/`
   ```bash
   python -m src.backup_manager             # 查看备份列表
   python -m src.backup_manager restore <name>  # 恢复
   ```
2. **从 chat/archive 重建** — 群聊历史在 `chat/archive/*.md`，可通过 LLM 重新提取记忆

### 2.6 会话/日志（可丢）

| 文件 | 内容 | 进 Git | 进包 | 可删除 |
|------|------|--------|------|--------|
| `logs/current/*.md` | 当前会话日志（实时写入） | **否** (.gitignore) | 否 | 安全删除 |
| `logs/sessions/*.md` | 已归档会话日志 | **否** (.gitignore) | 否 | 安全删除 |
| `logs/revision_notes.md` | 修订笔记 | **否** (.gitignore) | 否 | 安全删除 |
| `logs/session_archive.md` | 会话归档 | **否** (.gitignore) | 否 | 安全删除 |
| `st.session_state` (内存) | Streamlit 会话状态 | — | — | 页面刷新即丢 |

会话日志的写入链路：

```
app.py (对话)
  → session_logger.log()       # 追加到内存 _state
  → session_logger.flush_current_session()  # 按间隔刷到 logs/current/
  → session_logger.save()      # 归档到 logs/sessions/ + 清理 current/
```

**换电脑可以不迁 logs**。它们不是系统运行的必要状态。

### 2.7 备份（Cache）

| 文件 | 内容 | 进 Git | 进包 | 可删除 |
|------|------|--------|------|--------|
| `backups/memory_backups/*.bak` | 写入前自动备份 | **否** (.gitignore) | 否 | 安全删除 |
| `*.bak`, `*.tmp` | 残留临时文件 | **否** (.gitignore) | 否 | 安全删除 |
| `__pycache__/`, `.ruff_cache/` | Python/pyc 缓存 | **否** | 否 | 安全删除 |

备份是安全网，不是真源。删除不会丢数据，但会失去最近一次写入前的回滚点。

### 2.8 打包产物

| 路径 | 进 Git | 进包 |
|------|--------|------|
| `release/` | **否** (.gitignore) | — |

---

## 3. 真源层级汇总

```
                                   用户操作
                                       │
                                       ▼
                              st.session_state
                              (内存，页面刷新即丢)
                                       │
                          ┌────────────┴────────────┐
                          │                         │
                    config/                    memory/
               runtime_state.yaml        pending_updates/*.json
               ┌────┼────┐                     │
               │    │    │                     ▼
               ▼    ▼    ▼          pending_updates/*.md
          memory/  memory/  chat/       (视图)
        internal  interaction  wechat_
        _state.md _settings.md state.md
          (视图)    (视图)     (视图)

   memory/*.md ←─── after_session.py / memory_writer ←─── 权限检查
   chat/*.md  ←─── wechat_state.py / wechat_generator.py
   logs/*     ←─── session_logger.py

   backups/* ←─── safe_writer.py（自动备份旧文件）
```

### 读取优先级

各模块读取状态的顺序（以 `mode_manager` 为例）：

1. `st.cache_data(ttl=30)` → `load_runtime_modes()` 缓存结果
2. `_runtime_state_from_yaml()` → 读 `config/runtime_state.yaml`（真源）
3. 如果 YAML 不存在 → 回退 `_read_md_state_migration()` 从 `memory/internal_state.md` + `memory/interaction_settings.md` + `chat/wechat_state.md` 读取（迁移兼容）
4. 取默认值 `RuntimeModes()` 兜底

---

## 4. 运维操作指南

### 4.1 换电脑迁移

必须迁移的状态（丢则系统不完整）：

| 必须迁移 | 路径 | 原因 |
|---------|------|------|
| API 密钥 | `.env` | 无法连接 LLM |
| 长期记忆 | `memory/*.md`（不含 `pending_updates/`） | 学习历史丢失 |
| 运行时状态 | `config/runtime_state.yaml` | 可选，丢了可从默认重建 |

建议迁移：

| 建议迁移 | 路径 | 原因 |
|---------|------|------|
| 群聊历史 | `chat/`（含 `archive/`） | 学习讨论记录 |
| 视觉资源 | `assets/` | 头像/背景 |
| 角色印象 | `roles/*.md`（`### 对用户当前印象` 段） | 角色观察记录 |

不需要迁移：

| 不迁 | 原因 |
|------|------|
| `logs/` | 运行日志，对系统运行无用 |
| `backups/` | 安全网，到新机器重新生成 |
| `__pycache__/` | Python 会重建 |
| `release/` | 打包产物 |

### 4.2 安全删除（空间清理）

```bash
# 清空会话日志（最占空间）
rm -rf logs/current/*.md logs/sessions/*.md

# 清空备份
rm -rf backups/memory_backups/*.bak

# 清空临时文件
find . -name "*.bak" -delete
find . -name "*.tmp" -delete

# 清空未读消息（重启后重建）
echo "" > chat/wechat_unread.md
```

### 4.3 打包排除清单

`tools/package_project_helper.py` 的 `EXCLUDE_DIRS`：

```
__pycache__, .pytest_cache, .ruff_cache, .git, .github,
.vscode, .idea, venv, .venv, env, node_modules,
logs, backups, exports, release, dist, build, 图片资料
```

额外排除规则：
- `chat/archive/` — 历史群聊归档
- `*.pyc, *.pyo, *.bak, *.tmp` — 临时文件
- `.env, .env.*`（除非 `.env.example`）— 用户密钥
- `tools/package_project_v*.ps1` — 旧版打包脚本
- 含 `visual_assets_pack` 的路径

打包前还会扫描密钥模式（sk-*, ghp_*, sk-or-v1-*, api_key/token/secret 赋值）。

---

## 5. 当前已知问题

1. **`config/runtime_state.yaml` 未进 `.gitignore`** — 虽无敏感信息，但频繁变动不应提交。
2. **memory/*.md 示例/真实数据混用** — `.gitignore` 应增加 `memory/` 排除，或只留示例文件。
3. **chat/ 被 .gitignore 排除但 runtime_state.yaml 未排除** — 不一致。
4. **`memory/pending_updates/` 缓存的 JSON 与 MD 之间没有版本对应** — JSON 是真源，MD 是视图，但二者无显式关联约束。
5. **`memory/pending_updates/` 不自动清理** — 确认写入后，候选文件应删除或标记已处理，当前无此逻辑。

---

## 6. 推荐改进

```gitignore
# 在 .gitignore 中补充：
config/runtime_state.yaml
memory/
!memory/.gitkeep
```

同时为 `memory/` 添加一个 `.gitkeep` 保持目录结构，初始 memory 文件可作为示例通过 `git add --force` 选择性提交。
