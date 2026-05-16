# Study Agent

<p>
  <a href="https://github.com/2002yy/-study-agent/actions/workflows/ci.yml"><img src="https://github.com/2002yy/-study-agent/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/python-3.12-blue" alt="Python 3.12">
</p>

AI 学习搭子系统 —— 联网搜索 + 角色群聊 + 课后总结。

## 功能

- **单人学习对话** — 与 AI 一对一讨论学习内容
- **课后更新预览** — 总结学习进度，确认后写入记忆
- **微信群互动** — 四位角色（三月七、刻晴、纳西妲、流萤）群聊讨论
- **联网搜索** — 多源新闻聚合（Google News + Bing News + RSSHub），支持页面正文读取
- **来源追溯** — 搜索结果写入群聊记录，可回溯依据

## 快速开始

```bash
cd study-agent     # 进入项目目录
pip install -r requirements.txt
pip install -r requirements-dev.txt
cp .env.example .env
streamlit run app.py
```

浏览器打开 `http://localhost:8501`

## 环境配置

编辑 `.env`（完整模板见 `.env.example`）：

### Provider 选择

通过 `LLM_PROVIDER_PROFILE` 切换 LLM 提供商，支持 `openai` / `deepseek` / `openrouter` / `siliconflow` / `local`。每个 provider 读写自己的环境变量：

| Provider | API Key | Base URL | 默认 Base URL |
|---|---|---|---|
| `deepseek` | `DEEPSEEK_API_KEY` | `DEEPSEEK_BASE_URL` | `https://api.deepseek.com/v1` |
| `openrouter` | `OPENROUTER_API_KEY` | `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` |
| `siliconflow` | `SILICONFLOW_API_KEY` | `SILICONFLOW_BASE_URL` | `https://api.siliconflow.cn/v1` |
| `local` | `LOCAL_API_KEY` | `LOCAL_BASE_URL` | `http://127.0.0.1:8000/v1` |
| `openai` | `OPENAI_API_KEY` | `OPENAI_BASE_URL` | — |

每个 provider 的模型和连接参数：
- `{PROVIDER}_MODEL_FLASH_NAME` — flash 模型名
- `{PROVIDER}_MODEL_PRO_NAME` — pro 模型名
- `{PROVIDER}_DEFAULT_MODEL_PROFILE` — 默认模型档位（`flash`/`pro`）
- `{PROVIDER}_TIMEOUT_SECONDS` — 请求超时秒数
- `{PROVIDER}_MAX_RETRIES` — 最大重试次数

### 全局默认值

未设置 provider 级参数时回退到以下变量：
- `MODEL_FLASH_NAME` / `MODEL_PRO_NAME` — 模型名
- `DEFAULT_MODEL_PROFILE` — 默认档位（默认 `flash`）
- `LLM_TIMEOUT_SECONDS` — 全局超时（默认 `30`）
- `LLM_MAX_RETRIES` — 全局最大重试（默认 `2`）
- `LLM_MAX_TOKENS` — 全局最大 token 数

### 任务级覆盖

内置任务（`llm_router` `after_session`）有硬编码默认值，可通过环境变量覆盖：

| 任务 | 默认 max_tokens | 默认 timeout | 默认 temperature |
|---|---|---|---|
| `llm_router` | 240 | 20s | 0.0 |
| `after_session` | 1200 | 45s | 0.3 |

覆盖方式：`{TASK_KEY}_MAX_TOKENS` / `{TASK_KEY}_TIMEOUT_SECONDS` / `{TASK_KEY}_TEMPERATURE`（如 `AFTER_SESSION_MAX_TOKENS=1200`）。

### 解析链

每个参数按以下优先级解析：
1. 代码调用传入的显式参数
2. 任务级环境变量（如 `AFTER_SESSION_MAX_TOKENS`）
3. 任务硬编码默认值（`_TASK_DEFAULTS`）
4. 全局环境变量（如 `LLM_MAX_TOKENS`）
5. provider 级环境变量（如 `DEEPSEEK_TIMEOUT_SECONDS`）

## 项目结构

```
├── app.py                  # Streamlit 入口
├── requirements.txt        # 运行依赖
├── requirements-dev.txt    # 开发/测试依赖
├── .env.example            # 环境变量模板
├── USER_GUIDE.md           # 用户指南
│
├── src/
│   ├── llm_client.py       # LLM 调用（chat / stream）
│   ├── llm_router.py       # 模型路由分发
│   ├── context_builder.py  # 上下文构建
│   ├── mode_manager.py     # 模式管理（性能/互动氛围）
│   ├── role_manager.py     # 角色加载与管理
│   ├── session_logger.py   # 会话日志
│   ├── session_store.py    # 会话持久化
│   ├── safe_writer.py      # 安全文件写入
│   ├── backup_manager.py   # 备份管理
│   ├── wechat.py           # 微信群聊 + 联网搜索 + 新闻摘要
│   ├── wechat_memory.py    # 微信群记忆提取
│   ├── memory.py           # 记忆系统
│   ├── memory_tools.py     # 记忆工具
│   ├── memory_writer.py    # 记忆写入
│   ├── model_stats.py      # 模型用量统计
│   ├── perf.py             # 性能日志
│   ├── router.py           # 路由配置
│   ├── config.py           # 全局配置
│   ├── constants.py        # 公共常量
│   ├── text_utils.py       # 文本工具
│   ├── log_utils.py        # 日志工具
│   ├── health_check.py     # 健康检查
│   ├── export_tools.py     # 导出工具
│   ├── update_validator.py # 更新校验
│   ├── after_session.py    # 课后总结
│   ├── news/
│   │   └── article_extractor.py  # 文章正文提取（三层回退）
│   └── ui/
│       ├── main_panel.py        # 主页
│       ├── chat_panel.py        # 对话面板
│       ├── sidebar.py           # 侧边栏
│       ├── wechat_panel.py      # 微信群面板
│       ├── wechat_bubble.py     # 微信气泡渲染
│       ├── after_session_panel.py # 课后总结面板
│       ├── status_bar.py        # 状态栏
│       ├── session_state.py     # 会话状态
│       ├── theme.py             # 主题
│       └── avatar.py            # 头像
│
├── tests/
│   ├── test_wechat.py              # 微信/新闻搜索测试
│   ├── test_wechat_article_extract.py # 文章提取测试
│   ├── test_after_session.py       # 课后总结测试
│   ├── test_v03_accept.py          # 验收测试
│   └── test_packaging_guards.py    # 打包校验测试
│
├── chat/                  # 群聊记录
│   ├── wechat_group.md    # 当前群聊
│   ├── wechat_state.md    # 群聊状态
│   ├── wechat_unread.md   # 未读消息
│   └── archive/           # 历史群聊归档
│
├── memory/                # AI 记忆系统
│   ├── learner_profile.md # 学习者画像
│   ├── project_context.md # 项目上下文
│   ├── progress.md        # 学习进度
│   ├── summary.md         # 学习摘要
│   ├── current_focus.md   # 当前焦点
│   ├── task_board.md      # 任务看板
│   ├── internal_state.md  # 内部状态（版本号等）
│   ├── system_detail.md   # 系统详情
│   ├── agent.md           # Agent 配置
│   └── pending_updates/   # 待确认更新
│
├── roles/                 # 角色人设
│   ├── march7.md          # 三月七
│   ├── keqing.md          # 刻晴
│   ├── nahida.md          # 纳西妲
│   ├── firefly.md         # 流萤
│   └── references/        # 角色背景资料
│
├── templates/             # Prompt 模板
│   ├── wechat_update.md             # 群聊生成
│   ├── wechat_interactive_reply.md  # 互动回复
│   ├── wechat_memory_extract.md     # 记忆提取
│   └── routing_rules.md             # 路由规则
│
├── config/
│   └── routing_rules.yaml # 路由规则配置
│
├── tools/
│   ├── package_project.ps1      # 打包脚本
│   └── package_project_helper.py
│
├── assets/                # 静态资源（头像/背景/图标）
│
├── logs/                  # 运行日志
│
└── backups/               # 备份文件
```

## 版本历史

- **v0.1 ~ v0.6.3** — 早期探索阶段。界面仅纯文本、按钮触发全页刷新、侧边栏与主区域不同步、无视觉资源、自动路由缺失、群聊格式简陋。问题过多，未发布 Release。
- **v0.6.4** — 首次可用的正式包：Catppuccin 暗色主题、紫蓝渐变、微信气泡 UI、路由系统、会话隔离、safe_writer。
- **v0.6.5** — 开场氛围选择、角色归一化兜底、侧栏与 memory 对齐、打包脚本拆分。
- **v0.6.6** — 未知发言人渲染修复、并发写入安全、打包测试对齐。
- **v0.6.7** — 刷新逻辑拆分、notice queue、健康检查只读化、打包排除增强、lru_cache 缓存。
- **v0.6.8** — .tmp 排除、文件锁重试 finally 清理、LLM client 自动重建、wechat_state 批量写入、新闻 10 分钟缓存。
- **v0.6.9** — 自由文本联网搜索、进度指示、新闻缓存按 query 隔离、记忆写入加固。
- **v0.7.0** — 多源 RSS 聚合、正文三层提取、来源块写入群聊、摘要边界约束、URL 安全检查。
- **v0.7.1** — 90 天搜索窗口、来源块压缩、摘要覆盖率提示、prompt 乱码修复、覆盖率统计对齐。
- **v0.7.2** — 代码质量全面收口：修复 4 个 Bug、性能优化（缓存/YAML/diff）、架构改善（常量去重/模块拆分）、Streamlit fragment 反模式修复、关键路径错误处理增强。
- **v0.7.3** — 服务层拆分与工程化收口：Wechat news round 下沉到 `src/wechat_service.py`、session flush 批量提交、GitHub Actions CI、架构级测试、LLM client 参数扩展、YAML runtime state 真源化。详见 `changelog/README_v0_7_3.md`。
- **v0.7.4** — 工程体验收口：自动化版本 bump 工具、LLM 配置文档化（`.env.example` 5 个 provider）、NewsRoundResult 结果对象化（覆盖率/警告/耗时）、UI 来源可信度展示。详见 `changelog/README_v0_7_4.md`。
- **v0.7.5** — 文档同步收口 + 代码清理：版本信息同步 10 个文件、死代码清理（chat_stream / 重复函数）、YAML 同步 mtime canary 优化、重复逻辑合并。详见 `changelog/README_v0_7_5.md`。
- **v0.7.6** — 工程安全与新闻链路收口：
  - 加固 `.gitignore` 与打包密钥排除规则
  - 修复侧栏 HTML 动态内容转义问题
  - 重构新闻抓取链路，避免 RSS 阶段过早解析跳转链接
  - 补强新闻正文抓取的 URL 安全边界（DNS/IP 校验）
  - 修正无效 monkeypatch 测试，增强 CI 验收覆盖
- **v0.7.7** — 规划中。

完整 Release 及下载见 [Releases](https://github.com/2002yy/-study-agent/releases)。

## 许可

仅供个人学习使用。
