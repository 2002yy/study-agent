# Quality-0 S2：发送次数硬门禁

> 状态：**能力已实现，默认关闭，零付费执行。**
> 目的：让「45 次 / 20·20·5 / 每轮 4·4·1」成为**发送前**的拒绝条件，而不是事后统计。

## 为什么费用上限不够

`SpendLedger` 回答的是「这次调用花得起钱吗」，不回答「这个臂还能不能发」。便宜的调用可以在金额额度内一直发下去，于是：

- 单轮可能超发第 5 次；
- 一个臂可以借用另一个臂的额度；
- 进程重启后计数消失。

金额与次数必须同时成立，且次数必须是持久的。

## 实现

`src/application/send_budget.py` 的 `SendBudget`：一个 SQLite 文件，一张上限表 + 一张计数表。

| 操作 | 语义 |
| --- | --- |
| `register({scope: cap})` | 每个 scope 只创建一次；重复注册相同值幂等，**改值拒绝**（不能靠重启放宽） |
| `reserve(key, scopes, units=1)` | 单事务内检查并写入**全部** scope：要么全部计入，要么全部不计 |
| `usage(scope)` / `remaining(scope)` | 只读统计 |
| 重置 | **没有**。失败的发送同样占用额度 |

事务使用 `BEGIN IMMEDIATE`，与 `SpendLedger` 同一套争用纪律；两个进程抢最后一个单位时只有一个能提交。

### 为什么不用现成的 `SqliteDecisionAdmission`

该类每个数据库只允许**一个不可变预算**，而预演需要三层嵌套 scope（实验 / 臂 / 轮次），且一次发送在 SDK 可能重试时要计多个单位。拆成多个文件就无法保证「要么处处计入、要么处处不计」；一个文件一个事务做得到这一点。语义和争用规则与它保持一致。

## 接入点

`src/llm_spend_guard.reserve_call()` —— 审计已确认这是全仓唯一的发送收口点：

```python
_charge_send(request_key=request_key, attempts=attempts)   # 先扣次数
...                                                         # 再预留金额
```

顺序是刻意的：金额预留不可退款，所以次数必须在它之前拒绝。

### 一次真实发送只计一次

生产路径上有两次 `reserve_call`，但只有第一次扣次数：

1. `SettlementLedgerAdapter.reserve()` 用 `settling_owner=self` 做**金额预留**，此时不持有授权 → 扣 1 次；
2. 传输层在 `pre_reserved_send(...)` 内再调 `reserve_call` → 走授权快捷分支，只校验边界后 `return 0.0`，**不再扣次数**。

两处都扣会让 45 次变成只能发 22 次；两处都不扣则 45 次形同虚设，因为真实发送全部走第 2 步。`test_an_admitted_send_is_counted_exactly_once` 锁住这一点。

### 拒绝必须是「停」，不是「本次失败」

`SendLimitExceeded` **不继承** `SpendLimitExceeded`。原因：金额拒绝是**单次**语义，既有调用方会把它翻译成 `cost_ledger_refused` 并继续跑；如果次数耗尽也走这条路，预演会继续执行后续轮次，把「没有调用模型」记成模型行为——正是 P1 那类「空答案」缺陷。

因此次数耗尽/不可读是**运行时中止**：

| 情况 | `reason` | 行为 |
| --- | --- | --- |
| 某个 scope 额度用尽 | `exhausted` | 抛 `SendLimitExceeded`，运行中止 |
| 发送 key 重复 | `conflict` | 同上 |
| 账本文件不可读/缺上限 | `unavailable` | 同上（不可读 ≠ 无上限） |

默认路径不受影响：没有绑定 scope 时不会产生这条异常。

### 先扣次数、后扣金额的取舍

两个额度在两个文件里，没有覆盖两者的单一事务，只能选一个泄漏方向：

- 先扣次数（当前实现）：金额拒绝时白扣 1 次 → 可用发送数略少，但**不会超发**；
- 先扣金额：次数拒绝时留下无法退款的金额预留 → 花费证据被虚增。

预演选择前者：宁可少发一次，也不要伪造花费。`test_a_money_refusal_still_spends_the_send_unit` 把这个取舍写成契约而不是意外。

绑定方式是上下文，默认不绑定 = 行为不变：

```python
budget = SendBudget(run_dir / "sends.sqlite")
budget.register({
    "experiment:q0-preview": 45,
    "arm:current": 20,
    "round:current:r1": 4,
})

with send_budget_scope(budget, ["experiment:q0-preview", "arm:current", "round:current:r1"]):
    ...  # 本轮的用户轮次
```

`pre_reserved_send` 持有的授权不会二次计费：授权对应的是**已经计入**的那次预留，重复发送由既有的 `send_authorization_consumed` 拦截。

## SDK 重试

`reserve_call(attempts=N)` 的 `N = retries + 1`，次数按 `N` 计。理由：一次 SDK 调用可能真的产生 N 次网络请求；只记 1 次会让未被批准的重试免费通过。金额预留本来就是按 `N` 计的最坏情况，两者口径一致。

## 负控（全部离线）

| 场景 | 期望 | 测试 |
| --- | --- | --- |
| 单轮第 5 次 | 发送前拒绝 | `test_the_fifth_send_in_a_round_is_refused_before_sending` |
| 臂额度耗尽不借用他人 | 别的臂照常、被拒的发送不消耗实验额度 | `test_an_exhausted_arm_does_not_consume_the_other_arm` |
| 实验总额跨臂 | 第 3 次被拒，且不污染臂计数 | `test_the_experiment_cap_binds_across_arms` |
| 重启续跑 | 新进程读同一文件后仍拒绝 | `test_a_restarted_process_cannot_reopen_the_budget`、`test_counts_survive_a_restart_in_another_process` |
| 两个进程抢最后 1 个单位 | 恰好一个成功 | `test_two_processes_cannot_both_take_the_last_unit` |
| 发送 key 重复使用 | 拒绝 | `test_reusing_a_send_key_is_refused` |
| 上限被放宽 | 拒绝 | `test_a_cap_cannot_be_widened_later` |
| 生产路径（适配器 + 传输层重校验） | 一次物理发送只计 1 次 | `test_an_admitted_send_is_counted_exactly_once` |
| 次数耗尽经过适配器 | 抛异常中止，而非返回 `cost_ledger_refused` | `test_an_exhausted_send_budget_aborts_instead_of_looking_like_a_cost_refusal` |
| 账本不可读 | 中止（不视为无上限） | `test_an_unreadable_send_budget_stops_the_run` |
| 金额拒绝 | 已扣的 1 次不回滚（明示取舍） | `test_a_money_refusal_still_spends_the_send_unit` |

## 非范围

- 不发起任何真实调用；
- 不改变默认行为（未绑定 scope 时零影响）；
- 不替代金额账本，两者同时生效；
- 不做自动重试策略调整（重试次数由既有配置决定，次数按最坏情况计入）。
