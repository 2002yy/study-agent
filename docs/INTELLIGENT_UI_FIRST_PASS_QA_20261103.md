# 智能 UI：首轮生成正确率与独立浏览器验收（2026-11-03）

## 为什么做

这是独立于本地尚未推送的 `codex/intelligent-ui-20261103` 的**离线质量工具**，不修改现有模型提示、回答协议、认证、研究发布和本地已实现的交互组件。远端 main 仍是预设 `study-ui` 协议，不能把本分支当作自由生成引擎已经合并的证据。

真实验收里出现过两类可复现缺陷：
- Java 对象图在“执行之前”就出现尚未创建的对象，以及 SVG 箭头端点与对象框错位。
- 初次生成的代码/动画可运行，但运行正确性和几何布局需要追问修复。

这些属于 **P2 交互质量**，通常由模型生成与前端执行共同决定。首轮改动只增加不调用模型的独立验收外壳，避免通过提示词自证正确。

## 新增工具

- `frontend/tools/audit-generated-ui.mjs`：审查单份独立 HTML（含内联 SVG/Canvas），使用真实 Playwright 浏览器和受限 iframe；输出机器可读逐步验收结果。
- `frontend/tools/audit-generated-ui.test.mjs`：Node 内建单测，验证输入约束、拒绝任意脚本操作以及 iframe 安全策略。
- `frontend/tools/fixtures/intelligent-ui-inventory.{html,json}`：冻结库存情景：总量 37、锁定 5→12、可售 32→25、支付后总量与锁定各降 5、恢复；桌面和 390px 手机分别检查。

运行命令（Windows 11，前端已安装依赖和 Playwright 浏览器）：

```powershell
cd frontend
node --test tools/audit-generated-ui.test.mjs
node tools/audit-generated-ui.mjs --html tools/fixtures/intelligent-ui-inventory.html --scenario tools/fixtures/intelligent-ui-inventory.json --report inventory-report.json
```

离线浏览器通过初始化脚本提供与生产一致的 \`window.studyUI.setState(对象)\` 状态上报接口，不注入认证令牌或父页面数据；增加 \`expectState\` 可验证发布状态（如库存 37、锁定 12、可售 25），与从可见控件读取的数值守恒断言相互独立。状态报告来自生成代码自身，因此**不能替代可见行为和数学真值的独立断言**。\n\n独立断言操作：`click`、`set`、`expectText`、`expectAbsent`、`expectCount`、`expectEquation`、`expectLineAnchored`（仅 SVG line）、`expectNoOverflow`、`expectState`、`wait`。每个断言对渲染出的界面进行浏览器观测，不接受模型自报“已通过”。

### 隔离边界

浏览器里将生成代码放入不带 `allow-same-origin` 的 `sandbox="allow-scripts"` iframe；首先注入禁止默认网络、连接、外部字体、子框架与表单提交的 CSP，并拦截 HTTP(S) 请求。没有应用令牌和真实数据，下载与 service worker 被禁用。发现网络请求或控制台/运行异常，报告失败。该工具仅用于**不可信生成结果的离线检查**，不替代生产页面现有的双层沙箱和服务端规则；不宣称涵盖浏览器所有漏洞。

## 下一开发门与验收

1. **把本地自由生成实现推到远端隔离分支**，对照现有分支 HEAD 合并此工具；**不得**将旧 main 的 `answerUiProtocol.ts` 反向覆盖本地新版。
2. 从既有真实任务固定基准（库存、Java 引用、Canvas 动画），补充数组/栈、并发、统计图等至少四个不同题材，保存**首次输出原文**、一次追问修复输出和独立场景断言。禁止挑通过样本代替整体分母。
3. 指标区分：格式有效率、浏览器可运行率、**首轮语义正确率**、交互状态一致率、追问状态继承率、移动端可读/可操作率；不把“按钮能点”作为语义通过。
4. 先在独立测试样例确认原始失败确实被门禁捕获（对象提前出现、箭头错位、库存守恒破坏），再用小幅提示改动、模型重试或修订来提高首轮通过率。保留失败样本，不依赖一次模型自我审查。
5. 无用户明确的新授权，不执行新的付费模型调用。此前预留额累计约 ¥7.05/¥30 是旧任务的历史交接记录，不是当前动作的费用权限。

## 当前证据等级

- **已提交**：离线检查器、冻结情景与输入校验单测，均在独立 GitHub 分支，未合并 main。
- **未运行**：此远端精确 HEAD 上的 Playwright 浏览器测试、现有前后端全套 CI、真实模型抽样。不能声称它们通过。
- **不在范围**：持久化/研究事实发布资格、生产沙箱替换、模型供应商切换、`main` 合并或用户本机文件修改。
