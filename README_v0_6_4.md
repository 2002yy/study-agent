# README v0.6.4

## 概述

v0.6.4 对前端页面进行了大刀阔斧的改造（彩色主题、群聊主体），并对路由、写盘、日志、测试等层面进行了结构性质量收口，增强了 LLM 调用层的健壮性。

> **注意**：v0.6.4 改动跨度大，涉及前端重构、路由重写、写盘收口、日志隔离等多条链路并行推进。部分早期调整（如 UI 交互细节、侧栏状态联动）因改动粒度细、迭代快，未在本文档中逐一记录。完整变更请以 `git diff` 为准。

---

## P0 · 前端页面重构

### 视觉体系全面改造

- 全局 CSS 主题从默认 Streamlit 白色改为 **Catppuccin 暗色主题**，采用紫蓝渐变配色
- 角色头像、气泡、按钮、状态栏全部彩色化
- 微信群聊采用仿微信气泡样式，四个角色各有专属颜色标识
- 侧栏、课后更新面板、群聊工具面板统一深色风格

### 交互重心从单人聊天转向群聊

- 默认入口改为 **微信群模式**，打开页面首先看到四人角色群聊面板
- 单人主讲模式保留但改为可切换入口，`memory/internal_state.md` 中 `entry_mode` 控制
- 群聊支持用户参与发言、角色互动回复、未读标记、记忆候选提取
- 课后更新生成 → 确认写入 → 微信群反馈 形成完整闭环

改动涉及：`src/ui/theme.py`, `src/ui/wechat_bubble.py`, `src/ui/wechat_panel.py`, `src/ui/chat_panel.py`, `src/ui/sidebar.py`, `src/ui/avatar.py`, `src/ui/status_bar.py`, `src/wechat.py`, `src/wechat_memory.py`

---

## 一、路由系统修复

### 1.1 YAML default 配置生效

`config/routing_rules.yaml` 中的 `default` 段此前是摆设，路由硬编码了默认值。现已通过 `load_routing_config()` → `RoutingConfig` 统一读取，YAML 的 default 会被实际使用。

改动：`src/router.py:30-112`

### 1.2 规则匹配加入优先级

之前 `_match()` 只按命中关键词数量排序，导致"论文里的代码实验怎么改"这种同时命中两条规则时结果不稳定。现在每条规则支持 `priority` 字段：

- 机制: 100
- 任务/代码: 90
- 论文: 80
- 费曼: 70
- 概念地图: 60
- 入门: 50
- 收尾: 40

匹配规则：先比 priority，同优先再比命中数。

改动：`config/routing_rules.yaml`, `src/router.py:_match()`

### 1.3 fast 模式不再无条件覆盖 pro

之前 `fast` 模式强制所有路由结果使用 flash 模型。现在改为：
- **fast**: 默认 flash，但遇 `论文/代码/报错/架构/机制` 等高风险关键词仍升级为 pro
- **standard**: 规则决定
- **deep**: 强制 pro

改动：`src/router.py:181-195`

---

## 二、写盘层收口

### 2.1 mode_manager 写入走 safe_writer

`mode_manager.py` 中的 `_write_keyvalue()` 原先直接 `path.write_text()`，现在改为调用 `safe_write_text()`，使 `internal_state.md`、`interaction_settings.md`、`wechat_state.md` 的每次写入都有备份和原子替换。

改动：`src/mode_manager.py:113-131`

### 2.2 备份文件名精确到微秒

`safe_writer.py` 的备份时间戳从 `%H%M%S` 改为 `%H%M%S_%f`，避免同秒内多次写入导致备份覆盖。

改动：`src/safe_writer.py:8-9`

---

## 三、会话日志隔离

### 3.1 多会话日志隔离

`session_logger.py` 原先使用模块级全局变量 `ENTRIES`、`_meta`、`_flushed_count`，多会话场景下可能串数据。改为 `_state[session_id]` dict-based 结构，每个会话独立状态。

### 3.2 每会话独立文件

- 当前会话日志从 `logs/current_session.md` 改为 `logs/current/{session_id}.md`
- 存档文件包含 `session_id` 标识
- `save()` 仅清理当前会话，不影响其他会话
- `init_session()` 由 `session_state.py` 在 Streamlit 启动时调用

改动：`src/session_logger.py`, `src/ui/session_state.py`

---

## 四、LLM 调用层增强

### 4.1 超时与重试

OpenAI 客户端初始化为 `timeout=30.0, max_retries=2`。

### 4.2 错误分级中文提示

新增 `_classify_error()` 函数，区分 7 类错误：

| 错误 | 提示 |
|------|------|
| AuthenticationError (401) | API Key 无效或被拒 |
| PermissionDeniedError (403) | API 权限不足 |
| NotFoundError (404) | 模型名或端点不存在 |
| RateLimitError (429) | API 速率限制，请稍后重试 |
| InternalServerError (5xx) | API 服务端错误 |
| APITimeoutError | API 请求超时 |
| APIConnectionError | 网络连接失败 |

`stream_chat()` 的创建和迭代两个阶段分别包裹，流式中断时也给出中文提示。

改动：`src/llm_client.py`

---

## 五、依赖版本锁定

### 5.1 生产依赖

```
streamlit>=1.35,<2
openai>=1.0,<2
python-dotenv>=1.0,<2
pyyaml>=6.0,<7
pytest>=8.0,<9
python-docx>=1.1,<2
```

### 5.2 开发依赖（新建）

`requirements-dev.txt`:
```
pytest>=8.0,<9
ruff>=0.6,<1
mypy>=1.0,<2
```

---

## 六、课后更新写入修复（P0）

### 6.1 preview 模式允许确认写入

修复 `after_session_panel.py` 的守卫逻辑：之前 `is_memory_write_allowed()` 在 preview 模式下返回 False，导致用户点击"确认写入长期记忆"被直接拒绝。现在仅 safe_mode 和 locked 模式被阻止，preview/readonly 均可通过 `run_with_confirm_write()` 临时切入 confirm_write 完成写入。

改动：`src/ui/after_session_panel.py:107-113`

### 6.2 微信群"引用到记忆候选"路径修复

`wechat_panel.py` 原先通过 `Path(__file__).resolve().parent.parent` 手拼路径，导致写入到 `src/memory/pending_updates/`（错误目录）。现改为调用 `wechat_memory.py` 中的统一函数 `append_manual_memory_candidate()`，路径由 `CANDIDATES_FILE` 常量统一管理。

同时清理了错误目录 `src/memory/`。

改动：`src/ui/wechat_panel.py`, `src/wechat_memory.py`

---

## 七、测试体系同步（P1）

- `test_v03_accept.py`: 所有 `route_request()` 调用补上 `RuntimeModes` 参数，显式构造 `RuntimeModes(performance_mode="standard")` 避免本地状态依赖
- `test_streaming.py`: 测试目标从 `chat_stream` 改为直接检测 `stream_chat()`（包含 `stream=True`），匹配代码重构后的实际结构

---

## 八、角色设定调整

### 8.1 warm 模式加入动作/表情表述

四个角色的 `warm` 模式均加入角色化动作和表情：

| 角色 | 动作/表情示例 |
|------|-------------|
| 三月七 | `*歪头看你*`、`*眨眨眼*`、`~`、`…` |
| 刻晴 | `*轻轻敲了下你的屏幕*`、`*叹气*`、`…` |
| 纳西妲 | `*轻轻翻开书页*`、`*托腮思考*`、`…` |
| 流萤 | `*轻轻点头*`、`*把一杯热茶推到桌前*`、`…` |

格式统一为 `*动作描述*`。

### 8.2 三月七官方文本参考

三月七的完整语言风格示例（基础形态 + 习剑形态战斗语音）和角色背景故事（详情 + 故事一~四 + 仙舟）已拆分为独立参考文件 `roles/references/march7_lore.md`，不纳入角色行为 prompt。

---

## 改动文件清单

```
修改:
  src/router.py                    # 路由优先级 + YAML default + fast mode
  src/mode_manager.py              # _write_keyvalue 走 safe_writer
  src/safe_writer.py               # 备份时间戳 → 微秒
  src/session_logger.py            # 会话日志隔离
  src/llm_client.py                # 超时/重试 + 错误分级
  src/wechat.py                    # 群聊生成/互动/存储
  src/wechat_memory.py             # 群聊记忆候选 + append_manual_memory_candidate()
  src/ui/theme.py                  # Catppuccin 暗色主题
  src/ui/wechat_bubble.py          # 微信气泡样式组件
  src/ui/wechat_panel.py           # 群聊面板 + 记忆候选路径修复
  src/ui/chat_panel.py             # 主聊天区重构
  src/ui/sidebar.py                # 侧栏群聊控制
  src/ui/avatar.py                 # 角色头像组件
  src/ui/status_bar.py             # 状态条
  src/ui/after_session_panel.py    # preview 允许确认写入
  src/ui/session_state.py          # init_session() 调用
  config/routing_rules.yaml        # 7 条规则加 priority
  requirements.txt                 # 版本锁定
  roles/march7.md                  # warm 模式动作/表情
  roles/keqing.md                  # warm 模式动作/表情
  roles/nahida.md                  # warm 模式动作/表情
  roles/firefly.md                 # warm 模式动作/表情
  tests/test_v03_accept.py         # RuntimeModes 参数
  tests/test_streaming.py          # 检测 stream_chat

新增:
  requirements-dev.txt             # 开发依赖
  roles/references/march7_lore.md  # 三月七官方文本参考

删除:
  src/memory/                      # 错误目录，已清理
```
