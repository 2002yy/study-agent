import type { LearningState } from "../../types";

const MOVE_LABELS: Record<string, string> = {
  elicit_claim: "引出主张",
  clarify_definition: "澄清定义",
  expose_assumption: "暴露假设",
  request_prediction: "请求预测",
  test_example: "举例验证",
  offer_counterexample: "给反例",
  surface_contradiction: "揭示矛盾",
  give_hint: "给提示",
  provide_library_fact: "提供事实",
  reconstruct: "重构理解",
  transfer: "迁移",
  direct_explain: "直接讲解",
  set_scope: "界定范围",
  invite_explanation: "邀请解释",
  identify_main_gap: "定位缺口",
  minimal_repair: "最小修补",
  request_reexplanation: "要求重讲",
  transfer_test: "迁移检验",
  define_acceptance: "定义验收",
  inspect_artifact: "检查产出",
  form_hypothesis: "形成假设",
  choose_solution: "选择方案",
  apply_patch: "应用补丁",
  run_validation: "运行验证",
  close_stage: "收束阶段",
};

const PROTOCOL_LABELS: Record<string, string> = {
  socratic: "苏格拉底",
  socratic_rediscovery: "苏格拉底",
  feynman: "费曼",
  project: "项目",
  direct: "普通",
  auto: "自动",
};

export function moveLabel(move: string): string {
  return MOVE_LABELS[move] ?? move;
}

export function protocolLabel(protocol: string): string {
  return PROTOCOL_LABELS[protocol] ?? (protocol || "自动");
}

export function phaseTrail(phases: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const p of phases) {
    if (p && !seen.has(p)) {
      seen.add(p);
      out.push(p);
    }
  }
  return out;
}

export function deriveMastery(state: LearningState, visitedPhases: string[]): number {
  const confirmed = state.confirmed_points?.length ?? 0;
  const gap = state.unresolved_gap ? 1 : 0;
  const pointRatio = confirmed / Math.max(1, confirmed + gap);
  const totalPhases = Math.max(1, visitedPhases.length);
  const phaseRatio = visitedPhases.includes(state.phase)
    ? (visitedPhases.indexOf(state.phase) + 1) / totalPhases
    : 0;
  return Math.max(0, Math.min(1, 0.5 * pointRatio + 0.5 * phaseRatio));
}
