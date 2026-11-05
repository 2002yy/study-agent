# M4-F 宿主受控 Three.js

本片提供宿主图形能力，不把M4-D/E/G整个阶段宣称完成。用户已明确选择提前深入推进Three.js。
交互组件可增加 `"capabilities":["three"]`，再在html脚本里使用固定的 `window.THREE` 核心API。
库版本three0.187.0，构建时从锁定npm依赖打包为字符串，仅声明能力的卡片懒加载该本地资源。
运行库只在最内层隔离iframe执行；原CSP、网络禁用、父页隔离均保持。不提供CDN、import、addons。
普通旧卡片和显式空能力数组均不加载库。未知能力拒绝；WebGL2不可用需给出说明而非假渲染成功。

源码与能力声明作为同一版本保留：历史提取、旧版恢复、局部补丁、原文评测导出/重放均传递能力。
同HTML不同能力不能混作同一案例/恢复基线；评分汇总拒绝能力不匹配的证据。历史首批成绩不改写。

## 实际样例和验证

- 长方体：调长宽高和旋转，真实Three几何与体积、状态同步；可把当前参数带入后续问题。
- 动态过程：调频率/相位、播放暂停与恢复，位置与公式同步，真实WebGL画面更新。
- fixture：frontend/e2e/fixtures/controlled-three.ts。
- browser：frontend/e2e/acceptance/controlledThree.spec.ts。原始runtime双视口2例，真实App保存study-ui后
  经MarkdownMessage/异步InteractiveDocument/双sandbox的4例，全部6 PASS。覆盖实像素、参数、状态继续问、
  暂停稳定/恢复、CSP网络阻止、跨框架访问拒绝和零运行错误。浏览器API用受控fixture，无模型调用。
- 本地自包含HTML及截图：D:/study-agent-validation/m4f-artifacts-20261105/，cube与oscillator各1280/390版本。
  HTML由真实产品outer.srcdoc导出，内嵌库；不依赖CDN。手机Three画面已目视确认。
- 前端130文件713 PASS；审阅发现空能力数组前后端不一致，已规范为未声明并经直接13项回归通过。
- 后端历史/恢复/补丁/评测及相邻聊天影响集208 PASS，src mypy118/128、新增0；Ruff通过。

生成提示已说明能力声明、核心API、无addons、WebGL2失败处理、动画暂停和资源释放。
目前只证明工程链路和固定样例，不证明真实模型会选对媒介、生成正确3D或完成一般用户任务。
新的真实模型/自动修复评测仍需独立费用授权。M4-E证据反馈与M4-G媒介选择继续按原规划推进。
