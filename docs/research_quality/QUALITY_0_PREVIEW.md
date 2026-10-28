# Quality-0 预演：计划与预算门禁（未执行）

> 目的：在任何人批准付费运行之前，把「四臂能否公平跑、预算能否硬停、结果能否汇总」先验证清楚。
> 本切片只提供**计划与门禁**，不发送任何请求，也不产出质量结论。

## 预演配置

`tests/fixtures/quality_0/preview_v1.json`：

| 项 | 值 |
| --- | --- |
| 题目 | `CHAT-01`、`GAME-02`、`CODE-01`、`FILE-02` |
| 对照臂 | `current`、`candidate`、`model_direct`（API）；`chatgpt`（人工） |
| 每题轮次 | 4 题 + 1 个追问 = 每臂 5 轮 |
| 用户输入轮次 | **20** |
| 需要 API 的轮次 | **15**（3 个 API 臂 × 5 轮；`chatgpt` 由人工执行） |
| 每轮发送上限 | SA 臂 ≤4，`model_direct` ≤1 |
| 最坏情况模型发送 | **45** |
| 费用硬上限 | **10 元** |

这些数字与 owner 给出的预演预算一致；工具从 fixture 推导，不靠手写常量。

### 身份是冻结的，不是「只要编号存在」

`load_preview()` 校验的是**集合与形状**，不是「ID 看起来合法」：

| 冻结项 | 拒绝条件 |
| --- | --- |
| 题目集合 | 换成别的题、少一道、多一道、重复一道 → `preview_tasks_mismatch` / `preview_tasks_duplicate` |
| 对照臂集合 | 少一个臂、重复一个臂、替换成别的 ID → `preview_arms_mismatch` / `preview_arms_duplicate` |
| 臂的执行方式 | `current`/`candidate`/`model_direct` 必须是 `api`，`chatgpt` 必须是 `manual` → `preview_arm_shape_mismatch` |
| 每轮发送额度 | `4 / 4 / 1 / 0`，改大改小都拒绝 → 同上 |
| 上限字段 | 四个字段必须齐全 → `preview_limits_missing` |

顺序不参与判定：题目和臂可以重排，但集合与形状不能变。
因此「换掉一道题但仍凑出 20/15/45」这条路走不通——那已经是另一个实验。

## 工具

```powershell
# 默认：只打印计划（题、轮次、每臂发送上限、是否在授权内）
python tools/run_quality_0_preview.py --plan

# 额外检查「如果真要付费，门禁是否齐全」——仍然不发请求
python tools/run_quality_0_preview.py --validate-budget

# 本切片明确拒绝：臂执行尚未接线
python tools/run_quality_0_preview.py --live   # exit 2
```

`--validate-budget` 要求以下全部成立，任一缺失即 `ok=false` 并列出原因：

| 检查 | 失败原因 |
| --- | --- |
| 输入/输出单价存在、有限、>0 | `pricing_missing_or_invalid` |
| `STUDY_AGENT_SETTLEMENT_ADMISSION` 已由操作者启用 | `admission_not_enabled` |
| 账本路径显式配置且为绝对路径 | `ledger_not_configured` / `ledger_not_absolute` |
| 实验 id 显式配置 | `experiment_not_configured` |
| 发送上限是正整数且 ≤45 | `limit_not_integer` / `limit_not_positive` / `limit_exceeds_authorisation` |
| 轮次上限是正整数且 ≤20 / ≤15 | 同上 |
| 费用上限是**有限正数**且 ≤10 元 | `limit_cost_invalid` / `limit_cost_exceeds_authorisation` |
| 计划本身在授权内 | `plan_sends_exceed_authorisation` 等 |
| 计划在声明上限内 | `plan_sends_exceed_declared_limit` 等 |
| **spend guard 的有效上限存在且 ≤ 声明值** | `experiment_cap_missing` / `experiment_cap_invalid` / `experiment_cap_exceeds_authorisation` / `experiment_cap_exceeds_declared_limit` |

### 为什么必须检查「有效上限」

`tests/fixtures/quality_0/preview_v1.json` 里的 `max_cost_cny` 只是**声明**，
真正拦住支出的是 `src/llm_spend_guard.py` 的 `experiment_cap_cny()`。
该函数读 `LLM_SPEND_EXPERIMENT_CAP_CNY`，未设置时回退到 `LLM_SPEND_CAP_CNY`；
两者都没有时 `reserve_call()` 直接 `return 0.0`——**等于不限费**。

所以只检查 fixture 里的 10 元是假门禁。现在的检查要求：

- 有效上限必须存在（否则 `experiment_cap_missing`）；
- 有效上限必须是有限正数；
- 有效上限不得超过 10 元，也不得比声明的上限更松。

### 数值校验为什么单独写

`declared_cost > 10` 对 `NaN` 恒为 `False`，对 `True` 恒为合法；`0` 和 `-1` 也会「不大于 10」。
因此费用先做类型、有限性、正数三重检查，再做比较；`NaN` / `Inf` / `-1` / `0` / `true` / `"10"`
全部落在 `limit_cost_invalid`。发送数与轮次数同样拒绝布尔、浮点、字符串和 ≤0。

## 为什么 `--live` 直接拒绝

臂执行尚未接线。若现在只跑 `model_direct`，会得出「只有直接模型有数据」的结论，
四臂无法比较，正是本预演要避免的假象。**宁可拒绝，也不产生半套数据。**

接线时需要补齐（单独 PR）：

1. `current` / `candidate` 的调用入口与上下文隔离；
2. **每轮**发送计数独立校验：单轮超过 4 次（`model_direct` 超过 1 次）立即中止，
   不允许用别的轮次少发来抵消；累计 45 次同样实时检查，不是事后统计；
3. 费用必须走 `llm_spend_guard` 的预留/结算，由账本里的有效上限强制，
   而不是只读 fixture 里的 10 元；
4. 每次运行写入 `run_id`、`head_sha`、任务集合与附件哈希、模型身份、
   每题每臂的发送次数、预留与实际费用、结果路径；失败不得自动重跑成成功；
5. 四臂必须使用**完全相同的题目、附件字节与追问文本**（附件哈希已在题集中固定）；
   任一臂失败则该次运行标记为不完整，不做补齐。

## 预演之后才做的事

| 步骤 | 产出 |
| --- | --- |
| 四臂各 5 轮真实运行 | 原始回答 + 发送/费用账本 |
| 人工按 `QUALITY_0.md` 六维评分 | 评分表（`--write-sheet`） |
| `--summarize` | 每臂 0–100、TTFU、成本（未测量会被标记为不完整） |
| 根据实际每题费用与耗时 | 再决定 20 题完整实验的预算 |

## 非范围

- 不发送模型请求、不搜索、不改产品默认行为；
- 不产出排名或质量结论；
- 不把本预演当作 Quality-0 的验收。
