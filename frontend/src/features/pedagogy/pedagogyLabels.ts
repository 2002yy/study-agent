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
  feynman_diagnosis: "费曼",
  project: "项目",
  project_execution: "项目",
  direct: "普通",
  direct_answer: "普通",
  auto: "自动",
};

const PHASE_LABELS: Record<string, string> = {
  orientation: "建立目标",
  direct_explanation: "直接讲解",
  library_fact: "提供事实",
  scaffold: "提供线索",
  transfer: "迁移应用",
  test_assumption: "例子验证",
  elicit: "引出解释",
  diagnose: "诊断缺口",
  repair: "修正理解",
  re_explain: "重新解释",
  complete: "完成验证",
  define: "界定范围",
  inspect: "检视现状",
  decide: "决定方案",
  implement: "实施改动",
  verify: "验证结果",
  stabilize: "稳定成果",
  deliver: "交付收束",
  answer: "解答",
};

export function moveLabel(move: string): string {
  return MOVE_LABELS[move] ?? move;
}

export function protocolLabel(protocol: string): string {
  return PROTOCOL_LABELS[protocol] ?? (protocol || "自动");
}

export function phaseLabel(phase: string): string {
  return PHASE_LABELS[phase] ?? phase;
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
