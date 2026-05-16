# 任务看板

## 当前 Sprint (v0.7.4)

### 进行中

- 联网搜索多源结果质量进一步优化
- "基于标题"与"基于页面文本"区分增强

### 待开始

- 来源块 UI 折叠与链接点击体验
- 搜索按钮 cooldown / running 状态增强
- 网络失败 fallback 话题生成
- UI 模块基础测试覆盖（sidebar/chat_panel/status_bar）
- LLM 调用集成测试（含 mock）
- 会话状态无界增长上限

### 已完成 (v0.7.3)

- wechat_service 拆分
- session flush 批量提交
- GitHub Actions CI 落地
- 架构级测试覆盖
- LLM client 参数/配置扩展
- YAML runtime state 真源化

### 已完成 (v0.7.2)

- 测试版本断言 stale 修复
- 欢迎页硬编码版本动态化
- LLM Router 用量统计 fix
- 死代码 `main_panel.py` 删除
- `load_runtime_modes()` 缓存优化
- YAML 路由重复解析修复
- diff 算法 O(n×m) → set 运算
- 公共常量抽取到 `constants.py`
- 代码栅栏清理 `strip_code_fences()` 抽公共
- 文章提取模块独立到 `src/news/`
- Streamlit fragment rerun 反模式修复
- 关键路径错误处理日志增强
- `after_session.py` 崩溃保护
- `requirements.txt` 依赖清理

### 已完成 (v0.7.1 及更早)

- 默认入口切换为微信群
- 群聊用户右侧、角色左侧的对话布局
- 群聊流式回复与四角色归一化
- 打包脚本 `.env.*` 排除与 key 扫描
- 未知 speaker 不再伪装成用户
- safe_writer 临时文件唯一化
- 多源 RSS 聚合
- 正文三层提取：trafilatura / readability-lxml / HTMLParser
- 90 天搜索窗口
- 来源块压缩

## 禁止误动清单

- 不重构 v0.1 双模型主链路
- 不绕过 safe_writer
- 不自动写入长期记忆
- 不新增不必要的自动 LLM 调用

## 验收标准模板

- [ ] 功能行为符合预期
- [ ] 已有测试全部通过
- [ ] 日志记录完整
- [ ] 不破坏现有功能
