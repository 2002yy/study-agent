# Study Agent

AI 学习搭子系统 —— 联网搜索 + 角色群聊 + 课后总结。

## 功能

- **单人学习对话** — 与 AI 一对一讨论学习内容
- **课后更新预览** — 总结学习进度，确认后写入记忆
- **微信群互动** — 四位角色（三月七、刻晴、纳西妲、流萤）群聊讨论
- **联网搜索** — 多源新闻聚合（Google News + Bing News + RSSHub），支持页面正文读取
- **来源追溯** — 搜索结果写入群聊记录，可回溯依据

## 快速开始

```bash
cd study-agent     # 进入项目目录
pip install -r requirements.txt
pip install -r requirements-dev.txt
cp .env.example .env
streamlit run app.py
```

浏览器打开 `http://localhost:8501`

## 环境配置

编辑 `.env`：

```
OPENAI_API_KEY=your_api_key_here
OPENAI_BASE_URL=https://api.deepseek.com/v1
MODEL_FLASH_NAME=deepseek-v4-flash
MODEL_PRO_NAME=deepseek-v4-pro
DEFAULT_MODEL_PROFILE=pro
```

## 项目结构

```
src/          源代码
tests/        测试
chat/         群聊记录
memory/       记忆文件
roles/        角色定义
templates/    Prompt 模板
config/       路由配置
```

## 许可

仅供个人学习使用。
