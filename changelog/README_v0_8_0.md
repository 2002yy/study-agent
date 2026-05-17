# Study Agent v0.8.0 发布说明 / Release Notes

> 文档同步 + UI 中文标签 + 工程收口。合并 v0.7.8 全量变更与本轮文档/UI 统一。

---

## v0.8.0 新增

### 1. 文档版本同步

5 份文档统一升至 v0.8.0：

- `USER_GUIDE.md`：版本号、配置示例（Provider Profile）、能力清单更新
- `PROJECT_PLAN.md` / `FUTURE.md` / `COMPREHENSIVE_PROJECT.md`：版本升级、模块描述与实际代码对齐（wechat.py 拆分为 5 个子模块）、文档引用路径修正
- `changelog/README_v0_7_7.md`：标题中英双语、wechat.py 行数/职责修正

### 2. UI 中文标签

用户可见文案统一为中文主导：

- 模型标签：`自动` / `Flash（快速）` / `Pro（高质量）`
- 性能模式：`快速` / `标准` / `深度`
- 状态栏统计：`Flash 调用` / `路由调用` / `上次延迟` / `估算成本`
- Debug 性能行：`性能: 路由 0.xxx | 记忆 0.xxx | 上下文 0.xxx | ...`

### 3. 语言规范确立

仓库采用中文主导 + 英文技术名保留的策略：

| 类型 | 语言 |
|------|------|
| README / CHANGELOG | 中文主导，标题中英双语 |
| 用户文档 | 全中文 |
| UI 文案 | 中文 |
| 代码/配置变量/函数名 | 保留英文 |

---

## 合并 v0.7.8 变更

以下变更在开发分支上累积，与 v0.8.0 一并发布：

### 性能预算系统

新模块 `src/performance_budget.py`，按 fast/standard/deep 三档分配 max_tokens：

- 主聊天：700 / 1100 / 1600
- 群聊回复：520 / 760 / 1050，历史行数自适应（16 / 28 / 40）
- 开场生成：420 / 620 / 850
- 新闻摘要：650 / 950 / 1300
- 新闻讨论：520 / 760 / 1000

### 依赖锁定

迁移至 pip-tools 工作流：`requirements.in` → `requirements.txt`（锁定精确版本）。

### 状态模型文档化

`docs/STATE_MODEL.md`：真源层级、迁移指南、清理清单。YAML 为真源，MD 文件为视图。

### CI 门禁升级

`detect-secrets` 改为硬门禁（移除 `continue-on-error`）。

### 入口页新闻流程修复

- 群聊未开始时也能显示新闻阶段面板
- `_clear_wechat_news_state` 统一清理
- `run_discussion_stage` 正确调用 `update_wechat_join_state`

### README 重构

展示型结构：产品定位 / Demo / 使用流程 / 架构图 / Roadmap。

### `.gitignore` 收口

排除 `config/runtime_state.yaml`、`memory/`。

### 测试

新增 28 个测试，总测试数 140，Ruff clean。

---

## 兼容性

- 无新增依赖
- 140 测试通过
- Ruff clean
- 所有对外接口保持向后兼容
