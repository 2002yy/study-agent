# Learning State-1 验收矩阵（L2–L6 证据收尾）

**状态：证据收尾（2026-10-08）**
**基线：** `main` = `f35b13b78498f1e7ce2ad678bf6687bd85fb220a`
**合同：** [`LEARNING_STATE_1_CONTRACT.md`](LEARNING_STATE_1_CONTRACT.md)（A+；L1–L6 / T01–T18 / M1–M6）
**L1 实现权威：** `0de80751`（PR #200）；本文只整理证据，不重新验证 L1 实现，也不新增实现/测试。

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
| T16 | Lookup/Standard/Deep 不创建 mastery | `test_learning_mastery_isolation.py::test_only_the_closure_chain_writes_durable_understanding`（写入者清单守卫）；`test_learning_closure_commit_boundary.py::test_preview_and_ordinary_closure_generation_do_not_write_durable_truth`、`::test_auto_memory_mode_cannot_auto_commit_pending_durable_truth`；`test_learning_closure_candidate_boundary.py` | 结构性 + closure 边界行为 | 结构性（写入者清单）+ 边界行为 | **M6**：向研究模块加入 `commit_semantic_closure` 调用 → 守卫 FAIL（已实测） | PASS |
| T17 | 普通 UI 操作不创建 mastery | `test_learning_mastery_isolation.py::test_only_explicit_closure_routes_trigger_a_closure_run`（路由守卫）+ `::test_closure_truth_service_is_constructed_only_by_the_runtime_wiring`；无直接 UI 测试（UI 属 B 线） | 结构性 | 结构性 | **M6**：非 closure 路由触发 closure run → 守卫 FAIL（已实测）；无直接 UI 负控（限制 L-b） | PASS（结构性，见 L-b） |
| T18 | 显式 closure commit 正式写入链正常 | `test_learning_closure_commit_boundary.py::test_explicit_commit_writes_durable_truth_once_before_memory_commit`；`test_learning_verification_e2e.py::test_reasoned_explanation_commits_and_restores_learning_truth` | 是 | 直接 | `::test_truth_failure_stops_before_memory_commit_and_has_distinct_reason` | PASS |

## 汇总

```text
T01-T15, T18   直接证据（多数经真实生产路径或真实 HTTP）        PASS
T16            结构性（写入者清单守卫）+ closure 边界行为      PASS
T17            结构性（路由/构造守卫）；无直接 UI 负控         PASS（结构性）
M6             写入隔离变异负控（已实测检出）                 PASS
```

## 已知限制

- **L-a（T09/T10/T11）**：legacy fallback 与 durable-first 由行为断言覆盖，未设独立变异负控。理由：这两条是既有权威路径，本轮未改其语义；若要更强保证需新增 mutation，但合同 §8 要求「不为制造增量而改实现」，故不新增。
- **L-b（T17）**：UI 属 B 线且尚未封板；后端不存在 UI → durable 写入路径（唯一写入权威 `LearningClosureTruthService` 只经显式 closure 路由）。T17 由 `test_learning_mastery_isolation.py` 的**路由/构造守卫**覆盖（结构性），仍无直接 UI 负控。合同 §7 允许以「只读快照 + 模拟 UI 动作负控」验收。
- 本轮**未**改动 Socratic、durable 写入语义、§164 仪器；T14 口径不变。

## M6 负控资格（本轮补齐）

`tests/test_learning_mastery_isolation.py` 是 T16/T17/M6 的定点隔离负控：

- 扫描 `src/**/*.py`，`create_understanding_evidence` / `commit_review_attempt` / `commit_semantic_closure` 的调用者必须 ⊆ closure 链（`learning_closure_truth` / `learning_semantic_closure`）；`create_understanding_evidence` 在生产中**无调用者**。
- `LearningClosureTruthService` 只允许在 `runtime_repository.py` 构造。
- closure run 只允许由 `learning_closure_routes.py` / `session_routes.py` 触发。
- **变异实测**：向 `src/web/research/` 加入一个 `commit_semantic_closure` 调用 → `test_only_the_closure_chain_writes_durable_understanding` FAIL（探针已删除）。

因此 M6（研究/UI 绕过 closure 写入）具备可检出能力，不再是未资格化负控。

## 结论

- T01–T15、T18：**直接证据 PASS**。
- T16：**结构性（写入者清单守卫）+ closure 边界行为 PASS**。
- T17：**结构性 PASS**（路由/构造守卫），限制 L-b 如实登记。
- M6：**已资格化**（隔离变异负控实测检出）。
- 合同 §11 完成定义 1–10 项均有对应证据；**建议 `Learning State-1 = CLOSED`**（L1 实现权威 `0de80751`；L2–L6 验收由本矩阵关闭）。
- 不新增代码/测试；不启动只读 `learning_view`；不启动 RP-1。
