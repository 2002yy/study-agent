export type GoldenJourneyId =
  | "first_answer"
  | "system_learning"
  | "material_learning"
  | "web_research"
  | "source_code_learning";

export type GoldenJourneyBudget = {
  label: string;
  maxRequiredDecisionsBeforeStart: number;
  maxProductSurfaces: number;
  maxRecoveryClicks: number;
  nextActionMustBeExplicit: boolean;
};

/**
 * Product-level budgets, not implementation metrics.
 *
 * A new feature may add internal owners, runs, providers, or durable state, but
 * it must not silently make these five core journeys more expensive for the learner.
 */
export const GOLDEN_JOURNEY_BUDGETS: Record<GoldenJourneyId, GoldenJourneyBudget> = {
  first_answer: {
    label: "第一次打开 -> 提问 -> 获得回答",
    maxRequiredDecisionsBeforeStart: 0,
    maxProductSurfaces: 1,
    maxRecoveryClicks: 0,
    nextActionMustBeExplicit: true,
  },
  system_learning: {
    label: "系统学习 -> 理解验证 -> 整理 -> 下次恢复",
    maxRequiredDecisionsBeforeStart: 1,
    maxProductSurfaces: 2,
    maxRecoveryClicks: 1,
    nextActionMustBeExplicit: true,
  },
  material_learning: {
    label: "上传文档 -> 等待完成 -> 围绕资料提问 -> 查看引用",
    maxRequiredDecisionsBeforeStart: 1,
    maxProductSurfaces: 2,
    maxRecoveryClicks: 1,
    nextActionMustBeExplicit: true,
  },
  web_research: {
    label: "联网研究 -> 查看进度 -> 中止 -> 恢复 -> 继续对话",
    maxRequiredDecisionsBeforeStart: 0,
    maxProductSurfaces: 1,
    maxRecoveryClicks: 1,
    nextActionMustBeExplicit: true,
  },
  source_code_learning: {
    label: "GitHub 源码学习 -> 阅读源码 -> 回到学习目标",
    maxRequiredDecisionsBeforeStart: 0,
    maxProductSurfaces: 1,
    maxRecoveryClicks: 1,
    nextActionMustBeExplicit: true,
  },
};

export const ORDINARY_SURFACE_FORBIDDEN_TERMS = [
  "TaskContract",
  "ResearchRun",
  "run_id",
  "session_id",
  "topK",
  "vector backend",
  "provider_status",
] as const;
