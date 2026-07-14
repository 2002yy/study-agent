export type TaskIntent =
  | "quick_answer"
  | "research"
  | "learn"
  | "explain_back"
  | "project_execution"
  | "conversation"
  | "organize";

export type TaskContract = {
  task_intent: string;
  source_policy: string;
  closure_eligibility: string;
  learning_state_enabled: boolean;
  confidence?: string;
  reason?: string;
  explicit_override?: boolean;
};

export const TURN_TASK_INTENT_OPTIONS: Array<{
  value: "" | TaskIntent;
  label: string;
  description: string;
}> = [
  { value: "", label: "自动判断", description: "根据下一条消息和当前学习状态判断" },
  { value: "learn", label: "系统学习", description: "持续推进目标、阶段和理解验证" },
  { value: "quick_answer", label: "快速问答", description: "只回答当前问题，不推进长期学习状态" },
  { value: "research", label: "临时研究", description: "侧重公开资料、最新信息和来源" },
  { value: "project_execution", label: "项目推进", description: "围绕实现、验证和交付推进" },
];

let pendingTaskIntentOverride: TaskIntent | undefined;

export function setPendingTaskIntentOverride(intent: TaskIntent | undefined): void {
  pendingTaskIntentOverride = intent;
}

export function consumePendingTaskIntentOverride(): TaskIntent | undefined {
  const current = pendingTaskIntentOverride;
  pendingTaskIntentOverride = undefined;
  return current;
}

export function clearPendingTaskIntentOverride(): void {
  pendingTaskIntentOverride = undefined;
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : undefined;
}

export function taskContractFromRoute(
  route: Record<string, unknown> | undefined
): TaskContract | undefined {
  const raw = asRecord(route?.task_contract);
  if (!raw || typeof raw.task_intent !== "string") return undefined;
  return {
    task_intent: raw.task_intent,
    source_policy: String(raw.source_policy ?? "model_only"),
    closure_eligibility: String(raw.closure_eligibility ?? "not_applicable"),
    learning_state_enabled: raw.learning_state_enabled === true,
    confidence: typeof raw.confidence === "string" ? raw.confidence : undefined,
    reason: typeof raw.reason === "string" ? raw.reason : undefined,
    explicit_override:
      typeof raw.explicit_override === "boolean" ? raw.explicit_override : undefined,
  };
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
