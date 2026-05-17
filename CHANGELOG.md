# Changelog

## v0.7.8 — 性能预算 + 状态模型 + 工程收口

- **性能预算系统**（新模块 `src/performance_budget.py`）：所有 LLM 调用按 fast/standard/deep 三档分配 max_tokens 上限
  - 主聊天：700 / 1100 / 1600
  - 微信群聊回复：520 / 760 / 1050，历史行数按档自适应（16 / 28 / 40）
  - 开场生成：420 / 620 / 850
  - 新闻摘要：650 / 950 / 1300
  - 新闻群聊讨论：520 / 760 / 1000
- **依赖锁定**：迁移到 pip-tools 工作流（`requirements.in` → 锁定 `requirements.txt`）
- **状态模型文档化**：`docs/STATE_MODEL.md` 定义真源层级、迁移指南、清理清单
- **CI 门禁升级**：`detect-secrets` 改为硬门禁
- **入口页新闻流程修复**：群聊未开始时也能显示新闻阶段面板，`_clear_wechat_news_state` 统一清理
- **新闻讨论状态同步修复**：`run_discussion_stage` 正确调用 `update_wechat_join_state`
- **README 重构**：展示型结构（Demo / 架构图 / 使用流程 / Roadmap）
- **`.gitignore` 收口**：排除 `config/runtime_state.yaml`、`memory/`
- **140 tests，Ruff clean**

## v0.7.7 — 模块拆分与服务层解耦

- **新闻链路拆分**：`wechat.py`（~550 行）拆分为 4 个专注模块 + 1 个兼容门面
  - `wechat_format.py` — 纯文本 / 格式化工具
  - `wechat_state.py` — 文件 I/O、群聊状态、生命周期管理
  - `wechat_generator.py` — LLM 生成逻辑（群聊讨论、开场、互动回复）
  - `wechat_prompt.py` — 系统 / 互动 prompt 加载（自包含，无外部依赖）
  - `wechat.py` — 纯兼容门面，仅 re-export，零运行时逻辑
- **服务层拆分**：`wechat_service.py` 改为直连子模块，绕开门面
- **UI 逐阶段新闻流**：搜索 → 正文读取 → 生成摘要 → 群聊讨论，四步按钮推进
- **自适应 max_articles**：fast→2、standard→4、deep→6
- **安全加固**：
  - 自定义 `_SafeHTTPRedirectHandler` 逐跳 SSRF 校验 + 最多 3 次重定向
  - 包扫描增加 GitHub PAT、OpenRouter、通用 key/token 模式
  - detect-secrets 加入 CI 流程
- **内存保护**：Session logger 50 条自动 flush、2 小时老化警告
- **防回归 guard**：`test_wechat_decoupling.py` 4 个测试确保模块边界不退化
- **112 tests，Ruff clean**

## v0.7.6 — 工程安全与新闻链路收口

详细内容见 `changelog/README_v0_7_6.md`。

## v0.7.5 — 文档同步收口 + 代码清理

- 版本信息同步 10 个文件
- 死代码清理（chat_stream / 重复函数）
- YAML 同步 mtime canary 优化
- 重复逻辑合并
- 详见 `changelog/README_v0_7_5.md`

## v0.7.4 — 工程体验收口

- 自动化版本 bump 工具
- LLM 配置文档化（`.env.example` 5 个 provider）
- NewsRoundResult 结果对象化（覆盖率/警告/耗时）
- UI 来源可信度展示
- 详见 `changelog/README_v0_7_4.md`

## v0.7.3 — 服务层拆分与工程化收口

- Wechat news round 下沉到 `src/wechat_service.py`
- session flush 批量提交
- GitHub Actions CI
- 架构级测试
- LLM client 参数扩展
- YAML runtime state 真源化
- 详见 `changelog/README_v0_7_3.md`

## v0.7.2 — 代码质量全面收口

修复 4 个 Bug、性能优化（缓存/YAML/diff）、架构改善（常量去重/模块拆分）、Streamlit fragment 反模式修复、关键路径错误处理增强。

## v0.7.1 — 搜索窗口与来源优化

90 天搜索窗口、来源块压缩、摘要覆盖率提示、prompt 乱码修复、覆盖率统计对齐。

## v0.7.0 — 多源新闻聚合

多源 RSS 聚合、正文三层提取、来源块写入群聊、摘要边界约束、URL 安全检查。

## v0.6.9 — 联网搜索增强

自由文本联网搜索、进度指示、新闻缓存按 query 隔离、记忆写入加固。

## v0.6.8 — 写入与缓存优化

.tmp 排除、文件锁重试 finally 清理、LLM client 自动重建、wechat_state 批量写入、新闻 10 分钟缓存。

## v0.6.7 — 刷新与健康检查

刷新逻辑拆分、notice queue、健康检查只读化、打包排除增强、lru_cache 缓存。

## v0.6.6 — 渲染与并发修复

未知发言人渲染修复、并发写入安全、打包测试对齐。

## v0.6.5 — 氛围与角色优化

开场氛围选择、角色归一化兜底、侧栏与 memory 对齐、打包脚本拆分。

## v0.6.4 — 首次可用正式包

Catppuccin 暗色主题、紫蓝渐变、微信气泡 UI、路由系统、会话隔离、safe_writer。

## v0.1 ~ v0.6.3 — 早期探索阶段

界面仅纯文本、按钮触发全页刷新、侧边栏与主区域不同步、无视觉资源、自动路由缺失、群聊格式简陋。问题过多，未发布 Release。
