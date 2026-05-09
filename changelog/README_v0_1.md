# v0.1 验收文档

## 1. 安装依赖

```powershell
pip install -r requirements.txt
```

依赖项：`streamlit`、`openai`、`python-dotenv`

## 2. 配置 .env

```powershell
Copy-Item .env.example .env
```

编辑 `.env`，填入真实值：

```
OPENAI_API_KEY=your_api_key_here
OPENAI_BASE_URL=你的接口地址
MODEL_NAME=模型名称
```

## 3. 启动 Streamlit

```powershell
streamlit run app.py
```

浏览器打开提示的地址（默认 `http://localhost:8501`）。

## 4. 测试四个角色是否正常回复

在左侧栏分别选择每个角色，输入问题，确认：

| 角色 | 测试输入 | 预期表现 |
|------|----------|----------|
| 三月七 | "什么是卷积？" | 活泼、用提问引导，不直接给答案 |
| 刻晴 | "我想学深度学习，但不知道从哪里开始" | 直接、收束目标，给出可执行步骤 |
| 纳西妲 | "用一句话概括注意力机制的本质" | 温和、善用类比、提炼核心 |
| 流萤 | "今天学完了，有点累" | 轻柔、陪伴感，不越位教学 |

## 5. 确认日志保存成功

1. 进行一次对话后，点击左侧栏 **结束本轮并保存日志**
2. 检查 `logs/sessions/` 目录，应出现 `YYYY-MM-DD_HH-mm-ss.md` 文件
3. 打开文件，确认包含：时间、角色、模式、用户输入、Agent 回复，中文不乱码

## 6. v0.1 不包含的功能

- 长期记忆（不读取 progress.md / learner_profile.md / current_focus.md）
- 课后更新（不下课自动更新状态文件）
- 微信群（无 wechat_unread.md 生成）
- 自动模式路由（需手动选择模式）
- 自动角色调度（需手动选择角色）
- 头像、背景、气泡等视觉增强
