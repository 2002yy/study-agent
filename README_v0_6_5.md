# README v0.6.5

## 概述

v0.6.5 是在 [README_v0_6_4.md](C:\Users\96967\Desktop\study agent\README_v0_6_4.md:1) 基础上的一轮体验收口版。

如果说 v0.6.4 的重点是：
- 默认进入微信群
- 群聊成为主界面核心
- 页面结构、状态区、输入区和打包链路整体成型

那么 v0.6.5 的重点是：
- 让微信群“更像真的在聊”
- 让开场与首次用户发言的关系更自然
- 让四角色调度更稳定
- 让左侧状态和 memory 文档真正同步
- 让 release 打包脚本更稳、更可移植

---

## 相比 v0.6.4 的主要改进

### 1. 微信群开场从固定文本改为可控生成

v0.6.4 里，群聊开场主要还是固定模板或早期开场残留，容易出现风格僵硬的问题。

v0.6.5 改为：
- 开场不再默认自动写死
- 先由用户选择群聊氛围
- 再按当前角色 / 当前氛围 / 当前性能模式生成一轮开场
- 开场生成会额外触发一次 LLM 调用

这让开场更灵活，也更贴近当前页面配置。

### 2. 修正“角色提前知道用户会来”的问题

这是 v0.6.5 最重要的一条体验修复。

相较于 v0.6.4：
- 开场 prompt 明确要求四位角色只是在彼此聊天
- 不允许提前知道用户会来
- 不允许对用户隔空说话
- 不允许出现“如果你看到”“你要是来了”这类句子

这样用户第一次发言时，才会更像“突然加入并打断她们原本的对话”。

### 3. 四角色群聊调度加了最终兜底

v0.6.4 的群聊体验已经偏向多人互动，但仍可能出现只有部分角色发言的情况。

v0.6.5 在 `src/wechat.py` 中加入了统一归一化逻辑：
- 互动回复最终落盘前统一整理
- 课后反馈生成的群聊内容也统一整理
- 最终结果固定为 `三月七 / 刻晴 / 纳西妲 / 流萤` 四位角色都发言

也就是说，v0.6.5 不再只依赖 prompt“希望模型听话”，而是把四角色完整性做成了结果层保证。

### 4. 旧版错误开场会被识别并要求重生成

v0.6.4 的一个现实问题是：即使代码已改，新群文件里仍可能残留旧开场。

v0.6.5 增加了旧开场识别：
- 如果群里还没有用户发言
- 且内容命中旧版“预判用户会看到”的特征
- 则不再把它视为有效开场

这样界面会重新回到“先选氛围，再生成开场”的流程，而不是继续沿用错误内容。

### 5. 左侧状态与 memory 文档彻底对齐

v0.6.4 之后，界面上的版本状态已经来到 `v0.6.4`，但 memory 文档里仍有不少旧内容停在 `v0.5.3`、`v0.2`。

v0.6.5 这次做了文档收平：
- `memory/summary.md`
- `memory/current_focus.md`
- `memory/agent.md`
- `memory/progress.md`
- `memory/task_board.md`

现在这些文件都同步到了 `v0.6.4` 的当前状态，避免左侧状态栏和摘要文案给出相互矛盾的信息。

---

## 相比更早版本的延续关系

### 相比 v0.6.3

[README_v0_6_3.md](C:\Users\96967\Desktop\study agent\README_v0_6_3.md:1) 重点是“默认进入微信群”。

v0.6.5 在此基础上继续推进了三件事：
- 不只是默认进群，而是让“进群后的第一眼体验”更合理
- 不只是能发言，而是让“四角色一起回应”更稳定
- 不只是有群聊壳子，而是让“开场 -> 用户加入 -> 角色惊讶”这条链更像真实互动

### 相比 v0.6.2

[README_v0_6_2.md](C:\Users\96967\Desktop\study agent\README_v0_6_2.md:1) 重点是响应速度优化。

v0.6.5 没有推翻这套性能策略，而是继续沿用：
- `performance_mode: fast / standard / deep`
- 主聊天流式输出
- 不增加不必要的自动 LLM 调用

这次新增的开场生成虽然会多一次 LLM 调用，但它是显式、手动触发的，不会破坏 v0.6.2 的“默认链路要轻”的原则。

---

## 打包与工程侧改进

相较于 v0.6.4，v0.6.5 也补了一轮 release 工程质量：

- `tools/package_project.ps1` 不再只依赖 `python`，会自动探测：
  - `python`
  - `py`
  - `python3`
- 打包核心逻辑拆到 `tools/package_project_helper.py`
- 排除规则更精确：
  - 排除 `.env`
  - 排除 `.env.*`
  - 保留 `.env.example`
  - 排除 `chat/archive/`
  - 精准排除 `图片资料`
- 增加静态守护测试：
  - 锁住 `required` 文件
  - 锁住关键 `exclude` 规则
  - 锁住侧栏保存日志调用方式
  - 锁住微信群面板不重复渲染

---

## 本版涉及的关键文件

- [src/wechat.py](C:\Users\96967\Desktop\study agent\src\wechat.py:1)
- [src/ui/wechat_panel.py](C:\Users\96967\Desktop\study agent\src\ui\wechat_panel.py:1)
- [memory/summary.md](C:\Users\96967\Desktop\study agent\memory\summary.md:1)
- [memory/current_focus.md](C:\Users\96967\Desktop\study agent\memory\current_focus.md:1)
- [memory/agent.md](C:\Users\96967\Desktop\study agent\memory\agent.md:1)
- [memory/progress.md](C:\Users\96967\Desktop\study agent\memory\progress.md:1)
- [memory/task_board.md](C:\Users\96967\Desktop\study agent\memory\task_board.md:1)
- [tools/package_project.ps1](C:\Users\96967\Desktop\study agent\tools\package_project.ps1:1)
- [tools/package_project_helper.py](C:\Users\96967\Desktop\study agent\tools\package_project_helper.py:1)
- [tests/test_packaging_guards.py](C:\Users\96967\Desktop\study agent\tests\test_packaging_guards.py:1)

---

## 手动验收建议

1. 打开页面，默认进入微信群。
2. 如果是空群或旧错误开场，确认界面先显示“选择氛围并生成开场”。
3. 生成开场后，确认四位角色都在彼此聊天，而不是提前知道用户会来。
4. 用户发第一条消息后，确认会触发轻微惊讶，但只在该线程第一次发言时出现。
5. 再连续发一条消息，确认四位角色仍然都发言。
6. 查看左侧状态与 memory 摘要，确认不再停留在旧版 `v0.5.x`。
7. 运行打包脚本，确认 release 包能正常生成，且不包含 `.env.*` 与 `chat/archive/`。
