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

export type DoupoLoopId =
  | "retirement-contract"
  | "clan-repricing"
  | "alchemy-false-ending"
  | "three-year-settlement";

export type DoupoLoopStage =
  | "old-valuation"
  | "debt"
  | "suppression"
  | "hidden-growth"
  | "approach-reveal"
  | "hard-evidence"
  | "repricing"
  | "retroactive"
  | "new-debt";

export type DoupoLoopProfile = {
  label: string;
  chapters: string;
  oneLine: string;
  stages: Record<DoupoLoopStage, string>;
};

export type DoupoLessonState = {
  activeCardId: DoupoCardId;
  expandedCardId: DoupoCardId | null;
  knowledgeMoment: DoupoKnowledgeMoment;
  valuationPoint: DoupoValuationPoint;
  identityMerged: boolean;
  activeLoopId: DoupoLoopId;
  activeLoopStage: DoupoLoopStage;
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
  debt: "退婚：先欠下一笔能记三年的账",
  delay: "延迟：把今天还不了的债拖到更贵",
  "social-valuation": "“废物”：社会价格为什么落后于真实价值",
  "evidence-ladder": "证据梯：同一个结论为什么要换着证明",
  "layered-update": "认知破裂：爽感为什么要一层层兑现",
  "real-failure": "真失败：先烧掉确定性，再重新下注",
  "false-ending": "假终局：让错误共识先成立",
  "identity-merge": "身份合并：两份价值账户一次性并账",
  "moral-settlement": "三年之约：把尊严债还到边界为止",
  "reader-pay": "余波：旧账结清，再欠下一笔新账",
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

export const DOUPO_LOOP_ORDER: DoupoLoopId[] = [
  "retirement-contract",
  "clan-repricing",
  "alchemy-false-ending",
  "three-year-settlement",
];

export const DOUPO_LOOP_STAGE_ORDER: DoupoLoopStage[] = [
  "old-valuation",
  "debt",
  "suppression",
  "hidden-growth",
  "approach-reveal",
  "hard-evidence",
  "repricing",
  "retroactive",
  "new-debt",
];

export const DOUPO_LOOP_STAGE_LABELS: Record<DoupoLoopStage, string> = {
  "old-valuation": "旧估值",
  debt: "欠债",
  suppression: "压住不还",
  "hidden-growth": "暗中增值",
  "approach-reveal": "逼近揭示",
  "hard-evidence": "公开硬证据",
  repricing: "重新定价",
  retroactive: "回溯重构",
  "new-debt": "余波 / 新债",
};

export const DOUPO_LOOP_PROFILES: Record<DoupoLoopId, DoupoLoopProfile> = {
  "retirement-contract": {
    label: "退婚大厅：把屈辱写成未来合同",
    chapters: "第7章",
    oneLine: "这一轮不负责还债，只负责把债写清、写大、写成三年后必须公开兑现的合同。",
    stages: {
      "old-valuation": "萧炎被“三段斗之气、废物、未来有限”的旧价格包围。",
      debt: "借云岚宗权势公开处理婚约，伤到的不只是萧炎，也包括萧战与萧家的尊严。",
      suppression: "此刻实力和势力都不允许可信结算，强行反击只会把家族拖进风险。",
      "hidden-growth": "读者先拿到十二岁旧成绩与主角意志，知道旧标签并不等于真实上限。",
      "approach-reveal": "反写休书和三年之约把模糊羞辱改写成明确的未来验证点。",
      "hard-evidence": "这一轮暂时没有最终硬证据；它故意把硬证据推迟到三年后。",
      repricing: "现场社会价格没有彻底改变，只发生局部行动权回收。",
      retroactive: "回溯重构尚未发生，旧模型被保留，给后续数百章留下空间。",
      "new-debt": "三年之约成为新的长期承诺，读者知道这笔账迟早要在公开场域结。",
    },
  },
  "clan-repricing": {
    label: "30～40章：让“废物”这个价格逐级失效",
    chapters: "30～40章附近",
    oneLine: "不是靠一次震惊翻身，而是让每一条新证据关闭一种旧解释。",
    stages: {
      "old-valuation": "萧家同辈和乌坦城仍在用三年低谷给萧炎定价。",
      debt: "旧标签继续影响关系距离、轻视程度和外部势力的风险判断。",
      suppression: "第一次七段测试出现后，旧模型还能解释成偶然、测试问题或信息滞后。",
      "hidden-growth": "萧炎的真实成长速度持续领先于外界掌握的信息。",
      "approach-reveal": "正式测量、挑战、严格复测和外部核验一层层逼近同一结论。",
      "hard-evidence": "独立实战与更严格复测切断“石碑偶然”的退路。",
      repricing: "同辈、家族与外部势力开始改变接近、关注和资源判断。",
      retroactive: "人物开始承认过去几年形成的“废物”解释已经不能覆盖现在。",
      "new-debt": "社会价格虽被抬高，但纳兰嫣然与云岚宗这两个更远圈层仍没有完成更新。",
    },
  },
  "alchemy-false-ending": {
    label: "炼药大会：先让失败成立，再翻掉终局",
    chapters: "316～322章附近",
    oneLine: "热门身份先遭遇真失败，再制造一个合理的假终局，最后靠实物和专业审计完成翻转。",
    stages: {
      "old-valuation": "岩枭已经是热门炼药师，旧价格不是“废物”，而是“强但未必稳拿冠军”。",
      debt: "读者和场内人物已经把冠军期待押在岩枭身上，失败会真实损伤这份预期。",
      suppression: "第一次炼制确实失败，作者不立刻宣布“这是计划的一部分”。",
      "hidden-growth": "压力迫使萧炎重新下注，失败也推动能力状态发生变化。",
      "approach-reveal": "第二次炼制把药鼎裂缝、炸炉和白雾一步步推成失败信号。",
      "hard-evidence": "白雾散开后，三纹青灵丹仍在；随后专业人物继续检查，关闭最后的替代解释。",
      repricing: "结果从“这场赢了”上升为“这个年轻人的长期上限更高”。",
      retroactive: "前面的真失败不再被抹掉，而被重解释为这次翻盘为什么昂贵。",
      "new-debt": "“岩枭”账户继续增值，但这份高价值仍没有记到“萧炎”名字下。",
    },
  },
  "three-year-settlement": {
    label: "三年之约：多条价值线一次性并账",
    chapters: "332～340章附近",
    oneLine: "萧炎实力线、岩枭身份线和退婚尊严债在同一公开场域合流，形成最大规模的重新定价。",
    stages: {
      "old-valuation": "纳兰嫣然、云岚宗与更大公众仍保留对“三年前萧炎”的旧价格。",
      debt: "第7章留下的尊严债仍未公开结清，三年之约就是到期日。",
      suppression: "开场不能直接跳到身份揭露，旧判断必须先在战斗里逐步失效。",
      "hidden-growth": "读者早已知道萧炎的实力增长、炼药身份与异火线索，而场内人物掌握得更少。",
      "approach-reveal": "连续攻防先证明“他早已不是三年前的人”，但仍未解释岩枭这条高价值账户。",
      "hard-evidence": "胜负与异火暴露提供无法辩解的公开事实，并触发“岩枭就是萧炎”的身份合并。",
      repricing: "纳兰嫣然、柳翎、纳兰桀、云岚宗等同时被迫重算萧炎的价值。",
      retroactive: "炼药大会、异火、沙漠线索和三年前的选择被一口气重新解释，过去几百章一起升值。",
      "new-debt": "旧账完成情绪结算后，云棱与墨承相关因果接管局面，故事立刻进入新的债务循环。",
    },
  },
};

export function createDefaultDoupoLessonState(): DoupoLessonState {
  return {
    activeCardId: "debt",
    expandedCardId: null,
    knowledgeMoment: "duel-open",
    valuationPoint: "retirement",
    identityMerged: false,
    activeLoopId: "retirement-contract",
    activeLoopStage: "debt",
  };
}

export function doupoValuationGap(point: DoupoValuationPoint): number {
  const current = DOUPO_VALUATION[point];
  const socialAverage = (current.clan + current.city + current.nalan + current.yunlan) / 4;
  return Math.round(current.reader - socialAverage);
}

export function buildDoupoConversationContext(state: DoupoLessonState): string {
  const loop = DOUPO_LOOP_PROFILES[state.activeLoopId];
  return [
    "【当前《斗破苍穹》爽点循环分析状态】",
    "主题：不是教用户答题，而是直接拆解情绪债如何建立、增值、公开兑现，再滚进下一轮。",
    `当前分析卡：${DOUPO_CARD_LABELS[state.activeCardId]}。`,
    `当前循环：${loop.label}（${loop.chapters}）。`,
    `当前环节：${DOUPO_LOOP_STAGE_LABELS[state.activeLoopStage]}——${loop.stages[state.activeLoopStage]}`,
    `人物认知快照：${DOUPO_KNOWLEDGE_MOMENT_LABELS[state.knowledgeMoment]}。`,
    `社会估值快照：${DOUPO_VALUATION_POINT_LABELS[state.valuationPoint]}；读者与四个社会圈层的结构示意差约${doupoValuationGap(state.valuationPoint)}点。`,
    `身份账户：${state.identityMerged ? "已合并‘萧炎’与‘岩枭’，正在观察回溯重构" : "仍分开记录‘萧炎’与‘岩枭’两份社会价值"}。`,
    "回答时优先沿爽点循环追踪旧估值、情绪债、延迟条件、暗中增值、硬证据、重新定价、回溯重构和新债；不要把它改写成测验、课程目标或标准答案。",
    "原文事实与结构解释必须分开；估值数字只用于画出相对认知滞后，不是原文数值。",
    "这段状态只属于当前工作区分析视图，不写入长期学习状态，也不把叙事判断记成用户长期事实。",
  ].join("\n");
}
