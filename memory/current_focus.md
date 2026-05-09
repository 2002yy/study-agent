# 当前焦点

## 优先任务

- 继续打磨微信群联网搜索体验，优先收口“最近性、可信度、摘要边界”这三件事
- 让侧栏里的“当前阶段 / 当前任务”与 `memory` 文本、README 和当前打包内容保持一致
- 继续压缩来源块和状态文案，减少群聊正文被技术细节挤占
- 在不增加无关复杂度的前提下，稳住正文提取三层回退链路和测试覆盖

## 暂缓任务

- 更重的 UI 视觉重做
- 更激进的联网搜索扩源
- 非必要的自动化流程继续增加

## 版本同步文件清单

> 改版本号时，以下文件 **必须全部同步**，缺一不可：

| 文件 | 字段/位置 |
|---|---|
| `src/mode_manager.py` | `current_version`、`next_version`（默认值） |
| `memory/internal_state.md` | `current_version`、`next_version` |
| `memory/summary.md` | `## 当前阶段`、`## 版本进度` |
| `memory/current_focus.md` | `## 不要误动` 中的版本号、本清单 |
| `memory/progress.md` | `## 当前阶段`、`## 已完成` |
| `memory/agent.md` | `## 当前阶段` |
| `PROJECT_PLAN.md` | 首行活跃阶段、章节标题、`## 文档分工` |
| `USER_GUIDE.md` | `## 1. 当前阶段`、README 引用路径 |
| `COMPREHENSIVE_PROJECT.md` | 首行开发阶段、`## 6. 当前推荐阅读顺序` |
| `FUTURE.md` | 当前阶段/下一阶段文本、章节标题 |
| `README_internal_modes.md` | 首行对应版本 |
| `README.md` | `## 更新日志` 新增条目 |
| `changelog/README_v{version}.md` | 文件名与内容同步新建/更新 |

## 不要误动

- 不改 router 主逻辑
- 不改 memory 写入边界
- 不把当前真实版本字段从 `v0.7.1` 强行改到别的值
- 不引入额外自动 LLM 调用
