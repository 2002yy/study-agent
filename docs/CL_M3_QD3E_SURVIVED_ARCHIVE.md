# QD-3e 变异验证归档：5 项 SURVIVED 的分类与风险裁定

日期：2026-10-24
基线：`04f05a14`（QD-3e 实现）+ `7145729e`（竞争测试修复）
运行器：`.qd3e_mutate.py`（每变异独立 worktree / 独立 basetemp / 独立 TMP）
测试范围：`tests/test_research_scenarios.py` + `tests/test_research_production.py`
基线收集数：29（scenarios 17 + production 12）

## 一、结果总表

| # | 变异名 | 判定 | 分类 | 是否阻断 |
|---|---|---|---|---|
| 1 | `no-progress-check-removed` | **DETECTED**（failed=2） | 护栏有效 | 否 |
| 2 | `cancel-check-removed` | SURVIVED | **覆盖不足**（检查存在但未被走到） | 否 |
| 3 | `worker-starts-without-an-executor` | SURVIVED | **覆盖不足**（`factory()` 返回 None 时可达，未测） | 否 |
| 4 | `disabled-worker-starts-anyway` | SURVIVED | **覆盖不足**（关闭分支未被测） | 否 |
| 5 | `broken-factory-starts-anyway` | SURVIVED | **覆盖不足**（另一条失败路径未被测） | 否 |
| 6 | `factory-imports-eagerly` | SURVIVED | **变异无效**（变异测错了对象） | 否 |

**6 项中 1 项 DETECTED、5 项 SURVIVED。**

## 二、逐项归档

### 1. `no-progress-check-removed` — DETECTED ✅

- **变异目标**：删掉协调器循环里 `stop_if_no_progress(research_id)` 的调用。
- **检出**：2 个失败 —— `test_two_rounds_without_a_gain_stop_the_research`、
  `test_a_stopped_research_is_not_offered_to_another_worker`。
- **裁定**：护栏有效。R-4 自停在运行时**确实生效**（3e 修的两个真缺口之一）。
- **阻断**：否。

### 2. `cancel-check-removed` — SURVIVED ⚠️ 覆盖不足

- **变异目标**：把协调器循环里 `if not current.may_start_new_call:` 的分支改为 `if False:`。
- **可达性分析**：
  - 该检查位于**每轮 executor 调用之前**，读的是重新读取的行（`self.repository.resume`），
    位置正确（QD-3e 修复后）。
  - **但现有测试走不到这个判断**：取消发生在 executor **内部**（`observe` 钩子）。
  - `cancel()` 会 `state_version = state_version + 1`，于是**当轮 checkpoint 的 CAS 被拒**
    （`StaleResearchWriter`），协调器在 `result.leases_lost += 1` 处直接 return。
  - 因此**第 2 轮从未开始**，取消检查那行代码从未执行到判断。
- **根因**：**测试覆盖不足**，不是实现缺陷。检查的位置正确（executor 之前），
  但缺少「取消发生在两轮之间」的窗口测试。
- **风险裁定**：
  - 该窗口在生产**可达**——取消可在两轮之间落地（此时 `state_version` 未变，
    当轮 checkpoint 会成功，第 2 轮的检查就会生效）。
  - 但**当前实现的检查位置是对的**，且 3e 已用它堵住了「取消后仍发起模型调用」的路径
    （`test_a_cancellation_during_a_round_stops_the_next_call` 断言 executor 只进入一次）。
  - **不构成生产安全或费用边界可被绕过的缺陷**——只是该检查缺一个专门的负控用例。
- **阻断**：否。**遗留项**：补一个「取消发生在两轮之间」的用例（单独排期）。

### 3. `worker-starts-without-an-executor` — SURVIVED ⚠️ 覆盖不足（原判"变异无效"，已更正）

- **变异目标**：把 `start_research_coordinator` 里
  `if executor is None: ... return None` 改为「造一个空 executor 继续」。
- **可达性分析**：该锚点命中的是函数里的**第二个** `if executor is None` 检查。
  第一个检查（`if executor is None:` → `load_executor_factory()`）在
  `executor` 为 None 时**必然 return None**（factory 为 None），
  或给 `executor` 赋值。于是第二个检查**通常**不可达——
  **但 `factory()` 自己返回 None 时它是可达的**：第一个检查会走进
  `executor = factory()`，得到 None，然后落到第二个检查。
- **根因**：**测试覆盖不足**（**这一条是更正**）。
  此前把这一项归为"变异无效 / 目标分支不可达"，理由是第一个检查会先行 return。
  但同一个分析里已经承认"除非 `factory()` 返回 None"——那条路径存在，
  只是**没有测试**走到它。所以准确的说法是：
  **变异的目标分支在特定输入下可达，而现有测试没有构造那个输入**，
  于是 SURVIVED 反映的是覆盖缺口，不是不存在缺陷。
  这是"分类"本身需要被修正的一例：**"不可达"与"可达但没测"是两件事**，
  前者排除风险，后者只是留下风险未被发现。
- **风险裁定**：生产里 `coordinator.start()` 只有**一个**调用点
  （`research_production.py:183`），它在「开关开启 + 拿到 executor」两道门之后。
  即便走到第二个检查，其行为也是 `return None`（不启动），
  **不会产生费用**。所以**当前不构成可绕过的安全/费用缺陷**，
  但**结论依赖"第二个检查仍然 return None"这一实现事实**，
  而该事实**没有测试保护**——这正是覆盖缺口的实际含义。
- **阻断**：否。**遗留项**：补一条「`factory()` 返回 None 时 worker 不启动」的用例
  （与第 5 项的"factory 抛异常"用例相邻，但**不是同一条路径**：
  一个是异常，一个是 None 返回）。

### 4. `disabled-worker-starts-anyway` — SURVIVED ⚠️ 覆盖不足

- **变异目标**：把 `if not research_coordinator_enabled(): ... return None` 改为 `if False:`。
- **可达性分析**：所有调用 `start_research_coordinator` 的测试都设了
  `RESEARCH_COORDINATOR_ENABLED_ENV=1`，**「关闭」分支从未被测过**。
- **根因**：**测试覆盖不足**。实现本身正确（开关默认为关）。
- **风险裁定**：
  - 这是**费用边界的开关**——「worker 不启动」是防止无人值守地烧钱的最后一道门。
  - 但实现侧**没有绕过路径**：`research_coordinator_enabled()` 默认 False，
    `app.py` 的 lifespan 走 `get_research_coordinator()` → `start_research_coordinator()`，
    关闭时返回 None，**协调器不启动**。
  - **不构成可绕过的缺陷**（开关有效），但**缺一条「关闭时不启动」的断言**，
    将来若有人改了这道门，没有测试会拦住。
- **阻断**：否。**遗留项**：补一条「关闭时 `start_research_coordinator` 返回 None」的用例（单独排期）。

### 5. `broken-factory-starts-anyway` — SURVIVED ⚠️ 覆盖不足

- **变异目标**：把
  ```
  try:
      executor = factory()
  except Exception:
      _logger.exception("research executor factory failed")
      return None
  ```
  改为「except 里造一个空 executor 继续」。
- **可达性分析**：现有测试用的是 `no.such.module:factory`——
  这在 **`load_executor_factory()` 的导入阶段**就失败并 `return None`，
  **根本没走到 `factory()` 的调用**。`factory()` 本身抛异常的路径**从未被测过**。
- **根因**：**测试覆盖不足**（另一条失败路径未覆盖）。
- **风险裁定**：
  - 若 `factory()` 抛异常却被忽略，协调器会以**空 executor** 启动——
    它会扫描、会发现研究、会记录，但**不会产生模型调用**（executor 为 None 时
    `outcome = None` → `result.skipped += 1`）。
  - 即：**不产生费用**，但会产生「看起来活着、实际什么都不做」的 worker。
  - 这正是 `research_production.py` 文档字符串里明确说要避免的状态。
  - **不构成费用或安全边界可被绕过的缺陷**，但值得补测。
- **阻断**：否。**遗留项**：补一条「factory() 抛异常时 worker 不启动」的用例（单独排期）。

### 6. `factory-imports-eagerly` — SURVIVED ✗ 变异无效

- **变异目标**：原意是测「executor 模块在 **import 时**被导入」，
  但变异把 `importlib.import_module(...)` 插在 **`load_executor_factory()` 函数体内**——
  那是**调用时**导入，不是 import 时导入。
- **可达性分析**：**变异测错了对象**。它既没有破坏 import 时的行为，
  也没有触及文档字符串里那句承诺（「导入一个能调用模型的模块应当是一个决定，
  而不是启动应用的副作用」）。
- **根因**：**变异无效**——锚点选错位置。
- **风险裁定**：
  - 实际行为**符合承诺**：`src/application/research_production.py` 在模块顶层
    只 import `research_coordinator` 与 `research_state_repository`，
    **没有** import 任何模型客户端；executor 由 `module:attribute` 路径在**启动时**导入。
  - 生产代码里 `ResearchRound` 的唯一构造点在仓储内部，
    **无任何生产 Executor 实现**（执行器由部署方提供），故 `observation_urls`
    的生产可得性依赖部署方实现——**这是部署契约问题，不是本模块缺陷**。
  - **不构成缺陷**。
- **阻断**：否。**遗留项**：若要真正验证该承诺，需要一个「import 生产模块后检查
  `sys.modules`」的用例（单独排期）。

## 三、总结论

- **5 项 SURVIVED 中没有一项证实为生产安全或费用边界可被绕过的缺陷。**
  - **1 项是变异本身无效**（第 6 项：锚点选在函数体内，测的是"调用时导入"而非
    "import 时导入"），SURVIVED 不反映实现质量。
  - **4 项是测试覆盖不足**（第 2、3、4、5 项），实现的检查位置与生效路径均正确。
  - **第 3 项的分类已更正**（原判"变异无效 / 目标分支不可达"）：
    `factory()` 返回 None 时那个分支**是可达的**，只是没有测试构造那个输入。
    "不可达"会排除风险，"可达但没测"只是留下风险未被发现——两者不是一回事，
    因此更正为**覆盖不足**。
- **实际阻断项：0。**
- **已修的 2 项**（本轮，非 SURVIVED 清单内）：
  - `test_research_feed.py::test_every_round_the_coordinator_runs_publishes_an_event`
    —— **3e 引入的真回归**：3e 把 `stop_if_no_progress` 接进协调器后，
    该测试的两轮（**无 `observation_urls`**）被正确判定为「零增量」→
    研究自停 → 多出一条 `research_finished` 事件。修法是给测试的轮次补上来源，
    **不是放宽增量判定**（3d 冻结的口径是「增量以新来源为准」，有 11 项变异验证）。
  - `test_research_coordinator.py::test_two_workers_never_advance_the_same_research_at_once`
    —— **既有 flaky**（3c 基线 `a71e7e7d` 上同样 4/8 失败）。断言 `leases_lost == 1`
    只在「败者的 `resumable()` 早于胜者 claim」这一条时序下成立；
    败者也可能因「活租约不被提供」而被跳过（`leases_lost == 0`）。
    两者都是合法路径。修法是断言系统真正保证的东西（合起来只推进 1 轮、
    只有 1 个 executor 被进入），**不是**删掉断言。
- **遗留排期项**（不在本批）：
  1. 「取消发生在两轮之间」的负控用例（第 2 项）
  2. 「关闭开关时不启动 worker」的用例（第 4 项）
  3. 「`factory()` 抛异常时不启动 worker」的用例（第 5 项）
  4. 「import 生产模块不导入模型客户端」的用例（第 6 项）

---

## 四、与 PR #287 的整合阻断项（**必须在合入前解决**）

#287（`fix/cl-m3-qd3d-integration-20261024`，HEAD `5f10c0a3`）给
`stop_if_no_progress` 的 UPDATE 加了条件：

```sql
WHERE research_id = ? AND state_version = ? AND round_index = ?
  AND status IN ('running', 'checkpointed')
  AND lease_owner = '' AND cancel_requested_at = ''
```

### 阻断项 A：`lease_owner = ''` 与 3e 的调用时机冲突 → R-4 自停失效

**实测结论**（在 #287 的 HEAD `5f10c0a3` 上直接跑探针）：

```
--- 场景B：持有活跃租约时调用 stop_if_no_progress（3e 协调器路径）---
结果 -> None（未停止）
status: running | lease_owner: live-worker
```

**冲突点**：3e 的协调器在**自己的租约持有期间**调用 `stop_if_no_progress`
（`src/application/research_coordinator.py:519`，位于「checkpoint 之后、下一轮之前」）。
按 #287 新增的 `AND lease_owner = ''`，该 UPDATE 在协调器自己的租约下**永远不匹配**
→ `rowcount != 1` → `return None` → **研究永不自停**。

**后果**：契约 §11.2 的判据「连续两轮有效增量为零 → 自停，不跑满时长」
在整合后**完全失效**，且失效方式是**静默的**——不报错、不抛异常，只是研究一直跑下去。
这直接影响 §10.4 R-4「禁止为耗满时间而循环」。

**性质**：这是**整合产生的语义冲突**，不是 QD-3e 的缺陷，也不是 #287 的缺陷——
两边各自正确，合在一起不自洽。

**建议解法**（需裁定，不由本批单方面决定）：
- 方案 A：协调器在调用 `stop_if_no_progress` **之前先释放租约**，调用后再重新领取。
  代价是多两次租约往返。
- 方案 B：`stop_if_no_progress` 接受调用方传入的 `owner`，
  允许「租约属于自己」时也执行停止（`AND (lease_owner = '' OR lease_owner = ?)`），
  并用 `fencing_token` 做 CAS 保护。
- 方案 C：协调器在每轮**结束后**释放租约，再由下一轮开始时判断无进展。
  语义最干净，但改变了「一轮一租约」的节奏。

### 阻断项 B：#287 自身 CI 失败，且失败原因是新测试的构造与意图矛盾

#287 精确 HEAD `5f10c0a3` 的 CI 已 **`completed` 且 `conclusion: failure`**
（run `40101288220`；`pytest` 与 `mypy_baseline` 两项失败，前端与浏览器全绿）。
本地可复现：

```
FAILED tests/test_research_progress.py::test_no_progress_stop_cannot_override_an_active_worker
E       assert None is not None
tests/test_research_progress.py:349: AssertionError
```

**根因**（实测定位）：该测试想验证「零增量研究在活跃租约下不被停止」，
但它用 `_checkpoint()` 造的两轮**每轮来源不同**
（`urls_of(index)` 返回 `https://source/{index}`，即 source/0 与 source/1）
→ 按 3d 冻结的增量口径，**这两轮是有增量的** → 释放租约后 `stop_if_no_progress`
正确地返回 None（不该停）→ 测试断言 `stopped is not None` 失败。

即：**测试的意图（验证零增量场景）与它的构造（造出有增量的两轮）矛盾**。
修法是让它造两轮**相同来源**的轮次，与 `tests/test_research_scenarios.py` 里
QD-3e 已有的 `scripted_round(observation_urls=(same,))` 写法一致。

### 处置

- #287 **不由本批合并**（其 CI 未通过，且与 3e 存在上述语义冲突）。
- QD-3e 的两个提交（`04f05a14` + `0f38269f`）**独立推送到
  `codex/cl-m3-capability-20261023`**，不依赖 #287，也不强推、不覆盖。
- 上述两个阻断项随 §34 一并归档，**留给审核裁定**：
  - A 需决定「协调器何时有权宣布自停」的语义；
  - B 需修正 #287 那条测试的构造。
- 两者都**不阻塞 QD-3e 自身的收口**（3e 的实现、测试、回归均自洽），
  但**阻塞「主线可集成」这一层结论**。
