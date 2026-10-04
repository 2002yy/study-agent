import * as firefly from "./fireflyLessonModel";
import {
  buildDoupoConversationContext,
  createDefaultDoupoLessonState,
  type DoupoLessonState,
} from "./defaultDoupoLesson";

export type FireflyCardId = firefly.FireflyCardId;
export type FireflyBossToughness = firefly.FireflyBossToughness;
export type FireflyInvestment = firefly.FireflyInvestment;
export type FireflyTeamRoute = firefly.FireflyTeamRoute;
export type FireflyMode = firefly.FireflyMode;
export type FireflyPainPoint = firefly.FireflyPainPoint;
export type FireflyEnvironment = firefly.FireflyEnvironment;
export type FireflyCone = firefly.FireflyCone;
export type FireflySustain = firefly.FireflySustain;
export type FireflyOneGoldConfig = firefly.FireflyOneGoldConfig;
export type OneGoldRecommendation = firefly.OneGoldRecommendation;
export type DefaultLessonKind = "firefly" | "doupo";

export type FireflyLessonState = firefly.FireflyLessonState & {
  lessonKind: DefaultLessonKind;
  doupo: DoupoLessonState;
};

export type FireflyLessonController = {
  state: FireflyLessonState;
  update: (patch: Partial<FireflyLessonState>) => void;
  reset: () => void;
};

export const FIREFLY_CARD_ORDER = firefly.FIREFLY_CARD_ORDER;
export const FIREFLY_CARD_LABELS = firefly.FIREFLY_CARD_LABELS;
export const BOSS_INVESTMENT_LABELS = firefly.BOSS_INVESTMENT_LABELS;
export const TEAM_ROUTE_LABELS = firefly.TEAM_ROUTE_LABELS;
export const MODE_LABELS = firefly.MODE_LABELS;
export const PAIN_POINT_LABELS = firefly.PAIN_POINT_LABELS;

export function createDefaultFireflyLessonState(): FireflyLessonState {
  return {
    ...firefly.createDefaultFireflyLessonState(),
    lessonKind: "firefly",
    doupo: createDefaultDoupoLessonState(),
  };
}

export const bossSkillToughness = firefly.bossSkillToughness;
export const dahliaFirstBreakBonus = firefly.dahliaFirstBreakBonus;
export const bossHitCount = firefly.bossHitCount;
export const cloudflameToughness = firefly.cloudflameToughness;

export function oneGoldRecommendation(
  state: FireflyLessonState,
): OneGoldRecommendation {
  return firefly.oneGoldRecommendation(state);
}

export function buildFireflyConversationContext(state: FireflyLessonState): string {
  if (!state.active) return "";
  if (state.lessonKind === "doupo") {
    return buildDoupoConversationContext(state.doupo);
  }
  return firefly.buildFireflyConversationContext(state);
}
