# Interview Notes

## 一句话介绍

Study Agent 是一个本地优先的 AI 学习助手，重点在多 Provider 模型接入、长期记忆、上下文分层、来源追溯和工程稳定性。

## 技术难点

1. **多模型 Provider 抽象** — 统一 OpenAI-compatible client 模式，支持 5+ 供应商切换，参数解析与 API 兼容性适配
2. **长期记忆写入安全** — safe writer + preview/confirm 机制，防止不可逆的记忆污染
3. **联网搜索来源追溯** — Feed registry / RSS 多源聚合 → URL safety matrix → 文章正文三层提取 → LLM digest → pipeline trace 全过程来源可回溯
4. **Streamlit 重渲染性能优化** — 多层缓存策略、按模式批量落盘、主链路 token 预算控制
5. **CI / Ruff / detect-secrets 工程检查** — 312 pytest tests、Ruff clean、mypy local clean、GitHub Actions workflow、detect-secrets 对未豁免发现硬阻断

## 可讲亮点

- 不是简单 Prompt demo，而是可配置、可测试、可追踪的 AI 应用工程项目
- 上下文分层（fast / light / deep / archive）解决长对话场景下的 token 成本和记忆衰减
- SSRF 防护在联网搜索场景中的工程实现
- feed health / source trace 让联网资料入口可解释、可调试
- 新闻轮次会保存 JSON + Markdown audit artifact，类似 Codex 任务产物，方便回看每一步证据和告警
- pip-tools 依赖锁定 + 精确版本管控，保证构建可复现

## 展示边界

- `mypy` 已接入 CI soft check，当前本地 `python -m mypy --explicit-package-bases src` clean；但 CI 配置仍是非阻断检查。
- `performance_budget.py` 覆盖主要 chat / WeChat / news LLM 路径，辅助 LLM 调用仍需继续收口。
- `article_fetcher.py` 负责真实网络读取前的 DNS/IP SSRF 校验；`link_resolver.py` 是网络无关的 URL 预检和跳转记录。
- `detect-secrets` 已接入 CI，并通过解析扫描 JSON 的 `results` 对未豁免发现硬阻断；测试里的 Basic Auth 形态 URL 样例已显式 allowlist。
