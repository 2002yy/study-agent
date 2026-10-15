# Async Deep-1A — 持久授权 / 两层费用账本 / 执行租约 / 状态机（可编码合同）

> 状态：**Frozen for implementation（待一次性放行）**。总体合同见 [`ASYNC_DEEP_1_CONTRACT.md`](ASYNC_DEEP_1_CONTRACT.md) @ `f8769113`。
> 本文件只覆盖 **Async-1A**：把最容易造成**资金损失、双重执行、不可恢复状态**的接口落到可编码级别。
> 本阶段**不实现迁移、不改运行时、不调用模型、不触发 CI、不创建 PR**（已完成的只读核查不计费）。
>
> 迁移编号：**以实施时的 main 为准**；下文的 `26` 只是基于当前 `SCHEMA_VERSION=25` 的候选基线，**不预先假定**。
> 原 A/B/C 验收继续 **FAILED**；合并门继续关闭。

## 0. 已核查的现有语义（本设计的约束来源）

| 事实 | 位置 | 影响 |
| --- | --- | --- |
| `begin_operation(run_id, *, operation_id, stage, stale_after_seconds=120)` 使用 `BEGIN IMMEDIATE` + `version` CAS 原子获取 | `web_lookup_repository.py:429` | 可作为租约底座，但**陈旧判断只看开始时间** |
| 可获取状态包含 **`cancelled`**；获取时会 **`cancel_requested_at=None`** | 同上（第 461、472 行） | **N13 风险**：普通恢复会清除用户取消事实并重新起跑 |
| `_operation_is_stale` = `active_operation_started_at < now-120s` | 同上 79–84 | 长读取会被误判陈旧 → 需要**心跳/续期** |
| 写入需 `_assert_running_owner(run, operation_id)`（`transition_stage` 等） | 同上 502 | 现有所有权校验**只到 operation_id**，无代次 → 需要 **fencing token** |
| `WebLookupRun` 已有 `active_operation_id / active_operation_started_at / cancel_requested_at / version / owner_thread_id` | `runtime_entities.py:224` | 可扩展，无需新研究状态表 |
| 检查点已持久化 plan/notes/steps/steering/computations/incremental_budget | `checkpoint(...)` | 恢复事实齐备 |
| 费用账本 `llm_spend_guard` 预留额在内存 | `src/llm_spend_guard.py` | 1A 改为持久两层账本 |

## 1. 三个必须先钉死的语义（评审指定）

### 1.1 `paused` 不自动恢复：资格谓词

`paused` 有两种含义，必须区分：

| 子类 | 判定 | 调度行为 |
| --- | --- | --- |
| `paused(authorization_exhausted)` | 无有效授权（`deadline` 已过 / 调用或费用用尽） | **不得自动启动**，等待**再次授权** |
| `paused(boundary_wait)` | 仍有有效授权，但当前不可推进（如租约被占用、等待排队） | 可被调度器在授权仍有效时接管 |

**自动启动资格谓词（1A 定义，1B 接调度器）**：

```
eligible(run) :=
      has_authorization(run)                      # 存在未过期、未耗尽的授权记录
  AND run.status ∈ { pending, running, paused, failed }   # 见 §4 状态机
  AND run.status ≠ cancelled                        # N13：终态不可自动恢复
  AND lease_acquirable(run)                         # 无活跃租约，或租约已过期
  AND has_executable_work(run)                      # 存在 pending 计划任务 或 未执行转向 或 待续计算
```

- **新建的已授权 `pending` run 必须可被优先发现**（否则用户刚授权的任务不会被启动）。
- 进度端点/观察者只读，不参与资格判定。

### 1.2 租约必须有 fencing 语义

不只保存 `operation_id`，新增 **租约代次（epoch）**：

```
lease = { operation_id, epoch:int, holder:str, heartbeat_at:iso, expires_at:iso }
```

规则：
1. **获取/接管**：`epoch = previous_epoch + 1`，写回并返回；任何执行者持有的 `epoch` 必须与库中一致才能写入。
2. **续期（心跳）**：只更新 `heartbeat_at` / `expires_at`，**不得**触碰 `steering`、`plan`、`computations`、`incremental_budget` 等并发上下文（避免心跳覆盖并发 steering）。
3. **失约 fencing**：陈旧回收（接管）后，旧执行者的写入因 `epoch` 不匹配而**被拒绝**（`LeaseLost`），不得产生新结果。
4. **长 HTTP 请求不导致误接管**：失效判据使用 `expires_at`（由心跳刷新），而**不是**单个请求的开始时间；心跳周期 < `lease_ttl`（建议 ttl 90 s、心跳 30 s，具体值在 1A 编码时定）。
5. 显式取消写入 `cancel_requested_at` 后，租约持有者下一步 `ensure_active()` 退出，且其后续写入因租约状态被拒绝。

### 1.3 费用：先授权后预留，且原子核验

- **授权记录可以先于 run 存在**（截图视觉调用可能早于研究 run 创建）：授权表以 `authorization_id` 为主键；视觉调用创建授权并**立即**预留，随后 run 创建时通过 `bind_run(authorization_id, run_id)` 关联。
- **请求前预留与全局限额检查在同一事务内完成**（`BEGIN IMMEDIATE`）：任一不足即**拒绝该请求**。
- **取消后不再发起新的付费请求**；但**已发出的在途请求可能仍产生费用**——设计**不承诺撤销已发生的计费**，只保证“取消后不再新增请求”。

### 1.4 两种时间必须分开

| 名称 | 定义 | 存储 | 是否因恢复刷新 |
| --- | --- | --- | --- |
| **绝对授权期限** `deadline_at` | 自**用户批准时刻**起 15 分钟 | 授权表 | **否**（恢复/重连/重启都不刷新） |
| **实际执行耗时** `executed_seconds` | 跨暂停累计的真实执行时间（研究内部资源预算用） | 授权表/run 账本 | 累加，不从零重来 |

## 2. 数据模型（迁移草案）

> 编号以实施时 main 为准。以下为**草案**，用于评审结构而非最终 SQL。

### 2.1 `research_authorizations`（持久授权）

| 列 | 类型 | 说明 |
| --- | --- | --- |
| `id` | TEXT PK | `auth_<uuid>`；**可先于 run 存在** |
| `owner_thread_id` | TEXT | 会话归属（N14 鉴权依据） |
| `run_id` | TEXT NULL | 由 `bind_run` 后置绑定；未绑定时为 NULL |
| `granted_at` / `deadline_at` | TEXT | 绝对期限（§1.4） |
| `authorization_version` | INTEGER | 追加授权时递增（追加 ≠ 刷新 15 分钟） |
| `max_model_calls` / `max_vision_calls` / `max_searches` / `max_reads` | INTEGER | 次数上限 |
| `max_spend_cny` | REAL | run 级费用上限 |
| `reserved_cny` | REAL | **唯一预留合计**（余额 = 上限 − 本列） |
| `settled_cny` | REAL | 实际消费（**审计用**，不参与余额） |
| `executed_seconds` | REAL | 累计执行时长 |
| `status` | TEXT | `active` / `exhausted` / `revoked` |
| `created_at` / `updated_at` | TEXT | — |

约束：`UNIQUE(run_id)`（一个 run 一份有效授权；追加走 `authorization_version` 递增）。

### 2.2 `llm_spend_ledger`（费用预留，幂等键）

| 列 | 类型 | 说明 |
| --- | --- | --- |
| `call_id` | TEXT | **幂等键**：`<scope>:<purpose>:<uuid>`；跨重启唯一 |
| `authorization_id` | TEXT | 归属授权 |
| `scope_kind` / `scope_id` | TEXT | `run` / `global` |
| `reserved_cny` | REAL | 该调用的预留额（保守上界） |
| `settled_cny` | REAL NULL | 实际消费（已知时写入，**审计**） |
| `state` | TEXT | `reserved` / `sent` / `settled` / `orphaned` |
| `created_at` / `updated_at` | TEXT | — |

约束：`PRIMARY KEY(call_id)`；`INDEX(authorization_id)`。
**余额权威**：`remaining = max_spend_cny − reserved_cny`（**不含 settled**，避免二次扣费）。

### 2.3 全局账本行

`llm_spend_ledger` 增加一行 `scope_kind='global', scope_id='account'`（或单独 `llm_spend_accounts(id='account', limit_cny, reserved_cny)`），
**同一事务内**与 run 授权一起核验。

### 2.4 `web_lookup_runs` 扩展（租约 fencing）

`ALTER TABLE web_lookup_runs ADD COLUMN lease_epoch INTEGER NOT NULL DEFAULT 0;`
（`operation_id`/`started_at` 复用现有 `research_context` 字段，或同样上移为列；编码时定）

### 2.5 新增状态

`status` 现在包含 `paused`（持久）。`waiting` **不落库**。

## 3. Repository / API 方法签名（1A 目标形态）

```python
# --- 授权 ---
def create_authorization(*, owner_thread_id: str, granted_at: str, deadline_at: str,
                         limits: AuthorizationLimits) -> ResearchAuthorization
def bind_run(*, authorization_id: str, run_id: str) -> ResearchAuthorization
def append_authorization(*, authorization_id: str, limits: AuthorizationLimits) -> ResearchAuthorization  # version+1，deadline 不变
def revoke_authorization(*, authorization_id: str, reason: str) -> ResearchAuthorization
def get_authorization(*, authorization_id: str | None, run_id: str | None) -> ResearchAuthorization | None

# --- 费用（原子：预留 + run 上限 + 全局上限）---
def reserve_spend(*, call_id: str, authorization_id: str, scope_id: str,
                  estimated_cny: float) -> SpendReservation      # 不足则抛 SpendLimitExceeded
def mark_sent(*, call_id: str) -> None                            # 预留→已发出（崩溃恢复用）
def settle_spend(*, call_id: str, actual_cny: float) -> None      # 只写 settled（审计），不动余额

# --- 租约（fencing）---
def acquire_lease(*, run_id: str, holder: str, ttl_seconds: int) -> Lease   # epoch+1
def heartbeat_lease(*, run_id: str, holder: str, epoch: int, ttl_seconds: int) -> Lease
def release_lease(*, run_id: str, holder: str, epoch: int) -> None
def assert_lease(*, run_id: str, holder: str, epoch: int) -> None          # 失败抛 LeaseLost

# --- 状态 ---
def pause_run(*, run_id: str, reason: str) -> WebLookupRun        # running → paused
def resume_run(*, run_id: str, authorization_id: str) -> WebLookupRun
def cancel_run(*, run_id: str, reason: str) -> WebLookupRun       # 幂等；写 cancel 事实
```

## 4. 状态机（合法转换）

| 当前 | 事件 | 目标 | 备注 |
| --- | --- | --- | --- |
| — | 创建（交互） | `pending` | 未授权 |
| — | 创建（已授权长任务） | `pending`（带 authorization） | **可被发现**（§1.1） |
| `pending` | 获取租约并执行 | `running` | 需授权（长任务）或 turn 拥有（交互） |
| `running` | 正常结束 | `completed` / `partial` | 现有语义 |
| `running` | 错误 | `failed` | 现有语义 |
| `running` | 授权耗尽/需再次授权 | **`paused`** | **不继续付费** |
| `paused` | 再次授权（version+1） | `pending` → `running` | 需重新授权，非自动 |
| `running`/`paused`/`pending` | 用户显式停止 | `cancelled` | **终态** |
| `cancelled` | 任何自动事件 | `cancelled`（不变） | **不得自动复活**（N13） |
| `cancelled` | 用户显式新建授权并新建 run | 新 run（新 id） | 不复用旧 run |
| `partial` | 在授权内续跑 | `running` | 保留既有部分结果 |
| `completed`（`provider_status ∈ empty/partial/insufficient`） | 授权内续跑 | `running` | 现有 resumable 语义保留 |

**兼容性改动（必须）**：`begin_operation` 当前允许 `cancelled` 且会清空 `cancel_requested_at`。
异步模式下的获取入口须拒绝 `cancelled`，且**任何**恢复路径都不得清除取消事实。

## 5. 事务伪代码

### 5.1 预留（请求前，原子）

```
BEGIN IMMEDIATE
  auth  = SELECT * FROM research_authorizations WHERE id=? (或 run 绑定) FOR UPDATE-ish
  if auth is None or auth.status != 'active' or now > auth.deadline_at:  ROLLBACK; raise NotAuthorized
  if EXISTS(SELECT 1 FROM llm_spend_ledger WHERE call_id=?):            COMMIT; return existing   # 幂等
  run_remaining = auth.max_spend_cny - auth.reserved_cny
  acct = SELECT * FROM llm_spend_accounts WHERE id='account'
  acct_remaining = acct.limit_cny - acct.reserved_cny
  if estimated_cny > run_remaining or estimated_cny > acct_remaining:
      ROLLBACK; raise SpendLimitExceeded(run_remaining, acct_remaining)
  INSERT INTO llm_spend_ledger(call_id, authorization_id, scope_kind, scope_id,
                               reserved_cny, state) VALUES (?, ?, 'run', ?, ?, 'reserved')
  UPDATE research_authorizations SET reserved_cny = reserved_cny + ?, updated_at=? WHERE id=?
  UPDATE llm_spend_accounts    SET reserved_cny = reserved_cny + ? WHERE id='account'
COMMIT
```

### 5.2 租约获取/续期（fencing）

```
acquire:  BEGIN IMMEDIATE
            r = SELECT ... WHERE id=?
            if r.status == 'cancelled': ROLLBACK; raise NotResumable        # N13
            if lease_active(r) and not lease_expired(r): ROLLBACK; raise LeaseHeld
            epoch = r.lease_epoch + 1
            UPDATE web_lookup_runs SET status='running', lease_epoch=?, research_context=?(lease 字段)
                   WHERE id=? AND version=?                                      # 乐观 CAS
          COMMIT

heartbeat: BEGIN IMMEDIATE
             UPDATE ... SET research_context = json_set(research_context, '$.lease.heartbeat_at', ...)
                    WHERE id=? AND lease_epoch=?                                 # 只碰 lease 字段
             if rowcount != 1: ROLLBACK; raise LeaseLost
           COMMIT
```

### 5.3 取消（幂等、优先于恢复）

```
BEGIN IMMEDIATE
  UPDATE web_lookup_runs
     SET cancel_requested_at = COALESCE(cancel_requested_at, ?),
         status = CASE WHEN status IN ('pending','running','paused','partial') THEN 'cancelled' ELSE status END,
         lease_epoch = lease_epoch + 1            -- 使旧执行者立刻失约（fencing）
   WHERE id=? AND version=?
COMMIT
```

### 5.4 崩溃恢复（两种情形，评审指定）

| 情形 | 库中可见事实 | 恢复动作 |
| --- | --- | --- |
| **A. 预留成功、请求未发送**（崩溃在 `reserved` 与 `sent` 之间） | `ledger.state='reserved'`，无对应结果 | **不重发**该 `call_id`；将其标记 `orphaned` 并**如实记录**（保守策略下预留不退，余额不被释放）；该调用视为未发生 |
| **B. 请求已发送、结果未入库**（崩溃在 `sent` 与 commit 之间） | `ledger.state='sent'`，无对应提交结果 | **先核对**是否已有幂等结果（`query_attempts`/`selected_sources.url`/`computations.input_revision`）；无则**有界重试或如实标记不确定**；**不得**写成“已完成事实”（N12） |

两种情况都遵循：**已提交结果不重复执行**；**未知结果不冒充完成**。

## 6. 影响文件（1A）

| 文件 | 1A 变更 |
| --- | --- |
| `src/infrastructure/sqlite/database.py` | 新增一次迁移（授权表/账本表/全局行/`lease_epoch`），编号按当时 main |
| `src/repositories/research_authorization_repository.py`（新） | 授权 CRUD + 绑定/追加/撤销 |
| `src/repositories/llm_spend_ledger_repository.py`（新） | 预留/标记已发/结算（幂等） |
| `src/repositories/web_lookup_repository.py` | 租约 acquire/heartbeat/release/assert；`begin_operation` 拒绝 `cancelled` 且不清取消事实；`pause_run`/`resume_run`/`cancel_run` |
| `src/llm_spend_guard.py` | 进程内存 → 委托持久仓库（保留 fail-closed） |
| `src/application/attachment_vision.py` | 视觉调用先建授权并预留（可早于 run） |
| `src/domain/runtime_entities.py` | `paused` 状态常量；`ResearchAuthorization`/`Lease` 实体 |
| 测试 | `tests/test_async_deep_1a_*.py` |

## 7. 负控（Async-1A 确定性测试）

| # | 负控 | 断言 |
| --- | --- | --- |
| N13 | 取消后调用恢复接口 | `begin_operation`/`resume_run` **拒绝**；`cancel_requested_at` 不被清除；无新付费请求 |
| N11 | 超陈旧阈值但原 worker 存活 | 心跳续期生效；第二执行者 `LeaseHeld`；旧 epoch 写入 `LeaseLost` |
| N12 | 外部调用成功、提交前崩溃（情形 B） | 幂等核对后不重复提交；无结果则如实标记，不写“已完成” |
| N14 | 跨会话访问进度/授权 | 非 `owner_thread_id` 一律拒绝（进度、费用、材料均不可读） |
| 1A-1 | 预留成功但请求未发送（情形 A） | `call_id` 不被重发；标记 `orphaned`；余额不因重试而增加 |
| 1A-2 | 同 `call_id` 重复预留 | 只保留一份；不重复扣减 |
| 1A-3 | run 余额或全局余额任一不足 | 请求前拒绝；两者都不被部分扣减（事务回滚） |
| 1A-4 | 追加授权 | `authorization_version+1`；**`deadline_at` 不变**；余额不重置 |
| 1A-5 | 重启后余额 | 从库读取；**不刷新 15 分钟、不重发 ¥10** |
| 1A-6 | 心跳与并发 steering | 续期只碰 lease 字段；steering 写入不被覆盖 |
| 1A-7 | 视觉先于 run | 授权先创建并预留；`bind_run` 后计入该 run，非漏计 |

## 8. 本地验收命令（1A 编码后）

```powershell
# 只读/确定性，无模型调用、无网络
python -m pytest tests/test_async_deep_1a_authorization.py tests/test_async_deep_1a_ledger.py `
                 tests/test_async_deep_1a_lease.py tests/test_async_deep_1a_state_machine.py -q
python -m ruff check src tests
python -m mypy --explicit-package-bases src/ > mypy.log 2>&1; python tools/check_mypy_baseline.py --log mypy.log --baseline config/mypy_baseline.json --outcome failure
git diff --check
```

## 9. 尚存冲突 / 需放行时确认

1. **迁移编号**：以实施时 main 为准（当前 25 → 候选 26，**不预先假定**）。
2. **`begin_operation` 的 `cancelled` 兼容性（已核查，范围比预估更窄）**：
   - 代码层面确实允许 `cancelled` 获取，并会 `cancel_requested_at=None`。
   - 但**未发现**任何既有测试“在 `cancelled` run 上再次 `begin_operation`”。现有 `begin_operation` 测试覆盖的是
     **`running` + 陈旧 → 接管** 与 **旧 owner 失权后写入被拒**（`tests/test_research_run_recovery.py:140-169`，
     断言 `lost ownership`）；另有取消语义测试断言 `cancelled / user_cancelled`。
   - 因此 1A 的收窄（拒绝 `cancelled`、恢复路径不清除取消事实）**与现有测试不冲突**；实现时需
     1) 保留 `lost ownership` 这条既有错误面（fencing 不匹配仍映射到同义错误），2) 全仓再扫一次
     是否有隐藏调用方依赖“取消后可恢复”。
3. **租约 TTL 与心跳周期**：建议 ttl 90 s / 心跳 30 s，编码时按真实读取耗时分位确认。
4. **`lease_epoch` 落列 vs 落 JSON**：倾向落列（索引/并发更清晰），编码时以现有 schema 风格为准。
5. **全局账本上限来源**：由配置提供（不接受模型自行设定）；具体键名在 1A 编码时定。

## 10. 非目标（1A 不做）

- 不接调度器（**1B**）、不做前端重连与真实验收（**1C**）。
- 不重写 Reader（**Reader Performance-1** 独立冻结）。
- 不改 Evidence Gate、计算工具语义、角色切换、学习状态权威。
- 不改变原 A/B/C 的 FAILED 结论。
