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

## 工具

```powershell
# 默认：只打印计划（题、轮次、发送上限、是否在授权内）
python tools/run_quality_0_preview.py

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
| 账本路径显式配置 | `ledger_not_configured` |
| 实验 id 显式配置 | `experiment_not_configured` |
| 计划的发送数 ≤45 | `plan_sends_exceed_authorisation` |
| 声明的上限 ≤45 | `limit_sends_exceeds_authorisation` |
| 声明的费用 ≤10 元 | `limit_cost_exceeds_authorisation` |

## 为什么 `--live` 直接拒绝

臂执行尚未接线。若现在只跑 `model_direct`，会得出「只有直接模型有数据」的结论，
四臂无法比较，正是本预演要避免的假象。**宁可拒绝，也不产生半套数据。**

接线时需要补齐（单独 PR）：

1. `current` / `candidate` 的调用入口与上下文隔离；
2. 每轮发送计数必须实时对照 45 次上限，超限即中止（不是事后统计）；
3. 费用预留与结算沿用 `llm_spend_guard`，并保留账本；
4. 首轮不论成败都写入 `run_id`、`head_sha`、每题每臂的发送次数与费用；
5. 四臂必须使用**完全相同的题目、附件字节与追问文本**（附件哈希已在题集中固定）。

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
