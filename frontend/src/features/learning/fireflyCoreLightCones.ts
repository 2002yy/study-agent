import type { FireflyCoreCharacterKey } from "./fireflyCharacterData";

export type FireflyCoreLightCone = {
  name: string;
  superimposition: "S1" | "S5";
  effect: string;
  note: string;
};

export const FIREFLY_CORE_LIGHT_CONES: Record<
  FireflyCoreCharacterKey,
  FireflyCoreLightCone[]
> = {
  firefly: [
    {
      name: "梦应归于何处",
      superimposition: "S1",
      effect: "击破特攻+60%；装备者造成击破伤害后，使目标陷入溃败2回合：受到装备者造成的击破伤害+24%，速度-20%。",
      note: "流萤专武；易伤只提高装备者自己的击破伤害。",
    },
    {
      name: "记一位星神的陨落",
      superimposition: "S5",
      effect: "每次攻击使本场战斗攻击力+16%，最多4层（合计64%）；击破敌方弱点后造成的伤害+24%，持续2回合。",
      note: "免费五星；24%伤害提高不进入超击破，但64%攻击可经流萤A6继续转成击破特攻。",
    },
    {
      name: "铭记于心的约定",
      superimposition: "S5",
      effect: "击破特攻+56%；施放终结技后暴击率+30%，持续2回合。",
      note: "四星击破属性替代；暴击率不进入超击破。",
    },
  ],
  dahlia: [
    {
      name: "勿忘她的火焰",
      superimposition: "S1",
      effect: "击破特攻+60%；进入战斗时，使装备者与另一名开战队友造成的击破伤害+32%；若没有对应开战队友，则选取击破特攻最高的队友。装备者为敌人添加弱点时恢复1战技点，每次终结技之间最多1次；施放终结技重置。",
      note: "大丽花专武；同时覆盖击破伤害与战技点循环。",
    },
    {
      name: "决心如汗珠般闪耀",
      superimposition: "S5",
      effect: "命中未处于攻陷状态的目标时，有100%基础概率施加攻陷1回合；攻陷目标防御力-16%。",
      note: "四星减防方案，需要命中判定。",
    },
    {
      name: "新手任务开始前",
      superimposition: "S5",
      effect: "效果命中+40%；攻击防御力已降低的敌人后恢复8点能量。",
      note: "偏终结技循环；大丽花自身能稳定提供减防条件。",
    },
  ],
  fugue: [
    {
      name: "长路终有归途",
      superimposition: "S1",
      effect: "击破特攻+60%；敌方弱点被击破时，有100%基础概率使其受到的击破伤害+18%，持续2回合，可叠2层。",
      note: "忘归人专武；第二韧性让同一目标更容易连续建立两层。",
    },
    {
      name: "孤独的疗愈",
      superimposition: "S5",
      effect: "击破特攻+40%；施放终结技后自身持续伤害+48%，持续2回合；带有装备者施加的持续伤害的敌人被消灭时，恢复6点能量。",
      note: "黑塔商店五星；主要取击破特攻与特定场景回能。",
    },
    {
      name: "新手任务开始前",
      superimposition: "S5",
      effect: "效果命中+40%；攻击防御力已降低的敌人后恢复8点能量。",
      note: "忘归人能自行施加减防，回能条件容易成立。",
    },
    {
      name: "决心如汗珠般闪耀",
      superimposition: "S5",
      effect: "命中未处于攻陷状态的目标时，有100%基础概率施加攻陷1回合；攻陷目标防御力-16%。",
      note: "进一步叠防御区。",
    },
  ],
  lingsha: [
    {
      name: "唯有香如故",
      superimposition: "S1",
      effect: "击破特攻+60%；施放终结技攻击敌人后，使其陷入忘忧2回合：受到的伤害+10%；若灵砂当前击破特攻≥150%，再额外+8%。",
      note: "灵砂专武；满足阈值时合计18%受到伤害提高。",
    },
    {
      name: "等价交换",
      superimposition: "S5",
      effect: "装备者回合开始时，随机为1名当前能量百分比低于50%的其他队友恢复16点能量。",
      note: "团队回能，不提高灵砂自身伤害。",
    },
    {
      name: "一场术后对话",
      superimposition: "S5",
      effect: "能量恢复效率+16%；施放终结技时治疗量+24%。",
      note: "偏自身终结技循环。",
    },
    {
      name: "何物为真",
      superimposition: "S5",
      effect: "击破特攻+48%；施放普攻后，自身回复4%生命上限+800生命。",
      note: "可兑换的击破属性方案。",
    },
  ],
  gallagher: [
    {
      name: "何物为真",
      superimposition: "S5",
      effect: "击破特攻+48%；施放普攻后，自身回复4%生命上限+800生命。",
      note: "加拉赫的低成本击破方案。",
    },
    {
      name: "等价交换",
      superimposition: "S5",
      effect: "装备者回合开始时，随机为1名当前能量百分比低于50%的其他队友恢复16点能量。",
      note: "加拉赫终结技后的100%行动提前有利于更快再次触发回能。",
    },
    {
      name: "一场术后对话",
      superimposition: "S5",
      effect: "能量恢复效率+16%；施放终结技时治疗量+24%。",
      note: "加拉赫终结技本身不治疗，实际主要取16%能量恢复效率。",
    },
  ],
};
