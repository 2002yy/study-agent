# 未来方向

> 本文件记录当前版本之后的优先增强方向。  
> 当前开发阶段：`v0.7.3` 已落地，下一阶段主目标定位为 `v0.7.4`。

## v0.7.3 完成情况（服务层拆分与工程化收口）

v0.7.3 是一次服务层拆分与工程化收口：

### 服务层拆分
1. wechat news round 下沉到 `src/wechat_service.py`
2. `wechat_panel.py` 专注 UI 渲染与按钮流

### 工程化
3. session flush 批量提交策略（fast: 4轮, standard: 2轮, debug: 每轮）
4. GitHub Actions CI（pytest + ruff + mypy）
5. 架构级回归测试覆盖
6. LLM client 参数/配置扩展（provider_profile, task_name, JSON mode 等）
7. YAML runtime state 迁移为机器真源，markdown 视图自动同步

### 测试
8. 新增 5 个测试文件（wechat_service, session_logger_flush, architecture_flows, llm_client_options, mode_manager_yaml）
9. 全量 108 测试通过

---

## v0.7.4 重点

### 1. 联网搜索质量提升

优先考虑：

1. 进一步优化多源结果质量
2. 更稳地区分"基于标题"与"基于页面文本"
3. 对 Google News 中转页做更稳的处理
4. 继续减少低质量页面文本混入

### 2. 引用与来源体验

优先考虑：

1. 在 UI 中折叠展示来源
2. 链接支持点击打开
3. 支持查看本轮来源详情
4. 支持手动清理搜索缓存

### 3. 搜索交互体验

优先考虑：

1. 搜索按钮 cooldown
2. 更明确的 running 状态
3. 上次搜索结果复用
4. 网络失败 fallback 话题

### 4. 测试覆盖扩展

优先考虑：

1. UI 模块基础测试覆盖（sidebar/chat_panel/status_bar 等）
2. LLM 调用集成测试（含 mock）
3. 内存写入/备份/导出测试补充
4. session_logger 无界增长写入上限

---

## 中期方向

### 1. 会话状态管理

如果 Streamlit session_state 持续膨胀：

1. 会话数量上限 + TTL 淘汰
2. 历史会话懒加载

### 2. 运行态存储升级

如果 Windows 文件锁仍偶发，可考虑：

1. JSON 运行态
2. sqlite 状态存储
3. 更细粒度的写入节流

### 3. 更强的搜索能力

如果后续不仅是资讯检索，可考虑：

1. 更稳定的新闻 API
2. 更通用的网页搜索 API
3. PDF / 论文 / 技术页面专门处理链路
