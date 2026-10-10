# RP-1 原始 A/B 与 UI 证据归档

2026-10-09 用户授权提交远端尚无的本地成果，包括 UI 改造与原 A/B 答卷。本目录是原文件按字节复制的证据归档；索引 `manifest.json` 保存每个文件的 SHA-256、大小、原相对路径与实现 HEAD。

- `model-ability-ab/planning-96`：24 题 A/B 各重复两次的原始 96 次规划请求、响应、记录、匿名答卷、映射及机械摘要。
- `model-ability-ab/answer-paired-24`：原首 6 次固定资料回答及原风险停点，保持不变。
- `model-ability-ab/answer-paired-24-continuation`：用户授权继续的原后 18 次回答，不替换首六失败，不重新采样。
- `model-ability-ab/answer-paired-24-complete`：合并 24 份匿名答卷、揭盲映射、配对归因与封存评分。匿名映射不是 AES 解封密钥。
- `ui`：原 Conversation-first 桌面、手机、流萤和围棋页面 PNG，包含不同修订与诊断截图；静态截图不等于真实教学或异步运行验收。

回答阶段 20 秒 / 2800 tokens 的原实验诊断和生产规划入口后来的同数值配置属于不同批次，不重写原 96 次规划结果。保留题已解封且资源配置曾调整，相关回答属于 post-unseal 诊断，不能冒充纯未见保留集。固定证据回答没有测量真实检索收益；引用结构通过也不等于语义支持成立。

封存评分 JSON SHA-256：`5d5f3e8a7d8b29f0abada53fe652778b64e2509a139a00aeb3b7be9ad26b87f4`。

本次 409 个原文件、4,842,111 字节全部与原件一致（不含本 README 与 manifest）。保留 UTF-8 BOM 等原格式；不改答案、引用错误、分组、分数或原停止纪律。无凭据、AES 解封密钥、运行数据库、临时日志、头像备份或另一窗口未完成代码。

实现保留分支：`codex/reading-notebook-ui` (`40e0e311`)、`codex/conversation-first-ui` (`1a3d01bd`)、`codex/model-driven-research-entry` (`3c687b5f`)、独立 Answer Reliability shadow (`0cdcfe07`)。这些分支保存不同阶段的成果，不能整支盲目合并；准备生产 PR 时应复核最新 main 的依赖与差异，保留 #201 已合并内容。

归档与推送不授予研究支持或发布权。RP-1 仍 NO-GO：真实正文支持、通用定向检索、自然 Deep 进程恢复及综合发布验收尚未完成。项目执行状态仍以 `docs/PROJECT_STATUS.md` 为唯一入口。
