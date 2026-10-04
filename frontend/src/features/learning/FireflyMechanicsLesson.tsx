import { useMemo, useState } from "react";

import {
  BOSS_INVESTMENT_LABELS,
  FIREFLY_CARD_LABELS,
  FIREFLY_CARD_ORDER,
  MODE_LABELS,
  PAIN_POINT_LABELS,
  TEAM_ROUTE_LABELS,
  bossHitCount,
  bossSkillToughness,
  cloudflameToughness,
  oneGoldRecommendation,
  type FireflyLessonController,
  type FireflyOneGoldConfig,
} from "./defaultFireflyLesson";
import "./firefly-lesson.css";

const cardSummaries = {
  "firefly-and-sam": {
    summary:
      "开大后立刻进入高速行动窗口；倒计时速度70，在它到达前尽量塞进更多强化攻击和弱点击破。",
    data: ["240能量", "行动提前100%", "倒计时速度70"],
  },
  "combat-loop": {
    summary:
      "普通战技负责充能，终结技把流萤推入完全燃烧；之后的主循环是连续强化战技。",
    data: ["战技回144能量", "强化战技主削韧30", "完全燃烧速度+60"],
  },
  "super-break": {
    summary:
      "超击破读取削韧值、弱点击破效率、击破特攻、防御区、抗性区和击破易伤，不读取暴击伤害。",
    data: ["30×1.5=45", "300%击破特攻", "自身150%超击破"],
  },
  "eidolons-and-cones": {
    summary:
      "2魂最特殊：强化攻击完成击杀或弱点击破后获得额外回合；1魂与6魂则分别改防御区和削韧/抗性区。",
    data: ["1魂无视15%防御", "2魂额外回合", "6魂+20%火抗穿透"],
  },
  dahlia: {
    summary:
      "大丽花把强化战技主目标从45有效削韧推到80，并允许未破韧阶段也按削韧量产生超击破。",
    data: ["全队+50%弱点击破效率", "固定火削韧+20", "1魂首次削25%最大韧性"],
  },
  fugue: {
    summary:
      "忘归人给首领再加一条40%最大韧性的云火昭；第一次弱点击破后还能继续削，并触发第二次弱点击破。",
    data: ["云火昭=原韧性40%", "无对应弱点可50%效率削韧", "1魂再+50%弱点击破效率"],
  },
  "lingsha-gallagher": {
    summary:
      "灵砂把治疗、解控、副削韧和击破易伤合到一个位置；加拉赫则用更低成本保住战技点与单体削韧。",
    data: ["灵砂终结技群削20", "击破易伤25%", "加拉赫战技点循环宽松"],
  },
  "team-upgrades": {
    summary:
      "队伍可以从同谐主、艾丝妲、加拉赫起步，再按结构需求换成大丽花、忘归人、灵砂；老牌阮·梅体系仍可用。",
    data: ["起步", "低金", "老牌配置", "高配"],
  },
  "damage-ledger": {
    summary:
      "满配提升来自多条独立轨道：削韧、超击破倍率、防御、抗性、击破易伤和循环资源，不能压成一个固定总增伤。",
    data: ["310%超击破倍率示例", "350/310-1≈12.9%", "额外回合是独立资源"],
  },
  "enemy-environment": {
    summary:
      "同一笔投入会随怪物机制改变价值：长韧性看削韧时点，锁韧看未破韧超击破，多波次看额外回合与自动铺状态。",
    data: ["长韧性", "锁韧", "多波次", "高防御/高抗性"],
  },
} as const;

function ToggleRow({
  values,
  current,
  labels,
  onChange,
}: {
  values: readonly string[];
  current: string;
  labels: Record<string, string>;
  onChange: (value: string) => void;
}) {
  return (
    <div className="firefly-choice-row">
      {values.map((value) => (
        <button
          className={`firefly-choice${current === value ? " is-active" : ""}`}
          key={value}
          onClick={() => onChange(value)}
          type="button"
        >
          {labels[value]}
        </button>
      ))}
    </div>
  );
}

function CardDetail({ id, controller }: { id: string; controller: FireflyLessonController }) {
  const [eidolonTab, setEidolonTab] = useState("2魂");
  const [dahliaTab, setDahliaTab] = useState("技能");
  const [fugueTab, setFugueTab] = useState("技能");
  const [sustainTab, setSustainTab] = useState("灵砂");
  const state = controller.state;

  if (id === "firefly-and-sam") {
    return (
      <div className="firefly-card-detail">
        <p>
          流萤是萨姆装甲的驾驶者，来自格拉默铁骑体系。失熵症与有限生命属于官方人物设定；“倒计时逼着你把行动塞进窗口”是玩法结构解读，两者在界面里分开看。
        </p>
        <pre className="firefly-formula">104基础速度 + 60 = 164{"\n"}10000 / 164 ≈ 61行动值{"\n"}10000 / 70 ≈ 143行动值（倒计时）</pre>
        <p>粗略裸轴：0 / 61 / 122 / 143。版本数值按4.2加强后口径。</p>
      </div>
    );
  }

  if (id === "combat-loop") {
    return (
      <div className="firefly-card-detail">
        <pre className="firefly-flow">战技充能{"\n"}↓{"\n"}终结技·完全燃烧{"\n"}↓{"\n"}强化战技 → 强化战技 → 强化战技……</pre>
        <div className="firefly-table-wrap">
          <table className="firefly-table">
            <thead><tr><th>操作</th><th className="number">削韧</th><th>同时发生什么</th></tr></thead>
            <tbody>
              <tr><td>普攻</td><td className="number">10</td><td>回能</td></tr>
              <tr><td>战技</td><td className="number">20</td><td>消耗40%最大生命；最高回复60%最大能量；行动提前25%</td></tr>
              <tr><td>强化普攻</td><td className="number">15</td><td>回复20%最大生命</td></tr>
              <tr><td>强化战技</td><td className="number">30 / 两侧15</td><td>回复25%最大生命；植入火弱点</td></tr>
              <tr><td>终结技</td><td className="number">—</td><td>行动提前100%；速度+60；强化攻击弱点击破效率+50%</td></tr>
            </tbody>
          </table>
        </div>
        <p>240最大能量下，普通战技回复60%最大能量就是144点。</p>
      </div>
    );
  }

  if (id === "super-break") {
    return (
      <div className="firefly-card-detail">
        <pre className="firefly-formula">常规直伤：攻击属性 × 技能倍率 × 暴击 × 增伤{"\n\n"}超击破：削韧值 × 弱点击破效率 × 击破特攻{"\n"}× 超击破倍率 × 防御区 × 抗性区 × 击破易伤</pre>
        <p>强化战技基础削韧30；完全燃烧+50%弱点击破效率后变45。达到300%击破特攻时，流萤自身可获得150%超击破。</p>
        <div className="firefly-note">50%暴击伤害和50%弱点击破效率二选一时，这套超击破结构更需要后者：30×1.5=45，这15点同时改变破韧时点和超击破的削韧基数。</div>
        <ul>
          <li>完全燃烧期间额外+25%击破特攻；完成弱点击破后倒计时延后10%，单次最多3次。</li>
          <li>击破特攻≥150%时获得100%超击破；≥300%时获得150%超击破。</li>
          <li>攻击超过1800后，每多10攻击转0.8%击破特攻；2300攻击示例额外40%。</li>
        </ul>
      </div>
    );
  }

  if (id === "eidolons-and-cones") {
    const tabs = ["1魂", "2魂", "3魂", "4魂", "5魂", "6魂", "光锥"];
    const copy: Record<string, string[]> = {
      "1魂": ["强化战技无视15%防御", "强化战技不消耗战技点", "改变防御区与战技点循环"],
      "2魂": ["强化攻击完成击杀或弱点击破后，立即获得1个额外回合", "每个萨姆自身回合可触发1次，新自身回合重新获得资格", "每个额外回合至少多45主目标有效削韧、一次自身超击破结算和新的触发检查"],
      "3魂": ["战技+2、普攻+1", "主要抬技能直接数值；超击破不读取普通攻击技能倍率"],
      "4魂": ["完全燃烧期间额外+50%效果抵抗", "与天赋抗性叠加后，抗控制能力明显提高"],
      "5魂": ["终结技+2、天赋+2", "提高速度、击破相关增益和生存数值，不新增触发机制"],
      "6魂": ["完全燃烧期间+20%火属性抗性穿透", "强化攻击再+50%弱点击破效率", "主目标削韧示意：30×2.0=60"],
      光锥: ["梦应归于何处·叠影1：+60%击破特攻、专属击破易伤、减速", "记一位星神的陨落·叠影5：免费五星，高攻击可通过额外能力转成击破特攻", "铭记于心的约定·叠影5：直接补击破特攻，低成本替代"],
    };
    return (
      <div className="firefly-card-detail">
        <ToggleRow values={tabs} current={eidolonTab} labels={Object.fromEntries(tabs.map((v) => [v, v]))} onChange={setEidolonTab} />
        <ul>{copy[eidolonTab].map((item) => <li key={item}>{item}</li>)}</ul>
      </div>
    );
  }

  if (id === "dahlia") {
    const tabs = ["技能", "星魂", "光锥"];
    return (
      <div className="firefly-card-detail">
        <pre className="firefly-formula">只有流萤：30×1.5=45{"\n"}大丽花领域：30×(1+50%+50%)=60{"\n"}额外火削韧：60+20=80</pre>
        <ToggleRow values={tabs} current={dahliaTab} labels={Object.fromEntries(tabs.map((v) => [v, v]))} onChange={setDahliaTab} />
        {dahliaTab === "技能" ? (
          <ul><li>领域持续3回合，全队弱点击破效率+50%；未破韧敌人也可按削韧量产生超击破。</li><li>终结技全体削韧，施加败谢，约18%减防，并植入共舞者对应弱点。</li><li>火属性角色攻击植弱点时追加20固定火削韧并给大丽花回能；流萤强化战技可稳定触发。</li><li>每两次追加攻击回复1战技点。</li></ul>
        ) : dahliaTab === "星魂" ? (
          <ul><li>1魂：共舞者额外提高40个百分点；首次攻击额外削25%最大韧性，最低10、最高300。</li><li>2魂：全体敌人全属性抗性-20%；新敌入场自动进入败谢。</li><li>3魂：终结技+2、普攻+1。</li><li>4魂：追加攻击多5段；命中目标受到伤害提高12%。</li><li>5魂：战技+2、天赋+2。</li><li>6魂：共舞者+150%击破特攻；追加攻击后所有共舞者行动提前20%。</li></ul>
        ) : (
          <ul><li>勿忘她的火焰·叠影1：击破特攻、击破伤害乘区、战技点恢复。</li><li>决心如汗珠般闪耀·叠影5：走减防，需要一定效果命中。</li><li>新手任务开始前·叠影5：偏能量循环。</li></ul>
        )}
      </div>
    );
  }

  if (id === "fugue") {
    const tabs = ["技能", "星魂", "光锥"];
    return (
      <div className="firefly-card-detail">
        <div className="firefly-table-wrap"><table className="firefly-table"><thead><tr><th>原韧性</th><th className="number">云火昭</th></tr></thead><tbody>{[300,600,1200,1800].map((value) => <tr key={value}><td>{value}</td><td className="number">{value * 0.4}</td></tr>)}</tbody></table></div>
        <ToggleRow values={tabs} current={fugueTab} labels={Object.fromEntries(tabs.map((v) => [v, v]))} onChange={setFugueTab} />
        {fugueTab === "技能" ? (
          <ul><li>战技“狐祈”提高目标击破特攻；无对应弱点时也可按50%原削韧效率削韧，并可给敌人减防。</li><li>终结技全体削韧且无视弱点属性。</li><li>天赋提供云火昭；攻击已弱点击破的敌人时提供100%超击破。</li><li>敌人被弱点击破后可继续延迟其行动；达到特定击破特攻阈值后，击破可给其他队友提供叠层击破特攻。</li><li>狐祈不必固定给流萤，也可给灵砂等副削韧位。</li></ul>
        ) : fugueTab === "星魂" ? (
          <ul><li>1魂：狐祈目标+50%弱点击破效率。</li><li>2魂：每次敌人被弱点击破时回能；终结技使全队行动提前24%。</li><li>3魂：战技+2、普攻+1。</li><li>4魂：狐祈目标击破伤害提高20%。</li><li>5魂：终结技+2、天赋+2。</li><li>6魂：自身+50%弱点击破效率；狐祈效果扩展全队。</li></ul>
        ) : (
          <ul><li>长路终有归途·叠影1：击破特攻；每次弱点击破使敌人受到的击破伤害提高18%，可叠2层。</li><li>决心如汗珠般闪耀·叠影5：继续叠减防。</li><li>孤独的疗愈·叠影5：击破特攻与能量。</li><li>新手任务开始前·叠影5：偏能量循环。</li></ul>
        )}
      </div>
    );
  }

  if (id === "lingsha-gallagher") {
    return (
      <div className="firefly-card-detail">
        <ToggleRow values={["灵砂", "加拉赫"]} current={sustainTab} labels={{ 灵砂: "灵砂", 加拉赫: "加拉赫" }} onChange={setSustainTab} />
        {sustainTab === "灵砂" ? (
          <>
            <ul>
              <li>终结技：全体削韧20、全队治疗、浮元行动提前100%、敌人受到的击破伤害提高25%。</li>
              <li>浮元：独立行动 → 群体火削韧 → 追加单体削韧 → 治疗 → 解控。</li>
              <li>1魂：自身弱点击破效率+50%；敌人被弱点击破后防御-20%。</li>
              <li>2魂：终结技后全队击破特攻+40%，持续3回合。</li>
              <li>3魂：终结技+2、天赋+2。</li>
              <li>4魂：浮元行动时额外治疗当前生命值最低的角色。</li>
              <li>5魂：战技+2、普攻+1。</li>
              <li>6魂：浮元在场时全体敌人全属性抗性-20%；浮元每次行动增加4段额外攻击与对应削韧。</li>
            </ul>
            <ul>
              <li>唯有香如故·叠影1：补击破特攻与团队易伤。</li>
              <li>等价交换·叠影5：给低能量队友恢复能量。</li>
              <li>一场术后对话·叠影5：提高能量循环。</li>
              <li>何物为真·叠影5：偏灵砂自身击破/超击破输出。</li>
            </ul>
          </>
        ) : (
          <ul><li>强化普攻提供高单体削韧。</li><li>给敌人施加受到的击破伤害提高。</li><li>战技点循环更宽松。</li><li>成本更低，但会失去灵砂的群体削韧、解控、浮元与更高的团队易伤上限。</li></ul>
        )}
      </div>
    );
  }

  if (id === "team-upgrades") {
    const routes = ["starter", "dahlia", "classic", "premium"] as const;
    const routeLabels = { ...TEAM_ROUTE_LABELS, dahlia: "低金 · 加入大丽花" };
    const routeCopy = {
      starter: ["流萤 / 同谐主 / 艾丝妲 / 加拉赫", "同谐主提供超击破与击破特攻；艾丝妲给速度、攻击与火削韧；加拉赫兼顾治疗、战技点和击破易伤。"],
      dahlia: ["流萤 / 大丽花 / 同谐主 / 加拉赫", "未破韧阶段也能超击破；全队+50%弱点击破效率；再增加减防、固定削韧与循环支持。"],
      classic: ["流萤 / 阮·梅 / 同谐主 / 加拉赫", "继续依赖弱点击破效率、抗性穿透、速度/击破特攻与延长弱点击破窗口；仍可用，不把现代高配写成唯一答案。"],
      premium: ["流萤 / 大丽花 / 忘归人 / 灵砂", "流萤主削韧和超击破；大丽花提前出伤与提效率；忘归人提供第二韧性和再次击破；灵砂负责生存、副削韧和击破易伤。"],
    } as const;
    return (
      <div className="firefly-card-detail">
        <ToggleRow values={routes} current={state.teamRoute} labels={routeLabels} onChange={(value) => controller.update({ teamRoute: value as typeof state.teamRoute })} />
        <h4>{routeCopy[state.teamRoute][0]}</h4>
        <p>{routeCopy[state.teamRoute][1]}</p>
      </div>
    );
  }

  if (id === "damage-ledger") {
    return (
      <div className="firefly-card-detail">
        <pre className="firefly-formula">流萤自身 150%{"\n"}+ 忘归人 100%{"\n"}+ 大丽花0魂 60%{"\n"}= 310%超击破倍率{"\n\n"}大丽花1魂：350 / 310 - 1 ≈ 12.9%</pre>
        <p>这12.9%只属于超击破倍率这一层，不含大丽花1魂的最大韧性固定削韧和行动时点变化。</p>
        <ul><li>防御区：大丽花减防、忘归人减防、灵砂1魂减防、流萤1魂无视防御等。</li><li>抗性区：大丽花2魂、流萤6魂、灵砂6魂。</li><li>击破易伤：流萤专武、忘归人专武、灵砂终结技/专武、大丽花专武。</li><li>循环资源：战技点、能量、行动提前、额外回合。</li></ul>
      </div>
    );
  }

  const modes = ["memory", "apocalyptic", "fiction", "arbitration"] as const;
  const modeCopy = {
    memory: "轮次、稳定轴和首领阶段更重要。",
    apocalyptic: "首领机制、韧性和弱点击破事件价值更高。",
    fiction: "大量刷新让群攻、击杀链和额外回合更容易升值。",
    arbitration: "当期首领机制和高压生存条件影响更大。",
  };
  return (
    <div className="firefly-card-detail">
      <div className="firefly-table-wrap"><table className="firefly-table"><thead><tr><th>怪物环境</th><th>更容易升值的投入</th></tr></thead><tbody><tr><td>超长韧性</td><td>大丽花1魂、忘归人1魂、流萤6魂</td></tr><tr><td>锁韧</td><td>大丽花0魂</td></tr><tr><td>反复恢复韧性</td><td>流萤2魂、忘归人</td></tr><tr><td>多波次</td><td>流萤2魂、大丽花2魂</td></tr><tr><td>高防御</td><td>流萤1魂、灵砂1魂、减防来源</td></tr><tr><td>高抗性</td><td>大丽花2魂、流萤6魂、灵砂6魂</td></tr><tr><td>控制/高生存压力</td><td>灵砂</td></tr><tr><td>低生存压力竞速</td><td>减少生存投入，换更多输出/行动支持</td></tr></tbody></table></div>
      <ToggleRow values={modes} current={state.mode} labels={MODE_LABELS} onChange={(value) => controller.update({ mode: value as typeof state.mode })} />
      <p>{modeCopy[state.mode]}</p>
      <div className="firefly-note">长期机制与当前版本环境分层显示；这里展示的是机制如何改变投资价值，不把当期评级写成长期事实。</div>
    </div>
  );
}

function BossExperiment({ controller }: { controller: FireflyLessonController }) {
  const { state } = controller;
  const toughnessOptions = [300, 600, 1200, "locked"] as const;
  const investmentOptions = ["firefly-0", "dahlia-0", "dahlia-1", "fugue-1", "firefly-6"] as const;
  const hitCount = bossHitCount(state.bossToughness, state.investment);
  const cloudflame = cloudflameToughness(state.bossToughness);
  const hasFugue = state.investment === "fugue-1" || state.investment === "firefly-6";

  return (
    <section className="firefly-interactive" id="firefly-boss-experiment">
      <header><h3>换一条韧性，再算一次</h3><p>只统计流萤主目标削韧；不把三名队友全部攻击、转阶段和生命伤害塞进同一个数字。</p></header>
      <div className="firefly-control-block"><span className="firefly-control-label">首领状态</span><div className="firefly-choice-row">{toughnessOptions.map((value) => <button className={`firefly-choice${state.bossToughness === value ? " is-active" : ""}`} key={String(value)} onClick={() => controller.update({ bossToughness: value })} type="button">{value === "locked" ? "锁韧" : `${value}韧性`}</button>)}</div></div>
      <div className="firefly-control-block"><span className="firefly-control-label">队伍投入</span><ToggleRow values={investmentOptions} current={state.investment} labels={BOSS_INVESTMENT_LABELS} onChange={(value) => controller.update({ investment: value as typeof state.investment })} /></div>
      <div className="firefly-result">
        {hitCount === null ? <><strong>锁韧期间不报“需要几次攻击”</strong><p>弱点击破×；流萤2魂的“击破”触发×；大丽花领域允许超击破✓；若实际击杀，2魂“击杀”触发仍可✓；击破延长完全燃烧×。</p></> : <><strong>{hitCount}次强化战技</strong><p>当前每次教学削韧值：{bossSkillToughness(state.investment)}。{state.investment === "dahlia-1" || state.investment === "fugue-1" || state.investment === "firefly-6" ? "其中大丽花1魂首次再按25%最大韧性削减，最高300。" : ""}</p><div className="firefly-toughness-bars"><div className="firefly-bar"><span style={{ width: "100%" }} /></div>{hasFugue && cloudflame ? <><small>第一次击破后还有云火昭：{cloudflame}韧性</small><div className="firefly-bar cloudflame"><span style={{ width: "40%" }} /></div></> : null}</div></>}
      </div>
      <button className="firefly-link-button" onClick={() => controller.update({ showBossMath: !state.showBossMath })} type="button">{state.showBossMath ? "收起计算" : "看怎么算的"}</button>
      {state.showBossMath ? <pre className="firefly-formula">流萤：30×1.5 = 45{"\n"}+大丽花0魂：30×2.0 + 20 = 80{"\n"}+忘归人1魂：30×2.5 + 20 = 95{"\n"}+流萤6魂：30×3.0 + 20 = 110{"\n"}大丽花1魂首次：min(25%×最大韧性, 300)</pre> : null}
    </section>
  );
}

function updateOneGold(
  controller: FireflyLessonController,
  patch: Partial<FireflyOneGoldConfig>,
) {
  controller.update({ oneGold: { ...controller.state.oneGold, ...patch } });
}

function OneGoldDecision({ controller }: { controller: FireflyLessonController }) {
  const { state } = controller;
  const recommendation = useMemo(() => oneGoldRecommendation(state), [state]);
  const painPoints = ["break-slow", "locked-damage", "skill-points", "single-hit", "actions", "survival"] as const;
  const currentBossHits = bossHitCount(state.bossToughness, state.investment);
  const bossStateText = state.bossToughness === "locked"
    ? `锁韧 / ${BOSS_INVESTMENT_LABELS[state.investment]} / 不比较攻击次数`
    : `${state.bossToughness}韧性 / ${BOSS_INVESTMENT_LABELS[state.investment]} / ${currentBossHits}次强化战技`;
  const recommendationSummary = recommendation.key === "C"
    ? state.bossToughness === "locked"
      ? "当前首领处于锁韧状态，不用攻击次数评价1魂；先看大丽花0魂的未破韧超击破，等韧性恢复后再比较1魂固定削韧。"
      : `${state.bossToughness}韧性简化模型从${bossHitCount(state.bossToughness, "dahlia-0")}发缩到${bossHitCount(state.bossToughness, "dahlia-1")}发，首次额外削韧按25%最大韧性计算、最高300。`
    : recommendation.summary;

  return (
    <section className="firefly-interactive" id="firefly-one-gold">
      <header><h3>手里只有一金</h3><p>答案从当前配置、痛点、怪物环境和首领实验状态共同推导，不输出固定抽取榜。</p></header>
      <div className="firefly-config-summary">流萤{state.oneGold.fireflyEidolon}魂·{state.oneGold.fireflyCone === "signature" ? "专武" : state.oneGold.fireflyCone === "four-star" ? "四星光锥" : "免费光锥"} / {state.oneGold.dahliaEidolon === null ? "无大丽花" : `大丽花${state.oneGold.dahliaEidolon}魂`} / {state.oneGold.fugueEidolon === null ? "无忘归人" : `忘归人${state.oneGold.fugueEidolon}魂`} / {state.oneGold.sustain === "gallagher" ? "加拉赫" : state.oneGold.sustain === "lingsha-0" ? "灵砂0魂" : state.oneGold.sustain === "lingsha-1" ? "灵砂1魂+" : "无生存位"}</div>
      <div className="firefly-note">当前首领实验：{bossStateText}</div>
      <details><summary>编辑配置</summary><div className="firefly-config-grid">
        <label className="firefly-field">流萤星魂<select value={state.oneGold.fireflyEidolon} onChange={(event) => updateOneGold(controller, { fireflyEidolon: Number(event.target.value) })}>{[0,1,2,3,4,5,6].map((value) => <option key={value} value={value}>{value}魂</option>)}</select></label>
        <label className="firefly-field">流萤光锥<select value={state.oneGold.fireflyCone} onChange={(event) => updateOneGold(controller, { fireflyCone: event.target.value as FireflyOneGoldConfig["fireflyCone"] })}><option value="free">免费五星</option><option value="four-star">四星</option><option value="signature">专武</option></select></label>
        <label className="firefly-field">大丽花<select value={state.oneGold.dahliaEidolon ?? -1} onChange={(event) => updateOneGold(controller, { dahliaEidolon: Number(event.target.value) < 0 ? null : Number(event.target.value) })}><option value={-1}>未拥有</option>{[0,1,2,3,4,5,6].map((value) => <option key={value} value={value}>{value}魂</option>)}</select></label>
        <label className="firefly-field">忘归人<select value={state.oneGold.fugueEidolon ?? -1} onChange={(event) => updateOneGold(controller, { fugueEidolon: Number(event.target.value) < 0 ? null : Number(event.target.value) })}><option value={-1}>未拥有</option>{[0,1,2,3,4,5,6].map((value) => <option key={value} value={value}>{value}魂</option>)}</select></label>
        <label className="firefly-field">生存位<select value={state.oneGold.sustain} onChange={(event) => updateOneGold(controller, { sustain: event.target.value as FireflyOneGoldConfig["sustain"] })}><option value="gallagher">加拉赫</option><option value="lingsha-0">灵砂0魂</option><option value="lingsha-1">灵砂1魂+</option><option value="none">无生存</option></select></label>
        <label className="firefly-field">怪物环境<select value={state.environment} onChange={(event) => controller.update({ environment: event.target.value as typeof state.environment })}><option value="general">一般</option><option value="high-resistance">高抗性</option><option value="multi-wave">多波次</option></select></label>
      </div></details>
      <div className="firefly-control-block"><span className="firefly-control-label">你现在最难受的是</span><ToggleRow values={painPoints} current={state.painPoint} labels={PAIN_POINT_LABELS} onChange={(value) => controller.update({ painPoint: value as typeof state.painPoint })} /></div>
      <div className="firefly-recommendation"><strong>{recommendation.key} · {recommendation.title}</strong><p>{recommendationSummary}</p><ul>{recommendation.details.map((detail) => <li key={detail}>{detail}</li>)}</ul></div>
    </section>
  );
}

export function FireflyDefaultLesson({ controller }: { controller: FireflyLessonController }) {
  const { state } = controller;

  return (
    <div className="firefly-lesson-panel">
      <div className="firefly-lesson-shell">
        <header className="firefly-lesson-hero">
          <h2>流萤超击破体系</h2>
          <p>从按钮、削韧和超击破一路看到配队、怪物环境与“一金怎么花”。默认假设此前不熟悉流萤或超击破。</p>
          <div className="firefly-version-note">数据按4.2加强后的流萤。若外部资料仍写旧版35%/50%超击破倍率或旧2魂冷却，不采用。</div>
        </header>

        <nav className="firefly-directory" aria-label="流萤课程目录">
          {FIREFLY_CARD_ORDER.map((id) => <button className={`firefly-chip${state.activeCardId === id ? " is-active" : ""}`} key={id} onClick={() => controller.update({ activeCardId: id })} type="button">{FIREFLY_CARD_LABELS[id]}</button>)}
          <a className="firefly-chip" href="#firefly-boss-experiment">首领实验</a>
          <a className="firefly-chip" href="#firefly-one-gold">一金怎么花</a>
        </nav>

        <div className="firefly-card-list">
          {FIREFLY_CARD_ORDER.map((id, index) => {
            const expanded = state.expandedCardId === id;
            const content = cardSummaries[id];
            return (
              <article className={`firefly-card${state.activeCardId === id ? " is-active" : ""}`} key={id} onMouseEnter={() => controller.update({ activeCardId: id })}>
                <div className="firefly-card-header"><div><span className="firefly-card-index">{String(index + 1).padStart(2, "0")}</span><h3>{FIREFLY_CARD_LABELS[id]}</h3></div><button aria-expanded={expanded} className="firefly-expand" onClick={() => controller.update({ activeCardId: id, expandedCardId: expanded ? null : id })} type="button">{expanded ? "收起" : "展开"}</button></div>
                <p className="firefly-card-summary">{content.summary}</p>
                <div className="firefly-data-row">{content.data.map((item) => <span className="firefly-data-pill" key={item}>{item}</span>)}</div>
                {expanded ? <CardDetail id={id} controller={controller} /> : null}
              </article>
            );
          })}
        </div>

        <div className="firefly-interactions"><BossExperiment controller={controller} /><OneGoldDecision controller={controller} /></div>
        <footer className="firefly-footer">首领实验是教学简化模型；抽取建议由当前配置、痛点和怪物状态共同决定，不写入长期学习事实。</footer>
      </div>
    </div>
  );
}
