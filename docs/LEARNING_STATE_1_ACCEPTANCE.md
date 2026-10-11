# Learning State-1 验收矩阵（L2–L6 证据收尾）

**状态：2026-10-11 P1 修复候选；本地验证通过后仍须新 head CI 与审阅，L2–L6 尚未远端 CLOSED。**
**基线：** `main` = `f35b13b78498f1e7ce2ad678bf6687bd85fb220a`
**合同：** [`LEARNING_STATE_1_CONTRACT.md`](LEARNING_STATE_1_CONTRACT.md)（A+；L1–L6 / T01–T18 / M1–M6）
**L1 实现权威：** `0de80751`（PR #200）；本文只整理证据，不重新验证 L1 实现；**不修改生产实现**，保留结构守卫并新增 `test_learning_mastery_runtime_isolation.py` 的真实持久化隔离测试。

## 方法

对合同 §9 的 T01–T18，逐条给出：现有测试名 / 是否经过真实生产路径 / 直接或间接证据 / 负控 / 结论。
判定标准：
- **直接** = 断言直接命中合同要求，且经过相应真实组件（生产服务或真实 HTTP）。
- **间接** = 只有结构性保证或相邻覆盖，无直接断言。
- **负控** = 有变异/反例测试能在破坏该保证时失败。

## 矩阵

| 门 | 合同要求 | 现有测试 | 生产路径 | 证据 | 负控 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| T01 | 用户仅说“懂了”不 confirmed | `test_learning_verification_e2e.py::test_unverified_claims_never_confirm_mastery[懂了...]` | 是（TestClient `/chat` → `ExternalDataPolicyChatService`） | 直接 | `test_learning_authority_projection.py`（自述非 mastery；M3） | PASS |
| T02 | 启发式 concluded：legacy 可变，durable 不变 | `test_learning_verification_e2e.py::test_reasoned_explanation_commits_and_restores_learning_truth`；`test_learning_closure_commit_boundary.py::test_preview_and_ordinary_closure_generation_do_not_write_durable_truth` | 是 | 直接 | M1/M1b（expected_concepts 不回退） | PASS |
| T03 | legacy confirmed 被读取 → 标未验证 | `test_learning_resume.py::test_legacy_fallback_keeps_old_confirmed_points_outside_formal_claims`；`test_learning_authority_projection.py::test_legacy_confirmed_points_are_never_verified` | 读边界 + 单元 | 直接 | M2（把 legacy 当 verified → 投影测试 FAIL） | PASS |
| T04 | 无显式 expected_concepts → 不回退 legacy | `test_learning_authority_projection.py::test_expected_concepts_do_not_fall_back_to_confirmed_points`；`::test_policy_production_path_expected_concepts_do_not_fall_back` | 基类 + 生产 policy 路径 | 直接 | M1（基类）+ M1b（生产路径），均单独验证 | PASS |
| T05 | 显式课程目标仍可成为评估目标 | `::test_explicit_expected_concepts_are_passed_through`；`::test_policy_production_path_explicit_targets_pass_through` | 基类 + 生产 policy 路径 | 直接 | 与 T04 对偶（回退被切断时显式目标仍通过） | PASS |
| T06 | 正式 Review 绑定与评估输入不回归 | `test_review_turns.py::test_real_review_roundtrip_and_same_attempt_replay`、`::test_start_and_answer_http_flow`、`::test_foreign_thread_and_retry_rebinding_are_rejected` | 是（含 HTTP） | 直接 | `::test_fresh_pass_between_answer_and_commit_fails_cas`、`::test_atomic_guard_rejects_changed_frozen_authority` | PASS |
| T07 | 有效 durable pass → 对应 Claim confirmed | `test_learning_closure_truth.py::test_explicit_closure_reconverges_source_then_commits_claim_and_understanding_once`；`test_learning_verification_e2e.py::test_reasoned_explanation_commits_and_restores_learning_truth`；`test_learning_resume.py`（authority=`verified`） | 是（e2e） | 直接 | `test_learning_closure_commit_boundary.py::test_source_current_guard_runs_before_durable_truth_commit` | PASS |
| T08 | durable partial/fail 不 confirmed | `test_learning_closure_truth.py::test_without_real_validation_prompt_claim_stays_unverified`；`test_learning_verification_e2e.py::test_unverified_claims_never_confirm_mastery`；`test_learning_resume.py`（authority=`system_inferred`） | 是（e2e） | 直接 | `test_learning_closure_truth.py::test_unaccepted_or_model_invented_claim_fails_closed_before_source_convergence` | PASS |
| T09 | 无 durable Goal → legacy fallback | `test_learning_resume.py::test_legacy_fallback_keeps_old_confirmed_points_outside_formal_claims`、`::test_empty_thread_without_durable_or_legacy_learning_state_is_empty` | 是 | 直接 | 无显式变异；行为断言覆盖 | PASS |
| T10 | 有 durable Goal → durable-first | `test_learning_resume.py::test_durable_resume_uses_latest_revision_and_bounded_semantic_state`（`source=="durable"`）；`::test_durable_context_with_no_active_goal_never_resurrects_legacy_state` | 是 | 直接 | 无显式变异；行为断言覆盖（见限制 L-a） | PASS |
| T11 | durable 旧 revision 验证沿 lineage 投影 | `test_learning_revalidation.py::test_revalidate_commits_new_revision_on_same_lineage`；`test_learning_resume.py::test_durable_resume_uses_latest_revision_and_bounded_semantic_state`（`source_id` = 实际 UnderstandingEvidence） | 是 | 直接 | 无显式变异；`authority.source_id` 断言指向真实记录 | PASS |
| T12 | 重启/重复 commit 不丢、不重复 | `test_learning_truth_repository.py::test_repository_round_trip_survives_restart`；`test_learning_closure_truth.py::test_missing_primary_creates_hypothesis_only_and_retry_is_idempotent`；`test_learning_verification_e2e.py::test_interrupted_continuation_commits_once_and_restores` | 是 | 直接 | 幂等/崩溃重试用例 | PASS |
| T13 | thread 身份隔离，不串学习事实 | `test_review_turns.py::test_foreign_thread_and_retry_rebinding_are_rejected`；`test_learning_closure_goal_focus.py::test_same_objective_reuses_goal_but_new_objective_gets_new_focus` | 是（HTTP） | 直接 | 外部 thread 绑定拒绝 | PASS |
| T14 | §164 三种既有状态：观察口径不变 | `test_learner_state_parity.py`（全部分类/不变量用例）；`test_learner_state_shadow_seam.py`；`test_learner_state_shadow_acceptance.py` | 是（seam 经真实 `start_turn`） | 直接 | `test_learner_state_shadow_acceptance.py::test_normal_shadow_is_behaviourally_identical` 等 7 组 | PASS |
| T15 | durable-read OFF / canary：无隐式新写入 | `test_learner_state_durable_adapter.py::test_durable_read_is_off_by_default`、`::test_canary_enables_only_listed_threads`；`test_learner_state_shadow_acceptance.py::test_flag_off_never_invokes_the_reader` | 是 | 直接 | OFF/canary/异常分支用例 | PASS |
| T16 | Lookup/Standard/Deep 不创建 mastery | `test_learning_mastery_runtime_isolation.py`：lookup / standard / deep 参数化生产服务边界 | ChatService / StandardContinuationService / DeepPublicationService，真实 SQLite | 已填充 durable truth 全表 before/after 快照严格相等 | M6：各真实边界返回时注入 Understanding 写入，隔离断言必须失败且写入确实落库 | 本地 PASS；待新 head CI |
| T17 | 普通 UI 操作不创建 mastery | 同文件 ui 参数：真实 HTTP 列表、详情、learning-resume、标题更新 | TestClient / session service / 实际 LearningResumeService，同一真实 SQLite | 已填充 truth 全表 before/after 快照严格相等 | M6：真实 get_session 边界注入落库，隔离断言检出 | 本地 PASS；待新 head CI |
| T18 | 显式 closure commit 正式写入链正常 | `test_learning_closure_commit_boundary.py::test_explicit_commit_writes_durable_truth_once_before_memory_commit`；`test_learning_verification_e2e.py::test_reasoned_explanation_commits_and_restores_learning_truth` | 是 | 直接 | `::test_truth_failure_stops_before_memory_commit_and_has_distinct_reason` | PASS |

## 汇总

```text
T01-T15, T18   直接证据（多数经真实生产路径或真实 HTTP）        PASS
T16            三个真实研究服务 + populated truth 快照         本地 PASS
T17            实际 HTTP + populated truth 快照及写入负控     本地 PASS
M6             写入隔离变异负控（已实测检出）                 PASS
```

## 已知限制

- **L-a（T09/T10/T11）**：legacy fallback 与 durable-first 由行为断言覆盖，未设独立变异负控。理由：这两条是既有权威路径，本轮未改其语义；若要更强保证需新增 mutation，但合同 §8 要求「不为制造增量而改实现」，故不新增。
- **L-b（T16/T17）**：外部模型/provider 使用确定性 fixture；Standard 使用已有 handoff fixture，Deep 从已有 terminal fixture 进入真实 publication process。证明实际服务与 HTTP 边界不改 durable truth；不声称自然长研究、真实模型或浏览器端到端验收。
- 本轮**未**改动 Socratic、durable 写入语义、§164 仪器；T14 口径不变。

## M6 负控资格（本轮补齐）

`tests/test_learning_mastery_isolation.py` 是 T16/T17/M6 的定点隔离负控：

- 扫描 `src/**/*.py`，`create_understanding_evidence` / `commit_review_attempt` / `commit_semantic_closure` 的调用者必须 ⊆ closure 链（`learning_closure_truth` / `learning_semantic_closure`）；`create_understanding_evidence` 在生产中**无调用者**。
- `LearningClosureTruthService` 只允许在 `runtime_repository.py` 构造。
- closure 入口（`create_and_execute` / `commit` / `retry` / `cancel`）只允许由 `learning_closure_routes.py` / `session_routes.py` 触发或提交；只扫描引用了 closure service 的路由模块。
- **变异实测 1（研究写入）**：向 `src/web/research/` 加入一个 `commit_semantic_closure` 调用 → `test_only_the_closure_chain_writes_durable_understanding` FAIL（探针已删除）。
- **变异实测 2（路由提交）**：新增一个非授权路由引用 closure service 并调用 `service.commit(run_id)` → `test_only_explicit_closure_routes_trigger_a_closure_run` FAIL（探针已删除）。

因此 M6（研究/UI 绕过 closure 写入）具备可检出能力，不再是未资格化负控。

## 结论

- T01–T15、T18：**直接证据 PASS**。
- T16：真实 Lookup / Standard / Deep 服务边界持久化快照，本地 PASS。
- T17：实际普通 UI HTTP 边界持久化快照与落库负控，本地 PASS；限制 L-b 如实登记。
- M6：**已资格化**（隔离变异负控实测检出）。
- L1 已 CLOSED，权威仍为 `0de80751`；L2–L6 等待本修复候选的精确提交 CI 和最终审阅，不借用旧 head 的绿灯。
- 不改生产实现；不启动只读 `learning_view`；不启动 RP-1。

## 2026-10-11 实际边界补证

新增 4 个正常隔离测试、4 个真实边界写入负控、1 个显式授权 closure 正控，共 9 项；连同原结构守卫 13 passed。正常测试使用已填充的同一 SQLite，比较全部 learning_ / claim_ / understanding_ 表以及 source_evidence / next_steps / learner_misconceptions。负控通过真实 truth API 写入新 Understanding，必须被相同隔离断言检出；显式授权 commit 正控验证允许写入和重提幂等（仅其授权 context 更新时间不作为幂等值）。阶段影响集：全部 test_learning_* / test_learner_model* 加 Lookup / Standard / Deep 边界、Lookup terminal、Standard handoff/continuation、Deep publication，共 299 passed / 125.59s；另 Chat routes pedagogy 与 review projection 12 passed / 2.71s；Ruff 全仓 PASS，mypy 122/128（无新增错误），git diff --check PASS。仅测试与记录增量，不改生产或共享 fixture，按 staged policy 不重复 L3；远端新 head CI 尚待。
