# 学习闭环深化计划（复审后续）

> **For agentic workers:** 用 superpowers:executing-plans 逐 Task 推进，checkbox 跟踪。

**Goal:** 在 P0（已完成）基础上，补齐"结束学习 -> 自动总结 -> 确认记忆 -> 准确恢复"闭环，收敛次要功能，并加固路由输入校验。

**Spec 依据:** 远程复审 P0/P1/P2 列表 + 2026-07-12 学习工作台设计文档。

**测试命令:** 后端 `$env:PYTHONPATH="."; python -m pytest -q`；前端 `npx vitest run`（在 `frontend/`，用 `node_modules\.bin\vitest.cmd`）；构建 `node_modules\.bin\vite.cmd build`。

---

## P0 完成情况（已推送，86fb56c..a4f2b9d）

1. 阶段轨迹实时更新（onDone 追加 pedagogyPhases）
2. 恢复读取 `pedagogy_snapshot.phase`（原误读顶层 phase）
3. 恢复 `lastChat.pedagogy`
4. 后端 session turns 返回逐轮 route_snapshot/rag_snapshot
5. 前端恢复逐轮 RAG/联网证据
6. 协议码（socratic_rediscovery/feynman_diagnosis/project_execution/direct_answer）+ 阶段中文标签
7. "掌握度"->"本轮理解进度"，移除误导百分比
8. 欢迎语移除"右侧检查"旧三栏措辞
9. README + USER_GUIDE 重新定位到教学法驱动
10. 窄屏学习状态条 + 顶栏图标防溢出

---

## P0.11: 路由 mode 校验加固（先做，小）

**问题:** `router.py:277` 对"非 auto 但非法"的 selected_mode 原样透传给引擎，静默落 direct（乱码/拼写错误被无声吞掉）。

**Files:** `src/router.py`、`tests/test_router.py`

- [ ] 写失败测试：`selected_mode="苏格拉底?"`（非法）-> route.mode 回退为有效值（auto 行为）+ reason 含 warning
- [ ] 实现：在 route_request 内，若 `selected_mode` 既非 auto/自动 也非 `{"普通","苏格拉底","费曼","项目"}`，记 warning 并按 auto 处理（`mode_is_auto=True`）
- [ ] 测试通过 + 全量回归 + 提交

---

## P1: 闭合学习闭环

现状：`src/after_session.py:97 generate_after_session_updates` 已能 LLM 生成候选；`memory_service` 已有 preview/commit；但**无 after-session API 路由**，前端 MemoryPanel 靠手写。

### P1.1: after-session 自动候选端点
**Files:** `src/api/routes/memory_routes.py`（或 session_routes）、`src/application/memory_service.py`、`frontend/src/api.ts`、`frontend/src/types.ts`
- [ ] 后端：新增 `POST /sessions/{session_id}/after-session/preview` -> 调 `generate_after_session_updates`（基于 thread.learning_state + 最近 turns）-> 经 `memory_service.create` 生成 MemoryRun 预览 -> 返回 run_id + 候选
- [ ] 后端测试：端点返回非空调候选（mock LLM）
- [ ] 前端 api.ts + types：加 `requestAfterSessionPreview(sessionId)`
- [ ] 提交

### P1.2: "结束本次学习"按钮 + MemoryPanel 自动填充
**Files:** `frontend/src/features/single-chat/ChatPanel.tsx`（顶栏加"结束学习"按钮）、`frontend/src/features/learning-memory/MemoryPanel.tsx`、`memoryController.ts`
- [ ] ChatPanel 顶栏加"结束本次学习"主按钮 -> 调 after-session preview -> 把候选灌入 MemoryPanel + 打开记忆抽屉
- [ ] MemoryPanel：支持"由 after-session 填充"态（候选只读+勾选确认，而非空白手写）
- [ ] 提交

### P1.3: 恢复卡（替代三段原始 Markdown）
**Files:** `frontend/src/features/single-chat/ChatPanel.tsx`（home-brief 区）
- [ ] 老用户：用 lastChat.route.learning_state 渲染结构化恢复卡（目标/已确认点/当前缺口/下一步）+ [继续] [新主题]
- [ ] 新用户：保留现有快捷提问引导
- [ ] 提交

### P1.4: 评估决定显示（已验证/待验证）
**Files:** `frontend/src/features/learning/LearningPanel.tsx`、`types.ts`
- [ ] learning_state.payload.pedagogy_evaluation / last_response_violations -> 在"已确认点"旁显示"最近评估：通过/待复核/未通过"
- [ ] 提交

---

## P2: 收敛聚焦

### P2.1: 顶栏 dock 收敛为 4 + "更多"菜单
- [ ] 一级：上传资料 / 会话历史 / 结束学习 / 更多
- [ ] "更多"抽屉内：来源与知识库 / 设置 / 群聊 / 新闻 / 工具 / 工作流时间线

### P2.2: 设置分基础/高级
- [ ] 基础：角色、教学模式、模型档位、RAG 开关
- [ ] 高级（折叠）：top_k、min_score、检索模式、上下文层、氛围

### P2.3: 普通用户不暴露内部
- [ ] MemoryPanel 高级详情才显示 current_focus.md 等文件名
- [ ] RAG 高级参数默认隐藏

### P2.4: 角色/氛围降为表达层
- [ ] 角色与氛围移入"表达"设置区，不再作为主产品卖点文案

---

## 执行顺序

P0.11（加固）-> P1.1 -> P1.2 -> P1.3 -> P1.4 -> P2.1 -> P2.2 -> P2.3 -> P2.4

每个 Task TDD（能测则测）+ 单独提交。P1.1/P1.2 是闭环核心，优先。
