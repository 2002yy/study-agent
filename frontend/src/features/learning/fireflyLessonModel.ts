export type FireflyCardId =
  | "firefly-and-sam"
  | "combat-loop"
  | "super-break"
  | "eidolons-and-cones"
  | "dahlia"
  | "fugue"
  | "lingsha-gallagher"
  | "team-upgrades"
  | "damage-ledger"
  | "enemy-environment";

export type FireflyBossToughness = 300 | 600 | 1200 | "locked";
export type FireflyInvestment =
  | "firefly-0"
  | "dahlia-0"
  | "dahlia-1"
  | "fugue-1"
  | "firefly-6";
export type FireflyTeamRoute = "starter" | "dahlia" | "classic" | "premium";
export type FireflyMode = "memory" | "apocalyptic" | "fiction" | "arbitration";
export type FireflyPainPoint =
  | "break-slow"
  | "locked-damage"
  | "skill-points"
  | "single-hit"
  | "actions"
  | "survival";
export type FireflyEnvironment = "general" | "high-resistance" | "multi-wave";
export type FireflyCone = "free" | "four-star" | "signature";
export type FireflySustain = "gallagher" | "lingsha-0" | "lingsha-1" | "none";

export type FireflyOneGoldConfig = {
  fireflyEidolon: number;
  fireflyCone: FireflyCone;
  dahliaEidolon: number | null;
  fugueEidolon: number | null;
  sustain: FireflySustain;
};

export type FireflyLessonState = {
  active: boolean;
  activeCardId: FireflyCardId;
  expandedCardId: FireflyCardId | null;
  bossToughness: FireflyBossToughness;
  investment: FireflyInvestment;
  showBossMath: boolean;
  teamRoute: FireflyTeamRoute;
  mode: FireflyMode;
  painPoint: FireflyPainPoint;
  environment: FireflyEnvironment;
  oneGold: FireflyOneGoldConfig;
};

export type FireflyLessonController = {
  state: FireflyLessonState;
  update: (patch: Partial<FireflyLessonState>) => void;
  reset: () => void;
};

export const FIREFLY_CARD_ORDER: FireflyCardId[] = [
  "firefly-and-sam",
  "combat-loop",
  "super-break",
  "eidolons-and-cones",
  "dahlia",
  "fugue",
  "lingsha-gallagher",
  "team-upgrades",
  "damage-ledger",
  "enemy-environment",
];

export const FIREFLY_CARD_LABELS: Record<FireflyCardId, string> = {
  "firefly-and-sam": "流萤与萨姆",
  "combat-loop": "一轮怎么打",
  "super-break": "超击破怎么算",
  "eidolons-and-cones": "六个星魂",
  dahlia: "大丽花",
  fugue: "忘归人",
  "lingsha-gallagher": "灵砂与加拉赫",
  "team-upgrades": "配队怎么升级",
  "damage-ledger": "满配伤害账",
  "enemy-environment": "换怪以后",
};

export const BOSS_INVESTMENT_LABELS: Record<FireflyInvestment, string> = {
  "firefly-0": "流萤0魂",
  "dahlia-0": "+大丽花0魂",
  "dahlia-1": "+大丽花1魂",
  "fugue-1": "+忘归人1魂",
  "firefly-6": "+流萤6魂",
};

export const TEAM_ROUTE_LABELS: Record<FireflyTeamRoute, string> = {
  starter: "起步",
  dahlia: "加入大丽花",
  classic: "老牌配置",
  premium: "高配",
};

export const MODE_LABELS: Record<FireflyMode, string> = {
  memory: "混沌回忆",
  apocalyptic: "末日幻影",
  fiction: "虚构叙事",
  arbitration: "异相仲裁",
};

export const PAIN_POINT_LABELS: Record<FireflyPainPoint, string> = {
  "break-slow": "破韧太慢",
  "locked-damage": "锁韧没伤害",
  "skill-points": "战技点太紧",
  "single-hit": "单次伤害不足",
  actions: "行动次数不够",
  survival: "生存/控制",
};

export function createDefaultFireflyLessonState(): FireflyLessonState {
  return {
    active: true,
    activeCardId: "firefly-and-sam",
    expandedCardId: null,
    bossToughness: 1200,
    investment: "dahlia-1",
    showBossMath: false,
    teamRoute: "starter",
    mode: "memory",
    painPoint: "break-slow",
    environment: "general",
    oneGold: {
      fireflyEidolon: 0,
      fireflyCone: "free",
      dahliaEidolon: null,
      fugueEidolon: null,
      sustain: "gallagher",
    },
  };
}

export function bossSkillToughness(investment: FireflyInvestment): number {
  if (investment === "firefly-0") return 45;
  if (investment === "dahlia-0" || investment === "dahlia-1") return 80;
  if (investment === "fugue-1") return 95;
  return 110;
}

export function dahliaFirstBreakBonus(toughness: number): number {
  return Math.min(toughness * 0.25, 300);
}

export function bossHitCount(
  toughness: FireflyBossToughness,
  investment: FireflyInvestment,
): number | null {
  if (toughness === "locked") return null;
  const perHit = bossSkillToughness(investment);
  const firstBonus =
    investment === "dahlia-1" || investment === "fugue-1" || investment === "firefly-6"
      ? dahliaFirstBreakBonus(toughness)
      : 0;
  return Math.max(1, Math.ceil((toughness - firstBonus) / perHit));
}

export function cloudflameToughness(toughness: FireflyBossToughness): number | null {
  if (toughness === "locked") return null;
  return toughness * 0.4;
}

export type OneGoldRecommendation = {
  key: "A" | "B" | "C" | "D" | "E" | "F" | "G";
  title: string;
  summary: string;
  details: string[];
};

export function oneGoldRecommendation(state: FireflyLessonState): OneGoldRecommendation {
  const { oneGold, painPoint, environment } = state;

  if (oneGold.sustain === "lingsha-0" && painPoint === "survival") {
    return {
      key: "G",
      title: "灵砂1魂",
      summary: "生存位继续承担治疗，同时把破韧与减防一起抬高。",
      details: ["灵砂自身弱点击破效率+50%", "敌人被弱点击破后防御-20%"],
    };
  }

  if (oneGold.fugueEidolon === 0 && painPoint === "actions") {
    return {
      key: "F",
      title: "忘归人2魂",
      summary: "这里买的是整队行动节奏，不是只给流萤加一层伤害。",
      details: ["每次敌人被弱点击破时忘归人回能", "终结技使全队行动提前24%"],
    };
  }

  if (environment === "high-resistance" || environment === "multi-wave") {
    return {
      key: "E",
      title: "大丽花2魂",
      summary:
        environment === "high-resistance"
          ? "高抗性环境里，全属性抗性下降会直接抬高整队结算。"
          : "多波次里，新敌入场自动进入败谢，省掉重新铺状态的等待。",
      details: ["全体敌人全属性抗性-20%", "新敌入场自动进入败谢"],
    };
  }

  if (
    oneGold.fireflyEidolon >= 2 &&
    oneGold.dahliaEidolon === 0 &&
    painPoint === "break-slow"
  ) {
    return {
      key: "C",
      title: "大丽花1魂",
      summary: "1200韧性简化模型从15发缩到12发，首次额外削300韧性。",
      details: ["首次额外削减25%最大韧性，最高300", "共舞者超击破倍率再增加40个百分点"],
    };
  }

  if (
    oneGold.fireflyEidolon === 1 &&
    oneGold.dahliaEidolon !== null &&
    painPoint === "actions"
  ) {
    return {
      key: "B",
      title: "流萤2魂 vs 流萤专武",
      summary: "这里选的是“多打一整次”和“每次打得更重”的区别。",
      details: ["2魂：击杀/弱点击破后获得额外回合", "专武：击破特攻、专属击破易伤、减速"],
    };
  }

  if (
    oneGold.dahliaEidolon !== null &&
    (painPoint === "single-hit" || painPoint === "skill-points")
  ) {
    return {
      key: "D",
      title: "大丽花1魂 vs 大丽花专武",
      summary: "一边买削韧时点与共舞者超击破，一边买单次伤害与战技点循环。",
      details: ["1魂：削韧时点 / 共舞者超击破", "专武：单次击破伤害 / 战技点循环"],
    };
  }

  if (oneGold.dahliaEidolon === null) {
    return {
      key: "A",
      title: "先比较大丽花0魂",
      summary: "她先改变队伍结构，再和流萤1魂、流萤专武比较你具体买到了什么。",
      details: [
        "+50%弱点击破效率",
        "未破韧阶段也能产生超击破",
        "减防与固定火削韧",
        "战技点回收并帮助流萤缩短再次开大等待",
      ],
    };
  }

  return {
    key: "D",
    title: "按当前痛点比较边际收益",
    summary: "当前配置没有命中预设捷径，先比较能否改变破韧时点、行动次数与循环资源。",
    details: ["先看首领实验的削韧时点", "再看战技点、能量、行动提前与额外回合"],
  };
}

function oneGoldSummary(oneGold: FireflyOneGoldConfig): string {
  const cone =
    oneGold.fireflyCone === "signature"
      ? "专武"
      : oneGold.fireflyCone === "four-star"
        ? "四星光锥"
        : "免费光锥";
  const dahlia = oneGold.dahliaEidolon === null ? "无大丽花" : `大丽花${oneGold.dahliaEidolon}魂`;
  const fugue = oneGold.fugueEidolon === null ? "无忘归人" : `忘归人${oneGold.fugueEidolon}魂`;
  const sustain =
    oneGold.sustain === "gallagher"
      ? "加拉赫"
      : oneGold.sustain === "lingsha-0"
        ? "灵砂0魂"
        : oneGold.sustain === "lingsha-1"
          ? "灵砂1魂+"
          : "无生存位";
  return `流萤${oneGold.fireflyEidolon}魂·${cone} / ${dahlia} / ${fugue} / ${sustain}`;
}

export function buildFireflyConversationContext(state: FireflyLessonState): string {
  if (!state.active) return "";
  const card = FIREFLY_CARD_LABELS[state.activeCardId];
  const boss = state.bossToughness === "locked" ? "锁韧" : `${state.bossToughness}韧性`;
  const hits = bossHitCount(state.bossToughness, state.investment);
  const recommendation = oneGoldRecommendation(state);
  return [
    "【当前默认示例界面状态】",
    "主题：流萤超击破体系；数据按4.2加强后口径。",
    `当前卡片：${card}。`,
    `首领实验：${boss} / ${BOSS_INVESTMENT_LABELS[state.investment]}${hits === null ? "；锁韧期间不显示虚假攻击次数" : `；简化模型需要${hits}次流萤强化战技` }。`,
    `配队路线：${TEAM_ROUTE_LABELS[state.teamRoute]}；模式：${MODE_LABELS[state.mode]}。`,
    `一金配置：${oneGoldSummary(state.oneGold)}；痛点：${PAIN_POINT_LABELS[state.painPoint]}；当前候选：${recommendation.title}。`,
    "回答与当前卡片/实验状态相关的问题时，优先引用这些状态，不要重新泛泛介绍；首领实验只统计流萤主目标削韧，是教学简化模型。",
    "这段界面状态只服务默认示例问答，不得写入 durable learner truth，也不得把抽取建议记成用户长期事实。",
  ].join("\n");
}
