# 个人学习 Agent 系统 v0.6.2 响应速度优化说明

## 1. 版本目标

v0.6.2 聚焦响应速度优化。

核心目标：

- 让普通聊天更快出现首 token
- 减少不必要的 LLM 调用
- 缩短普通聊天上下文
- 缓存高频视觉资源
- 降低 Streamlit rerun 带来的额外开销
- 降低不必要的写盘频率


## 2. performance_mode

v0.6.2 新增三档性能模式：

### 2.1 fast

- 默认倾向 `flash`
- 使用规则路由
- 使用 `light` 上下文
- 禁用 `LLM Router`
- 不读取 archive 级上下文
- 页面启动不自动跑全量健康检查

适用场景：

- 普通日常聊天
- 轻量提问
- 想优先要首 token 速度


### 2.2 standard

- 当前默认模式
- 规则路由优先
- 默认使用 `light` 上下文
- 允许在低置信度且 hybrid 开启时调用 `LLM Router`

适用场景：

- 大多数正常学习对话


### 2.3 deep

- 默认倾向 `pro`
- 使用更重的上下文
- 默认使用 `deep` 上下文

适用场景：

- 深度分析
- 项目讨论
- 论文修改
- 更复杂的问题拆解


## 3. context_mode

v0.6.2 引入三档上下文模式：

### 3.1 light

普通聊天默认使用 `light`。

读取内容：

- `summary.md`
- `current_focus.md`
- `learner_profile.md` 核心区
- 当前角色 prompt
- 最近 8 条消息

不读取：

- 完整 archive
- revision 类内容
- `wechat_group`


### 3.2 deep

在 `light` 的基础上额外读取：

- `progress.md`
- `project_context.md`
- `task_board.md`


### 3.3 archive

读取最完整的 memory 组，适合归档级、重上下文任务。


## 4. LLM 调用策略

### 4.1 普通聊天默认只允许一次 LLM 调用

普通聊天主路径默认只调用一次主模型。

目标是：

- 减少等待时间
- 避免多跳推理链路造成体感变慢


### 4.2 LLM Router 调用条件

`LLM Router` 只在以下条件同时满足时才允许调用：

- 规则路由结果为低置信度
- `hybrid` 路由模式已开启
- 当前不是 `fast` 模式

也就是说，`LLM Router` 不再作为普通聊天默认必经环节。


### 4.3 模型建议使用规则，不调用 LLM

模型建议逻辑改为规则判断。

不再为了“建议 flash 还是 pro”额外发起一次 LLM 调用。


## 5. 主聊天与结构化任务

### 5.1 主聊天使用 `stream_chat`

主聊天链路改为使用流式输出。

这样可以：

- 更快显示首 token
- 改善用户体感
- 支持记录 `llm_first_token_time`


### 5.2 结构化任务仍使用 `chat`

以下结构化任务仍保留非流式 `chat`：

- 课后更新
- 微信群反馈生成
- 微信群记忆提取
- 其它需要整块结构化结果的任务

这样可以保持结构化输出稳定性。


## 6. 视觉资源缓存

### 6.1 图片缓存

头像图片的 base64 data URI 转换加入缓存。

效果：

- 不在每轮 rerun 重复读取同一张图片
- 不重复做相同的 base64 编码


### 6.2 CSS 缓存思路

全局 CSS 注入集中管理。

目标是避免：

- 每个局部组件重复构造样式字符串
- 样式层的重复计算


## 7. 健康检查轻量化

页面启动只做轻量检查。

轻量检查只覆盖关键文件和基础状态，不执行完整扫描。

全量健康检查改为：

- 只在按钮点击时运行
- 结果缓存 60 秒

这样可以避免应用启动时的额外阻塞。


## 8. 写盘降频

### 8.1 current_session

`current_session.md` 不再在每条日志追加时立即写盘。

改为：

- 流式输出完成后再统一写一次


### 8.2 model_stats

主回复完整结束后再记录一次统计。

不在中间过程重复落盘。


### 8.3 perf_log

性能日志只在 `debug_mode=true` 时写入。

普通使用场景不额外增加写盘开销。


## 9. 普通聊天当前调用链路

普通聊天现在的主链路为：

1. 用户输入问题
2. 规则路由先执行
3. 只有低置信度且 hybrid 开启时，才允许 `LLM Router`
4. 根据 `performance_mode` 选择 `context_mode`
5. 读取对应 memory bundle
6. 组装最近 8 条消息和当前角色 prompt
7. 主聊天调用 `stream_chat`
8. 首 token 到达时记录 `llm_first_token_time`
9. 回复完成后记录总耗时、模型统计、session log


## 10. 调试指标

在 `debug_mode=true` 时，系统可显示并记录以下耗时：

- `route_time`
- `memory_read_time`
- `context_build_time`
- `llm_first_token_time`
- `llm_total_time`
- `ui_render_time`
- `total_time`


## 11. 手动验收步骤

### 验收 1：普通聊天是否流式输出

1. 启动应用
2. 发送一条普通聊天消息
3. 确认回复不是整块一次出现，而是流式输出


### 验收 2：首 token 是否更快

1. 打开 `debug_mode`
2. 发送普通聊天消息
3. 查看是否显示 `llm_first_token_time`
4. 观察首 token 是否明显早于完整回复结束时间


### 验收 3：fast 模式是否禁用 LLM Router

1. 将 `performance_mode` 切换为 `fast`
2. 发送一条普通聊天
3. 确认模型倾向 `flash`
4. 确认不会因为低置信度自动走 `LLM Router`


### 验收 4：standard 模式是否允许 hybrid 兜底

1. 将 `performance_mode` 切换为 `standard`
2. 将路由设为 `hybrid`
3. 发送一条规则难以判断的问题
4. 确认只有低置信度时才可能触发 `LLM Router`


### 验收 5：context_mode 是否生效

1. 普通聊天下确认默认使用 `light`
2. 深度任务或 `deep` 模式下确认上下文更重
3. 确认普通聊天不读取 archive 级内容


### 验收 6：健康检查是否轻量化

1. 重启页面
2. 确认启动阶段没有自动跑全量健康检查
3. 手动点击“系统健康检查”
4. 再次点击，确认 60 秒内结果可复用


### 验收 7：写盘是否降频

1. 发送一条普通聊天
2. 确认回复完成后才刷新 `current_session.md`
3. 在 `debug_mode=false` 下确认不会写 `perf_log`


## 12. 结论

v0.6.2 的优化重点不是削减功能，而是把“普通聊天主路径”收缩成更轻、更少跳、更少写盘、更少重复读取的链路。

重点原则：

- 普通聊天优先速度
- 深度任务保留能力
- 结构化任务继续按钮触发
- 调试信息只在需要时开启
