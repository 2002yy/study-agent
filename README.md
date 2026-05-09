# Study Agent

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

编辑 `.env`：

```
OPENAI_API_KEY=your_api_key_here
OPENAI_BASE_URL=https://api.deepseek.com/v1
MODEL_FLASH_NAME=deepseek-v4-flash
MODEL_PRO_NAME=deepseek-v4-pro
DEFAULT_MODEL_PROFILE=pro
```

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
│   ├── health_check.py     # 健康检查
│   ├── export_tools.py     # 导出工具
│   ├── update_validator.py # 更新校验
│   ├── after_session.py    # 课后总结
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
│   ├── test_streaming.py           # 流式测试
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
- **v0.6.6** — 未知发言人渲染修复、并发写入安全。
- **v0.6.8** — 打包优化、文件锁重试、缓存机制。
- **v0.6.9** — 自由文本联网搜索、进度指示、记忆写入加固。
- **v0.7.1** — 三层正文提取降级、90 天搜索窗口、来源块压缩、摘要边界约束、prompt 乱码修复。

完整 Release 及下载见 [Releases](https://github.com/2002yy/-study-agent/releases)。

## 许可

仅供个人学习使用。
