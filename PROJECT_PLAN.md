# Study Agent 项目规划

> 当前活跃阶段：`v0.8.0`  
> 当前状态：v0.8.0 已发布，基于 v0.7.8 的全量变更（性能预算、依赖锁定、状态模型、CI 门禁）追加文档版本同步与 UI 中文标签。

## 当前定位

当前项目已经不再只是"学习对话 + 群聊反馈"，而是进入：

```text
学习对话
+ 课后更新
+ 微信群互动
+ 轻量联网资讯检索
+ 页面文本增强摘要
+ 记忆系统渐进沉淀
```

## v0.7.2 已完成的重点

v0.7.2 是一次代码质量收口，不是功能增量：

1. 修复 4 个 Bug（测试版本断言 stale、欢迎页硬编码版本、LLM Router 用量统计错误、死代码删除）
2. `load_runtime_modes()` 加 `@st.cache_data(ttl=30)` 缓存，避免同次渲染重复读文件
3. YAML 路由配置修复重复解析（同次请求原读两次）
4. diff 算法从 O(n×m) 改为 set 集合运算
5. 公共常量抽取到 `src/constants.py`（消除 sidebar/status_bar/chat_panel/wechat_panel 四文件重复）
6. 代码栅栏清理 `strip_code_fences()` 抽取到 `src/text_utils.py`
7. 文章提取模块独立到 `src/news/article_extractor.py`
8. Streamlit fragment 内 `st.rerun()` 全部改为 `st.rerun(scope="fragment")`
9. 关键路径裸 except 加日志（`log_utils.py`），`after_session.py` LLM 调用加崩溃保护
10. `requirements.txt` 清理误放的 pytest
11. 全量 72 测试通过，changelog 写入 `changelog/README_v0_7_2.md`

## v0.7.3 已完成的重点

v0.7.3 是一次服务层拆分与工程化收口：

1. wechat news round 服务下沉到 `src/wechat_service.py`
2. session flush 批量提交（按性能模式分频次）
3. GitHub Actions CI 落地（pytest + ruff + mypy）
4. 架构级回归测试（`tests/test_architecture_flows.py`）
5. LLM client 参数/配置扩展（provider_profile、task_name、JSON mode 等）
6. YAML runtime state 迁移为真源（config/runtime_state.yaml）
7. 全量 108 测试通过，changelog 写入 `changelog/README_v0_7_3.md`

## v0.7.4 已完成的重点

v0.7.4 是一次工程体验收口：

1. 自动化版本管理工具 `tools/bump_version.py`
2. LLM 配置文档化（.env.example 扩展至 50 行，README 配置节重写）
3. NewsRoundResult 结果对象化（source_block / article_coverage / elapsed_ms / warnings）
4. UI 来源可信度展示（覆盖率条、警告逐条展示、条目图标区分）

## v0.8.1 目标

下一阶段回归 UI 打磨与稳定性：

1. UI 打磨（搜索按钮 cooldown、状态反馈、失败 fallback）
2. 会话状态无界增长防护（session_state 上限 + TTL 淘汰）
3. 测试覆盖扩展（UI 模块、LLM 集成、写入操作）
4. 引用与来源体验优化（折叠、链接可点击、来源详情）

## 文档分工

1. `CHANGELOG.md`: 当前版本说明
2. `USER_GUIDE.md`: 当前使用方法
3. `FUTURE.md`: 下一阶段方向
4. 历史 `README_v0_x.md`: 版本留档，不再作为当前状态依据
