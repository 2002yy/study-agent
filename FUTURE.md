# 未来方向

> 本文件记录当前版本之后的优先增强方向。  
> 当前开发阶段：`v0.7.2` 已落地，下一阶段主目标定位为 `v0.7.3`。

## v0.7.2 完成情况（代码质量收口）

v0.7.2 未按原计划走功能增量，而是做了一次全面的代码质量扫描与优化收口：

### Bug 修复
1. 测试版本断言 stale → 更新为 v0.7.1 并改名
2. 欢迎页硬编码版本 v0.6.2 → 改为动态读取 `load_runtime_modes().current_version`
3. LLM Router 用量统计 fix → 支持 `model_profile` 参数
4. 死代码 `main_panel.py` → 已删除

### 性能优化
5. `load_runtime_modes()` 加 `@st.cache_data(ttl=30)`，避免同次渲染重复读文件
6. YAML 路由配置修复重复解析（同次请求原为读两次）
7. diff 算法从 O(n×m) 改为 set 集合运算

### 架构改善
8. 公共常量抽取到 `src/constants.py`（消除 4 文件重复定义）
9. 代码栅栏清理抽取到 `src/text_utils.py`（消除 3 文件重复实现）
10. 文章提取模块独立到 `src/news/article_extractor.py`

### Streamlit 优化
11. wechat_panel fragment 内 `st.rerun()` 改为 `st.rerun(scope="fragment")`
12. sidebar fragment 内同上

### 健壮性
13. 关键路径裸 except 加日志（`router.py`/`llm_router.py`/`config.py`）
14. `after_session.py` LLM 调用加 try/except 崩溃保护
15. `requirements.txt` 移除误放的 pytest

---

## v0.7.3 重点

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
