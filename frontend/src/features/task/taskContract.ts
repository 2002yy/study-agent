export type TaskContract = {
  task_intent: string;
  source_policy: string;
  closure_eligibility: string;
  learning_state_enabled: boolean;
  confidence?: string;
  reason?: string;
};

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : undefined;
}

export function taskContractFromRoute(
  route: Record<string, unknown> | undefined
): TaskContract | undefined {
  const raw = asRecord(route?.task_contract);
  if (!raw || typeof raw.task_intent !== "string") return undefined;
  const contract: TaskContract = {
    task_intent: raw.task_intent,
    source_policy: String(raw.source_policy ?? "model_only"),
    closure_eligibility: String(raw.closure_eligibility ?? "not_applicable"),
    learning_state_enabled: raw.learning_state_enabled === true,
    confidence: typeof raw.confidence === "string" ? raw.confidence : undefined,
    reason: typeof raw.reason === "string" ? raw.reason : undefined,
  };
  const learningState = asRecord(route?.learning_state);
  const hasActiveLearning = Boolean(
    String(learningState?.objective ?? "").trim() ||
    String(learningState?.protocol ?? "").trim()
  );
  if (
    hasActiveLearning &&
    contract.task_intent === "quick_answer" &&
    contract.confidence === "low"
  ) {
    return {
      ...contract,
      task_intent: "learn",
      closure_eligibility: "learning_summary",
      learning_state_enabled: true,
      confidence: "medium",
      reason: "continue_active_learning",
    };
  }
  return contract;
}

export function taskIntentLabel(intent: string): string {
  return (
    {
      quick_answer: "快速问答",
      research: "临时研究",
      learn: "系统学习",
      explain_back: "理解检查",
      project_execution: "项目推进",
      conversation: "临时对话",
      organize: "整理结果",
    }[intent] ?? intent
  );
}

export function closureActionLabel(contract: TaskContract | undefined): string | null {
  if (!contract) return "整理学习";
  if (contract.closure_eligibility === "learning_summary") return "整理学习";
  if (contract.closure_eligibility === "project_summary") return "收束项目";
  // Research-summary generation is not wired to the current learning closure endpoint yet.
  return null;
}
