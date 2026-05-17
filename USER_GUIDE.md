# 用户指南

## 1. 当前阶段

当前项目处于 `v0.7.8` 阶段，核心能力包括：

1. 单人学习对话
2. 课后更新预览与确认写入
3. 微信群互动（四位角色群聊）
4. 联网搜索与页面文本增强摘要
5. 多源新闻聚合与来源追溯
6. 性能预算系统（fast/standard/deep 三级 max_tokens）

日常使用请优先参考本文件和 [v0.7.8 发布说明](changelog/README_v0_7_7.md)。

## 2. 启动

```powershell
cd "C:\Users\96967\Desktop\study agent"
pip install -r requirements.txt
pip install -r requirements-dev.txt
Copy-Item .env.example .env
streamlit run app.py
```

浏览器打开 `http://localhost:8501`。

## 3. 基本配置

复制 `.env.example` 为 `.env`，按文件内注释填写。`.env.example` 是唯一准配置，本指南不重复列另一套。

配置以 `.env.example` 为准。当前推荐使用 Provider Profile 方式：

```text
LLM_PROVIDER_PROFILE=deepseek
DEEPSEEK_API_KEY=your_api_key_here
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL_FLASH_NAME=deepseek-chat
DEEPSEEK_MODEL_PRO_NAME=deepseek-reasoner
```

常用建议：

1. 日常对话和微信群互动默认用 `Flash`
2. 更复杂的课后总结、论文修改可切到 `Pro`
3. 不确定时可先保持自动配置

## 4. 微信群使用

### 4.1 群聊入口

微信群面板当前有三类主要动作：

1. `生成群聊开场`
2. `聊最近新闻`
3. `联网查点什么`

### 4.2 联网搜索

当前真实代码中，联网搜索会做多源聚合：

1. Google News
2. Bing News
3. 部分国内 RSSHub 新闻源

你可以直接输入：

```text
OpenAI 最近进展
Godot 4.6
国内 AI 芯片
美联储 利率
```

### 4.3 尝试读取正文

搜索表单里有：

```text
☑ 尝试读取正文
```

当前真实边界：

1. 最多抓 `10` 条新闻结果
2. 最多尝试读取前 `5` 条页面文本
3. 单条页面文本最多保留 `5000` 字
4. 读取失败会自动降级，不会让整轮群聊失败

如果你更在意速度，可以取消勾选。

### 4.4 来源追溯

搜索完成后，群聊记录里会写入：

```text
【联网检索】
查询：xxx
1. 标题 | 来源 | 时间 | 正文状态
   链接
```

这样后续回看 `chat/wechat_group.md` 时，能知道讨论依据来自哪些搜索结果。

## 5. 课后更新

标准流程：

1. 正常进行一轮学习对话
2. 点击 `生成课后更新预览`
3. 查看各类更新建议
4. 选择需要写入的项目
5. 点击 `确认写入长期记忆`
6. 需要时再生成微信群反馈

所有正式写入都应走确认流程，不建议直接手改核心 memory 文件。

## 6. 当前模式说明

你平时最常用的是这几项：

1. `relationship_mode`: `standard / warm / close`
2. `performance_mode`: `fast / standard / deep`
3. `memory_mode`: `preview / confirm_write / readonly / locked`
4. `safe_mode`: 是否禁止写入长期记忆

如果只是测试新功能，建议：

1. `memory_mode = preview`
2. 需要真写时再临时确认
3. 不放心时开启 `safe_mode`

## 7. 导出与打包

### 7.1 导出

侧栏支持导出：

1. 学习报告
2. docx 报告
3. 项目状态
4. 微信群记录
5. session 归档

### 7.2 打包

当前推荐：

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\package_project.ps1
```

打包时会自动排除：

1. `.env` / `.env.*`
2. `logs/`
3. `backups/`
4. `exports/`
5. `chat/archive/`
6. `article_text_replacement_files*`

## 8. 测试

当前建议命令：

```powershell
python -m compileall -q .
python -m pytest -q
```

如果改了微信群联网相关逻辑，建议再手测：

1. `聊最近新闻`
2. 自定义搜索 `OpenAI 最近进展`
3. 勾选与取消 `尝试读取正文` 各试一次

## 9. 文档定位

当前仓库文档建议这样看：

1. `changelog/README_v0_7_1.md`: 当前版本检查包说明
2. `USER_GUIDE.md`: 当前使用指南
3. `PROJECT_PLAN.md`: 当前阶段规划与里程碑
4. `FUTURE.md`: 下一阶段方向
5. `COMPREHENSIVE_PROJECT.md`: 面向新协作者的总体说明
6. `README_v0_1.md` 到 `README_v0_6_9.md`: 历史版本记录
