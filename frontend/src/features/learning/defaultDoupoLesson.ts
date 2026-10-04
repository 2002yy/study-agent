export type DoupoCardId =
  | "debt"
  | "delay"
  | "social-valuation"
  | "evidence-ladder"
  | "layered-update"
  | "real-failure"
  | "false-ending"
  | "identity-merge"
  | "moral-settlement"
  | "reader-pay";

export type DoupoKnowledgeMoment =
  | "duel-open"
  | "model-breaks"
  | "identity-reveal";
export type DoupoKnowledgeStatus = "yes" | "no" | "updating";
export type DoupoWitnessId =
  | "xiao-yan"
  | "nalan-yanran"
  | "liu-ling"
  | "nalan-jie"
  | "yunlan-disciples"
  | "reader";
export type DoupoFactId = "not-waste" | "yanxiao-champion" | "same-person";
export type DoupoValuationPoint =
  | "retirement"
  | "clan-test"
  | "external-audit"
  | "alchemy"
  | "duel-open"
  | "identity-merge"
  | "settlement";
export type DoupoValuationSeriesId =
  | "reader"
  | "clan"
  | "city"
  | "nalan"
  | "yunlan";
export type DoupoGateId = "G1" | "G2" | "G3" | "G4" | "G5" | "G6" | "G7";

export type DoupoLessonState = {
  activeCardId: DoupoCardId;
  expandedCardId: DoupoCardId | null;
  knowledgeMoment: DoupoKnowledgeMoment;
  valuationPoint: DoupoValuationPoint;
  identityMerged: boolean;
  gates: Record<DoupoGateId, boolean>;
};

export type DoupoLessonController = {
  state: DoupoLessonState;
  update: (patch: Partial<DoupoLessonState>) => void;
  reset: () => void;
};

export const DOUPO_CARD_ORDER: DoupoCardId[] = [
  "debt",
  "delay",
  "social-valuation",
  "evidence-ladder",
  "layered-update",
  "real-failure",
  "false-ending",
  "identity-merge",
  "moral-settlement",
  "reader-pay",
];

export const DOUPO_CARD_LABELS: Record<DoupoCardId, string> = {
  debt: "爽点开始于打脸吗？",
  delay: "为什么不能马上打回去？",
  "social-valuation": "“废物”究竟是什么？",
  "evidence-ladder": "石碑证明了，为什么还要萧克？",
  "layered-update": "为什么震惊必须一层一层来？",
  "real-failure": "主角真的失败，会不会破坏爽感？",
  "false-ending": "“炸炉”为什么不是再来一次失败？",
  "identity-merge": "“岩枭=萧炎”为什么会炸？",
  "moral-settlement": "三年之约到底在结什么账？",
  "reader-pay": "高潮结束以后怎么办？",
};

export const DOUPO_KNOWLEDGE_MOMENT_LABELS: Record<DoupoKnowledgeMoment, string> = {
  "duel-open": "三年之约开场",
  "model-breaks": "旧模型开始失效",
  "identity-reveal": "异火暴露后",
};

export const DOUPO_WITNESS_LABELS: Record<DoupoWitnessId, string> = {
  "xiao-yan": "萧炎",
  "nalan-yanran": "纳兰嫣然",
  "liu-ling": "柳翎",
  "nalan-jie": "纳兰桀",
  "yunlan-disciples": "云岚宗弟子",
  reader: "读者",
};

export const DOUPO_FACT_LABELS: Record<DoupoFactId, string> = {
  "not-waste": "萧炎已不是三年前的“废物”",
  "yanxiao-champion": "岩枭是炼药师大会冠军",
  "same-person": "岩枭就是萧炎",
};

const yes: DoupoKnowledgeStatus = "yes";
const no: DoupoKnowledgeStatus = "no";
const updating: DoupoKnowledgeStatus = "updating";

export const DOUPO_KNOWLEDGE_MATRIX: Record<
  DoupoKnowledgeMoment,
  Record<DoupoWitnessId, Record<DoupoFactId, DoupoKnowledgeStatus>>
> = {
  "duel-open": {
    "xiao-yan": { "not-waste": yes, "yanxiao-champion": yes, "same-person": yes },
    "nalan-yanran": { "not-waste": updating, "yanxiao-champion": yes, "same-person": no },
    "liu-ling": { "not-waste": no, "yanxiao-champion": yes, "same-person": no },
    "nalan-jie": { "not-waste": updating, "yanxiao-champion": yes, "same-person": no },
    "yunlan-disciples": { "not-waste": no, "yanxiao-champion": yes, "same-person": no },
    reader: { "not-waste": yes, "yanxiao-champion": yes, "same-person": yes },
  },
  "model-breaks": {
    "xiao-yan": { "not-waste": yes, "yanxiao-champion": yes, "same-person": yes },
    "nalan-yanran": { "not-waste": yes, "yanxiao-champion": yes, "same-person": no },
    "liu-ling": { "not-waste": yes, "yanxiao-champion": yes, "same-person": no },
    "nalan-jie": { "not-waste": yes, "yanxiao-champion": yes, "same-person": no },
    "yunlan-disciples": { "not-waste": updating, "yanxiao-champion": yes, "same-person": no },
    reader: { "not-waste": yes, "yanxiao-champion": yes, "same-person": yes },
  },
  "identity-reveal": {
    "xiao-yan": { "not-waste": yes, "yanxiao-champion": yes, "same-person": yes },
    "nalan-yanran": { "not-waste": yes, "yanxiao-champion": yes, "same-person": yes },
    "liu-ling": { "not-waste": yes, "yanxiao-champion": yes, "same-person": yes },
    "nalan-jie": { "not-waste": yes, "yanxiao-champion": yes, "same-person": yes },
    "yunlan-disciples": { "not-waste": yes, "yanxiao-champion": yes, "same-person": yes },
    reader: { "not-waste": yes, "yanxiao-champion": yes, "same-person": yes },
  },
};

export const DOUPO_VALUATION_POINT_LABELS: Record<DoupoValuationPoint, string> = {
  retirement: "第7章·退婚债建立",
  "clan-test": "30～32章·家族公开测试",
  "external-audit": "39～40章·外部复测",
  alchemy: "炼药师大会·高价值身份分账",
  "duel-open": "三年之约开场",
  "identity-merge": "第337章·身份合并",
  settlement: "三年之约结算",
};

export const DOUPO_VALUATION_SERIES_LABELS: Record<DoupoValuationSeriesId, string> = {
  reader: "读者",
  clan: "萧家同辈",
  city: "乌坦城外部势力",
  nalan: "纳兰嫣然",
  yunlan: "云岚宗",
};

export const DOUPO_VALUATION: Record<
  DoupoValuationPoint,
  Record<DoupoValuationSeriesId, number>
> = {
  retirement: { reader: 44, clan: 12, city: 8, nalan: 14, yunlan: 6 },
  "clan-test": { reader: 66, clan: 54, city: 24, nalan: 16, yunlan: 8 },
  "external-audit": { reader: 73, clan: 69, city: 61, nalan: 18, yunlan: 10 },
  alchemy: { reader: 88, clan: 71, city: 64, nalan: 34, yunlan: 17 },
  "duel-open": { reader: 91, clan: 74, city: 66, nalan: 47, yunlan: 24 },
  "identity-merge": { reader: 94, clan: 78, city: 72, nalan: 91, yunlan: 82 },
  settlement: { reader: 96, clan: 82, city: 76, nalan: 94, yunlan: 90 },
};

export const DOUPO_GATE_LABELS: Record<DoupoGateId, string> = {
  G1: "旧估值成立",
  G2: "延迟成立",
  G3: "证据升级",
  G4: "见证者有权重",
  G5: "行为发生改变",
  G6: "状态能够持久",
  G7: "结算保持对称",
};

export const DOUPO_GATE_QUESTIONS: Record<DoupoGateId, string> = {
  G1: "人物为什么这样看主角？这个判断真的影响过关系、资源或尊严吗？",
  G2: "为什么不能立刻纠正？等待是否来自权力差、信息差或现实约束？",
  G3: "这次证据解决了新的怀疑，还是只把同一个数字再放大？",
  G4: "见证者此前押过什么判断、关系、资源或权力？",
  G5: "认知更新以后，人物实际做了什么不同的事？",
  G6: "下一场景还保留这次重新估值，还是换地图就清零？",
  G7: "回报是否与原债相称，主角有没有从受不公者变成新的不公者？",
};

export function createDefaultDoupoLessonState(): DoupoLessonState {
  return {
    activeCardId: "debt",
    expandedCardId: null,
    knowledgeMoment: "duel-open",
    valuationPoint: "retirement",
    identityMerged: false,
    gates: {
      G1: true,
      G2: true,
      G3: true,
      G4: true,
      G5: true,
      G6: true,
      G7: true,
    },
  };
}

export function doupoGateCount(state: DoupoLessonState): number {
  return (Object.keys(state.gates) as DoupoGateId[]).filter((gate) => state.gates[gate]).length;
}

export function doupoGateDiagnosis(state: DoupoLessonState): string {
  const count = doupoGateCount(state);
  if (!state.gates.G7) {
    return "结算越过原债的合法边界，爽点可能发生道德反转。";
  }
  if (count === 7) {
    return "七门完整：这次重新估值具备长程结算的结构条件。";
  }
  if (count >= 5) {
    return "能形成即时回报，但仍有状态漏账；缺失的门会削弱长期记忆价值。";
  }
  return "有打脸，没重量：旧估值、证据、见证或后续状态没有形成完整闭环。";
}

export function doupoValuationGap(point: DoupoValuationPoint): number {
  const current = DOUPO_VALUATION[point];
  const socialAverage = (current.clan + current.city + current.nalan + current.yunlan) / 4;
  return Math.round(current.reader - socialAverage);
}

export function buildDoupoConversationContext(state: DoupoLessonState): string {
  const disabledGates = (Object.keys(state.gates) as DoupoGateId[])
    .filter((gate) => !state.gates[gate])
    .map((gate) => `${gate} ${DOUPO_GATE_LABELS[gate]}`);
  const gateSummary = disabledGates.length
    ? `通过${doupoGateCount(state)}/7；关闭：${disabledGates.join("、")}`
    : "通过7/7";
  return [
    "【当前默认示例界面状态】",
    "主题：长篇小说为什么会让你爽——拆解《斗破苍穹》的认知翻转。",
    `当前卡片：${DOUPO_CARD_LABELS[state.activeCardId]}。`,
    `人物知识状态：${DOUPO_KNOWLEDGE_MOMENT_LABELS[state.knowledgeMoment]}。`,
    `社会估值曲线：${DOUPO_VALUATION_POINT_LABELS[state.valuationPoint]}；读者与四个社会圈层的教学估值差约${doupoValuationGap(state.valuationPoint)}点。`,
    `身份合并实验：${state.identityMerged ? "已执行‘岩枭=萧炎’，正在回溯重算旧判断" : "尚未合并‘萧炎’与‘岩枭’两个价值账户"}。`,
    `重新估值七门：${gateSummary}。`,
    "回答与当前卡片或实验相关的问题时，优先读取这些界面状态；估值曲线是教学量表，不是原文数值。",
    "原文事实与结构解释必须分开：四组原文样本支持认知翻转机制，但不能把类型传播归因扩大成《斗破》发明了升级流。",
    "这段界面状态只服务默认示例问答，不得写入 durable learner truth，也不得把叙事判断记成用户长期事实。",
  ].join("\n");
}
