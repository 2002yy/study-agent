# 项目上下文

## 项目结构

```
study_agent/
├── app.py              # Streamlit UI
├── src/
│   ├── llm_client.py   # API 封装
│   ├── role_manager.py # 角色加载
│   └── session_logger.py # 日志保存
├── roles/              # 4 角色人设
├── memory/             # 长期状态（v0.2 只读）
├── chat/               # 微信（v0.4）
├── logs/sessions/      # 会话存档
└── PROJECT_PLAN.md
```

## v0.1 已通过验收

- 四个角色正常回复，风格可区分
- 五种模式切换有效
- Flash / Pro 双模型切换正常
- 会话日志 UTF-8 保存，中文不乱码
- 配置缺失时不崩溃，给出中文错误提示

## v0.2 当前阶段

只做读取和展示，不做自动写入。写入留到 v0.3。
