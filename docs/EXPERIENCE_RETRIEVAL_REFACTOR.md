# 体验与检索重构：本地交付记录

更新：2026-11-02。用户明确选择 UI 美学与流畅交互、后端去冗余、核心检索、
CLI 可验证开发。用户选择 A+C，生产 UI 已接线；角色头像放大、聊天图表设计准则已内化。

## 基线与归属

- 分支：`codex/experience-retrieval-20261101`。
- 工作树：`D:/study-agent-validation/experience-retrieval-20261101`。
- 已 fetch 的 main 基线：`abf40b494272c547f1fe29ca15edd13c4c470e7b`。
- 搜索提交：`d61b108cb1927d25f8e96f8cd53b55768c0d3014`。
- CLI 提交：`16b94b95bcd5ebce369dad2992f2e93e4481ad51`。
- UI 提交：`89f32288391dbb12f038362ccd081a6009863776`，前序原型基线 `f6738040`。
- 原桌面工作树保持原分支与未跟踪文件；未读取其 .env，也未吸收其他工作树 WIP。
- 尚未 push/PR/merge；没有远端 CI 或生产交付资格。

## 后端：用一个提供商循环替换三个分支

`GeneralWebGateway` 保留 fallback、ddg_first、merge 三种部署策略，
由数据决定顺序与提前停止。超时、开关、错误记录、来源边界不变。
消除重复的调度、截止时间包装和去重循环，生产文件净减 121 行。
未删除访问控制、预算准入、SSRF、取消、持久化或发布证据检查。

两个已复现的检索缺陷（owner=retrieval，priority=P2）：

1. 首引擎返回域外网页时，旧实现先停止提供商回退，再做 site: 过滤，
   导致备用引擎可用仍返回空结果；merge 也可能在过滤前用完结果名额。
   现在每个提供商先过滤，再判断成功或回退，合并后才占交付名额。
2. 全 URL casefold 把不同大小写的路径/查询误当成同一网页。
   现在仅 scheme/authority 归一，保留路径和查询大小写；同页片段不占重复名额。

首引擎已有合域结果时仍只请求一次；无有效结果时使用既有备用引擎与共享时限，
不增加重试层。没有测量新的在线耗时或答案正确率，不能宣称实测延迟/质量提升。

## CLI：复用现有门禁与 JSON 回执

`studyctl test list --json` 直接展示现有 manifest 的 L1/L2 名称与路径。
没有第二份注册表、新调度器或付费运行入口。
`test run --impact-set search_flow` 覆盖 18 个直接影响测试文件；
`test run --impact-set studyctl` 验证 CLI 的读取、执行、失败、回执等合同。
命令用法与前端 Vitest/Playwright 入口见 [STUDYCTL.md](STUDYCTL.md)。

## 验证

| 检查 | 实际结果 |
| --- | --- |
| 旧代码负控 | 新增的 11 项初始用例：7 FAIL、4 PASS，证明域名回退、截断顺序和大小写去重缺陷 |
| 初步搜索影响集 | 51 PASS |
| 扩大影响集首次运行 | 224 PASS、2 FAIL：旧测试替换整个私有调度，绕过前移后的过滤 |
| 失败处理 | 将这三项测试的替身收窄到网络提供商，原断言保持；相关 27 PASS |
| 最终 search_flow（真实 CLI 子进程） | 230 PASS，105.31 秒 |
| studyctl（真实 CLI 子进程） | 445 PASS、1 SKIP，275.67 秒；SKIP 是既有 Windows symlink 权限限制 |
| 类型 | src mypy baseline 124/128，新增 0；CLI 模块 mypy PASS |
| 静态 | Ruff check 全仓 PASS；改动 Python 格式化；git diff --check PASS |
| 原型 | 三版 × 1440×900 / 375×812，脚本通过；人工查看桌面/手机截图，视觉 PASS |
| 设计 lint | 三版无红灯、无模板装饰 |

测试先在此工作树未提交实现上运行，JSON 正确标记 `uncommitted_source=true`，
不能把其中基线 head_sha 冒充受测提交。随后仅做等价格式化并保存上述代码提交。
本片是普通检索适配器和 CLI 有界修改，未触及 L3 强制触发项；L2/L3 未运行。

原始 CLI 回执：
`D:/study-agent-validation/experience-search-flow-final-20261101.json`、
`D:/study-agent-validation/experience-cli-20261101.json`。
失败回执保留在 `experience-search-flow-20261101.json`，未覆盖。
类型检查日志为同目录 `experience-mypy-20261101.log` 与 `experience-cli-mypy-20261101.log`。

## UI：从已选 A+C 接入生产界面

使用 huashu-design，六候选中展开三版：

- A 清流：会话导航、居中对话、按需来源。
- B 夜航：深色顶栏布局、图解、纵向阅读；手机输入框需向下滚动。
- C 对照：答案与来源双页，引用定位原文；手机切换回答/来源。

[打开总览](../design-demos/experience-20261101/index.html)；
[六候选](../design-demos/experience-20261101/thumbs.html)。
示例全部标为本地交互演示，无真实模型回答/检索/上传。
用户明确选择 A+C；原话与迭代授权见同目录 `direction-approved.md`。
这些文件保留为选稿证据，实际应用已由生产组件实现。

`py -3.12 design-demos/experience-20261101/verify_all.py` 自动建临时 loopback
服务，三份验证脚本均消费它传入的 URL。复核发现初稿脚本仍硬编码 8766；
已修成随机端口注入并重新跑三版通过，避免误测另一份服务。
截图与 JSON 在同一目录。覆盖来源、空白输入、合成 IME 事件、发送、
本地附件展示、会话切换、布局溢出及 pageerror；不等于 Android 真机或辅助技术验收。

### 已实现范围与回归

- 将来源阅读放到对话右侧，移动端按既有标签切换，同步修正拖动与键盘缩放方向。
- 清理旧气泡样式文件与重复壳层规则；统一白底、灰绿、阅读宽度、间距和固定输入区。
- 纳西妲采用原有 512px 图片，桌面头像 88px、手机 72px，正文独占下一行。
- 图片或图表延迟撑高后仍跟随最新位置；用户上翻时不抢滚动，减少动画偏好受尊重。
- 将 huashu-design 方法缩成聊天准则，接入既有 `packAnswerUiContext`，不新增模型调用。
  设计规则、来源和代码入口见 [CHAT_VISUAL_DESIGN.md](CHAT_VISUAL_DESIGN.md)。
- 横向条形图逐项显示名称/数值/单位；折线按有序数据展示，保留完整数据表及带单位复制。
  `view`/`unit` 为可选字段，旧消息可用；未知样式/代码仍不进入组件。

owner=UI（布局/头像/滚动/图表）与 prompt context（模型的视觉参考）。
L1 影响集是 `playwright.experience.config.ts` 的 9 个浏览器测试文件，
全部 `frontend/src` 单测，以及后端 `test_turn_context_transport.py`、
`test_chat_service.py`、`test_answer_publication_gate.py`。
未改后端执行/存储合同，未触发 L3；本批不是最终合并/发布资格。

| 检查 | 实际结果 |
| --- | --- |
| 滚动负控 | 换回 `f6738040` 的 ChatPanel，新用例 FAIL：高度增至 1200 时位置仍为 900；已恢复实现 |
| 组件影响集 | 6 文件/71 PASS，随后全量通过 |
| 前端全量 | 121 文件/610 PASS，35.51 秒 |
| A+C 交互影响集 | 24 PASS，37.2 秒；覆盖实际发送请求携带设计准则、连续补充、输入、来源、缩放、晚到内容与可访问性 |
| 最终截图定位调整 | 2 PASS，6.3 秒；仅调整截图滚动位置，不改生产行为 |
| 后端关联集 | 58 PASS，32.96 秒；离线替身，无付费模型调用 |
| 静态 | `npm run build`（含 tsc）/Ruff 全仓/git diff --check PASS；src mypy 沿用前片无新增错误证据，本片无 Python 改动 |
| 视觉 | 亲自查看桌面与 375px 头像/图表、右侧来源截图，PASS；另测 320px 无页面横向溢出 |

有意义的失败：最初 composer 两项仅断言旧 12px，已按新侧栏 13px 更新；
新增图表测试发现全局 `.message-body span` 将标签压回 12px/粗体，
已给图表文字明确作用域，最终浏览器断言 14px，截图复核字重。
首轮浏览器运行还暴露系统 Chrome 启动退出及完整 Golden Journey 收尾要求；
改用项目 Chromium，并以独立有界配置运行该子集，原完整门禁保持。

回执位于 `D:/study-agent-validation/`：
`experience-ui-unit-final-20261102.log`、`experience-ui-experience-final-20261102.log`、
`experience-ui-context-20261102.log`、`experience-ui-build-final-20261102.log`、
`experience-ui-scroll-negative-20261102.log`。
截图在 `experience-ui-evidence-20261102/`，含 `desktop-chromium-portrait-chart.png`、
`mobile-chromium-portrait-chart.png` 和两种视口的 `*-sources.png`。
截图中的文字与数字是明示的测试样本，并非真实模型/检索效果证据。
全量单测后仅调整 CSS 作用域及浏览器测试，已由 24 项浏览器门禁和最终构建覆盖。
最终代码提交后未修改生产文件。
构建仍有约 734 kB 主包提示，未测冷启动或网络延迟，不宣称已获得性能基准提升。

## 决策与唯一下一片

- loop=static；decision=engineering-only。
- dynamic_evidence=not_run；budget_authorization=not_applicable（未调用模型/API）。
- UI 本地实现及静态验收完成；`89f32288` 提交后 tracked/untracked 均干净。
- 下一片：按 `abf40b49...HEAD` 准备增量 PR 评审与远端门禁，保留三个独立实现提交的边界。
- 付费真实任务比较尚未获得本轮授权/共享硬预算；未运行。静态通过不能证明模型审美或答案正确率提升。
