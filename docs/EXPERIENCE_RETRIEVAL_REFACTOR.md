# 体验与检索重构：本地交付记录

更新：2026-11-02。用户明确选择 UI 美学与流畅交互、后端去冗余、核心检索、
CLI 可验证开发。当前原型方向尚未选择，生产 UI 接线待下一步。

## 基线与归属

- 分支：`codex/experience-retrieval-20261101`。
- 工作树：`D:/study-agent-validation/experience-retrieval-20261101`。
- 已 fetch 的 main 基线：`abf40b494272c547f1fe29ca15edd13c4c470e7b`。
- 搜索提交：`d61b108cb1927d25f8e96f8cd53b55768c0d3014`。
- CLI 提交：`16b94b95bcd5ebce369dad2992f2e93e4481ad51`。
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

## UI：可点击方向，尚未接线生产

使用 huashu-design，六候选中展开三版：

- A 清流：会话导航、居中对话、按需来源。
- B 夜航：深色顶栏布局、图解、纵向阅读；手机输入框需向下滚动。
- C 对照：答案与来源双页，引用定位原文；手机切换回答/来源。

[打开总览](../design-demos/experience-20261101/index.html)；
[六候选](../design-demos/experience-20261101/thumbs.html)。
示例全部标为本地交互演示，无真实模型回答/检索/上传。
建议 A 作为日常聊天骨架，按需展开 C 的来源对照；这不是用户已选方向。

`py -3.12 design-demos/experience-20261101/verify_all.py` 自动建临时 loopback
服务，三份验证脚本均消费它传入的 URL。复核发现初稿脚本仍硬编码 8766；
已修成随机端口注入并重新跑三版通过，避免误测另一份服务。
截图与 JSON 在同一目录。覆盖来源、空白输入、合成 IME 事件、发送、
本地附件展示、会话切换、布局溢出及 pageerror；不等于 Android 真机或辅助技术验收。

## 决策与唯一下一片

- loop=static；decision=engineering-only。
- dynamic_evidence=not_run；budget_authorization=not_applicable（未调用模型/API）。
- UI 方向待用户选择。按用户点名的 huashu-design 三方向门，选定前不修改生产 UI。
- 下一片：落实所选方向到现有 WorkspaceView/ChatPanel/SourcesPanel，
  整理壳层与样式 token，复用现有控制器，用 Vitest/Playwright/CLI 验证交互，
  保留输入、附件、来源和研究补充的真实行为。
