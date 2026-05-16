# Study Agent 项目全貌

> 面向新协作者和无上下文接手者的当前阶段总览。  
> 当前开发阶段：`v0.7.3`

## 1. 项目定义

这是一个基于 `Python + Streamlit` 的学习管理 Agent，当前核心体验包括：

1. 学习对话与角色化教学
2. 课后更新预览与确认写入
3. 微信群互动与记忆候选提取
4. 轻量联网资讯检索与页面文本增强摘要

## 2. 当前真实状态

当前代码已经进入：

```text
学习对话
+ 课后更新
+ 微信群互动
+ 联网搜索
+ 页面文本增强
+ 来源追溯
```

其中联网能力当前是轻量方案，不是完整搜索引擎。

## 3. 关键模块

### 核心逻辑

1. `src/wechat.py`: 微信群、搜索、页面读取、来源块、摘要
2. `src/mode_manager.py`: 运行态模式和版本状态
3. `src/session_logger.py`: 会话日志与安全写入
4. `src/safe_writer.py`: 原子写入、备份、tmp 清理
5. `src/llm_client.py`: LLM 调用与 client 重置

### UI

1. `src/ui/wechat_panel.py`: 微信群主面板
2. `src/ui/sidebar.py`: 设置、模式、记忆、导出
3. `src/ui/status_bar.py`: 状态与版本展示

### 文档

1. `changelog/README_v0_7_1.md`: 当前版本说明
2. `USER_GUIDE.md`: 当前使用指南
3. `PROJECT_PLAN.md`: 当前阶段规划
4. `FUTURE.md`: 下一阶段方向
5. 历史 `README_v0_x.md`: 历史留档

## 4. 当前联网能力边界

真实代码当前边界：

1. 搜索最多保留 10 条结果
2. 最多读取前 5 条页面文本
3. 单条页面文本最多保留 5000 字
4. 读取失败自动降级
5. 支持多源聚合与去重
6. 阻止本地 / 私有 / 特殊地址访问

## 5. 当前开发重点

当前阶段的重点已经从“把功能做出来”转向：

1. 搜索结果质量
2. 页面文本质量
3. 引用与来源展示
4. 打包与状态一致性
5. 测试覆盖关键边界

## 6. 当前推荐阅读顺序

如果你要快速接手，推荐顺序：

1. `changelog/README_v0_7_1.md`
2. `USER_GUIDE.md`
3. `PROJECT_PLAN.md`
4. `src/wechat.py`
5. `src/ui/wechat_panel.py`
