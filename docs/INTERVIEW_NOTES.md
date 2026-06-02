# Interview Notes

## 一句话介绍

Study Agent 是一个本地优先的 AI 学习助手，重点在多 Provider 模型接入、长期记忆、上下文分层、来源追溯和工程稳定性。

## 技术难点

1. **多模型 Provider 抽象** — 统一 OpenAI-compatible client 模式，支持 5+ 供应商切换，参数解析与 API 兼容性适配
2. **长期记忆写入安全** — safe writer + preview/confirm 机制，防止不可逆的记忆污染
3. **联网搜索来源追溯** — RSS 多源聚合 → 文章正文三层提取 → LLM digest → 全过程来源可回溯
4. **Streamlit 重渲染性能优化** — 多层缓存策略、batched session logging、性能预算控制
5. **CI / Ruff / detect-secrets 工程门禁** — 140 tests、Ruff clean、密钥泄露自动阻断

## 可讲亮点

- 不是简单 Prompt demo，而是可配置、可测试、可追踪的 AI 应用工程项目
- 上下文分层（fast / light / deep / archive）解决长对话场景下的 token 成本和记忆衰减
- SSRF 防护在联网搜索场景中的工程实现
- pip-tools 依赖锁定 + 精确版本管控，保证构建可复现
