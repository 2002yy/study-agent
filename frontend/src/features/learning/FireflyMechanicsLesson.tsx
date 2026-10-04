import { useMemo, useState, type ReactNode } from "react";

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
    summary: "开大后立刻进入高速行动窗口；倒计时速度70，在它到达前尽量塞进更多强化攻击和弱点击破。",
    data: ["240能量", "行动提前100%", "倒计时速度70"],
  },
  "combat-loop": {
    summary: "普通战技负责充能，终结技把流萤推入完全燃烧；之后的主循环是连续强化战技。",
    data: ["战技回144能量", "强化战技主削韧30", "完全燃烧速度+60"],
  },
  "super-break": {
    summary: "超击破读取削韧值、弱点击破效率、击破特攻、防御区、抗性区和击破易伤，不读取暴击伤害。",
    data: ["30×1.5=45", "300%击破特攻", "自身150%超击破"],
  },
  "eidolons-and-cones": {
    summary: "2魂最特殊：强化攻击完成击杀或弱点击破后获得额外回合；1魂与6魂则分别改防御区和削韧/抗性区。",
    data: ["1魂无视15%防御", "2魂额外回合", "6魂+20%火抗穿透"],
  },
  dahlia: {
    summary: "大丽花把强化战技主目标从45有效削韧推到80，并允许未破韧阶段也按削韧量产生超击破。",
    data: ["全队+50%弱点击破效率", "固定火削韧+20", "1魂首次削25%最大韧性"],
  },
  fugue: {
    summary: "忘归人给首领再加一条40%最大韧性的云火昭；第一次弱点击破后还能继续削，并触发第二次弱点击破。",
    data: ["云火昭=原韧性40%", "无对应弱点可50%效率削韧", "1魂再+50%弱点击破效率"],
  },
  "lingsha-gallagher": {
    summary: "灵砂把治疗、解控、副削韧和击破易伤合到一个位置；加拉赫则用更低成本保住战技点与单体削韧。",
    data: ["灵砂终结技群削20", "击破易伤25%", "加拉赫战技点循环宽松"],
  },
  "team-upgrades": {
    summary: "队伍可以从同谐主、艾丝妲、加拉赫起步，再按结构需求换成大丽花、忘归人、灵砂；老牌阮·梅体系仍可用。",
    data: ["起步", "低金", "老牌配置", "高配"],
  },
  "damage-ledger": {
    summary: "满配提升来自多条独立轨道：削韧、超击破倍率、防御、抗性、击破易伤和循环资源，不能压成一个固定总增伤。",
    data: ["310%超击破倍率示例", "350/310-1≈12.9%", "额外回合是独立资源"],
  },
  "enemy-environment": {
    summary: "同一笔投入会随怪物机制改变价值：长韧性看削韧时点，锁韧看未破韧超击破，多波次看额外回合与自动铺状态。",
    data: ["长韧性", "锁韧", "多波次", "高防御/高抗性"],
  },
} as const;

function ToggleRow({ values, current, labels, onChange }: {
  values: readonly string[];
  current: string;
  labels: Record<string, string>;
  onChange: (value: string) => void;
}) {
  return (
    <div className="firefly-choice-row">
      {values.map((value) => (
        <button className={`firefly-choice${current === value ? " is-active" : ""}`} key={value} onClick={() => onChange(value)} type="button">
          {labels[value]}
        </button>
      ))}
    </div>
  );
}

function DetailSection({ title, children }: { title: string; children: ReactNode }) {
  return <section><h4>{title}</h4>{children}</section>;
}

const fireflyEidolonCopy: Record<string, { points: string[]; meaning: string; scene: string }> = {
  "1魂": {
    points: ["强化战技无视15%防御", "强化战技不消耗战技点"],
    meaning: "一条落在防御区，一条落在循环资源。它不会直接多出一次行动，但高频强化战技对全队战技点的压力会明显降低。",
    scene: "战技点紧时，“省点”会直接改善循环；队伍已有多种减防时，15%无视防御则需要和现有防御区一起看。",
  },
  "2魂": {
    points: ["强化普攻/强化战技完成击杀或弱点击破后，立即获得1个额外回合", "每个萨姆自身回合只触发1次；新的自身回合重新获得资格"],
    meaning: "它买的是一次完整行动。只算完全燃烧自带+50%弱点击破效率，额外回合至少再提供45主目标有效削韧、一次自身超击破结算、新的击杀/击破检查，以及新的完全燃烧延时机会。",
    scene: "杂兵、多波次、反复恢复韧性的首领更容易连续触发；长时间锁韧、又杀不掉目标时，击破分支会失效，因此2魂的收益会明显波动。",
  },
  "3魂": {
    points: ["战技+2、普攻+1"],
    meaning: "主要抬技能直接数值。超击破本身不读取普通攻击技能倍率，因此它不会像2魂那样改行动结构。",
    scene: "伤害已经高度集中在超击破时，3魂更接近数值补强，玩法结构基本不变。",
  },
  "4魂": {
    points: ["完全燃烧期间额外+50%效果抵抗"],
    meaning: "它处理的是爆发窗口被控制打断的风险。短窗口里少一个回合，损失可能比少一条普通伤害乘区更大。",
    scene: "控制频繁的高压环境会升值；纯木桩竞速里，它的价值基本不会出现在伤害表上。",
  },
  "5魂": {
    points: ["终结技+2、天赋+2"],
    meaning: "提高速度、击破相关增益和生存数值，但没有新增触发机制。",
    scene: "它把既有结构推高，但不会改变“什么时候能多打一回合”这种战斗逻辑。",
  },
  "6魂": {
    points: ["完全燃烧期间+20%火属性抗性穿透", "强化攻击再+50%弱点击破效率"],
    meaning: "一条进抗性区，一条同时影响破韧时点和超击破削韧基数。主目标削韧从30×1.5=45变成30×2.0=60。",
    scene: "长韧性与高火抗环境会同时放大两条收益；低韧性杂兵上，额外削韧可能因为提前溢出而打折。",
  },
  光锥: {
    points: ["梦应归于何处·叠影1：+60%击破特攻、专属击破易伤、减速", "记一位星神的陨落·叠影5：免费五星，高攻击可经额外能力转成击破特攻", "铭记于心的约定·叠影5：直接补击破特攻，低成本替代"],
    meaning: "专武更偏“每次打得更重”；星魂里则有省战技点、额外回合、抗性穿透等完全不同的资源。",
    scene: "专武、1魂、2魂对应的痛点不同：单次伤害、战技点、行动次数、破韧速度不能合成一条固定抽取顺序。",
  },
};

function CardDetail({ id, controller }: { id: string; controller: FireflyLessonController }) {
  const [eidolonTab, setEidolonTab] = useState("2魂");
  const [dahliaTab, setDahliaTab] = useState("技能");
  const [fugueTab, setFugueTab] = useState("技能");
  const [sustainTab, setSustainTab] = useState("灵砂");
  const state = controller.state;

  if (id === "firefly-and-sam") {
    return (
      <div className="firefly-card-detail">
        <DetailSection title="角色设定 / 玩法结构">
          <p>官方设定里，流萤是萨姆装甲的驾驶者，来自格拉默铁骑体系；失熵症、有限生命、星核猎手身份与匹诺康尼经历属于人物线。玩法上的“完全燃烧”则是一个明确的倒计时爆发窗口。</p>
          <div className="firefly-note">“有限生命对应战斗倒计时”属于玩法设计解读，不当作官方剧情事实。</div>
        </DetailSection>
        <DetailSection title="完全燃烧的行动窗口">
          <pre className="firefly-formula">104基础速度 + 60 = 164{"\n"}10000 / 164 ≈ 61行动值{"\n"}10000 / 70 ≈ 143行动值（倒计时）</pre>
          <p>裸轴大约是0 / 61 / 122 / 143。不开额外加速时，窗口天然只容纳有限次行动；速度、行动提前、2魂额外回合和击破后的倒计时延长，都会直接影响这个窗口里能塞进几次强化攻击。</p>
        </DetailSection>
        <DetailSection title="角色背景">
          <ul>
            <li>格拉默铁骑说明“萨姆”首先是一套战争兵器体系，并非独立于流萤的第二人格。</li>
            <li>失熵症贯穿她关于时间、选择和“活着”的表达。</li>
            <li>星核猎手与匹诺康尼人物线决定她在剧情里的关系位置；剧情设定与战斗数值分开呈现。</li>
          </ul>
        </DetailSection>
      </div>
    );
  }

  if (id === "combat-loop") {
    return (
      <div className="firefly-card-detail">
        <pre className="firefly-flow">战技充能{"\n"}↓{"\n"}终结技·完全燃烧{"\n"}↓{"\n"}强化战技 → 强化战技 → 强化战技……</pre>
        <div className="firefly-table-wrap"><table className="firefly-table"><thead><tr><th>操作</th><th className="number">削韧</th><th>同时发生什么</th></tr></thead><tbody>
          <tr><td>普攻</td><td className="number">10</td><td>回能；主要用于非常规循环</td></tr>
          <tr><td>战技</td><td className="number">20</td><td>消耗40%最大生命；最高回复60%最大能量；行动提前25%</td></tr>
          <tr><td>强化普攻</td><td className="number">15</td><td>回复20%最大生命</td></tr>
          <tr><td>强化战技</td><td className="number">30 / 两侧15</td><td>回复25%最大生命；植入火弱点</td></tr>
          <tr><td>终结技</td><td className="number">—</td><td>行动提前100%；速度+60；强化攻击弱点击破效率+50%</td></tr>
        </tbody></table></div>
        <DetailSection title="充能段 / 完全燃烧">
          <p>240最大能量下，普通战技回复60%就是144点。开大前主要处理回能；开大后资源重点切到强化战技、弱点击破和超击破，直到倒计时结束。</p>
        </DetailSection>
        <DetailSection title="强化普攻的位置">
          <p>强化普攻能回血，但基础削韧15低于强化战技主目标30，也没有两侧削韧。战技点或目标结构没有额外限制时，强化战技通常占据主循环。</p>
        </DetailSection>
        <DetailSection title="生命与抗打断">
          <ul>
            <li>普通战技主动压低生命换能量；强化攻击再把生命拉回来。</li>
            <li>天赋的减伤与效果抵抗降低短爆发窗口被打断的概率。</li>
            <li>秘技逐波植入火弱点，新波次也能较快回到流萤自己的削韧节奏。</li>
          </ul>
        </DetailSection>
      </div>
    );
  }

  if (id === "super-break") {
    return (
      <div className="firefly-card-detail">
        <pre className="firefly-formula">常规直伤：攻击属性 × 技能倍率 × 暴击 × 增伤{"\n\n"}超击破：削韧值 × 弱点击破效率 × 击破特攻{"\n"}× 超击破倍率 × 防御区 × 抗性区 × 击破易伤</pre>
        <DetailSection title="一次强化战技的削韧">
          <p>强化战技基础主削韧30；完全燃烧+50%弱点击破效率后变成45。这个45既让韧性条掉得更快，也进入超击破的削韧基数，因此弱点击破效率同时改变破韧时点和单次超击破。</p>
          <div className="firefly-note">50%暴击伤害不进入超击破结算；50%弱点击破效率则把30主削韧推到45。</div>
        </DetailSection>
        <DetailSection title="击破特攻的两条阈值">
          <ul>
            <li>完全燃烧期间额外+25%击破特攻。</li>
            <li>击破特攻≥150%时获得100%超击破；≥300%时获得150%超击破。</li>
            <li>攻击超过1800后，每多10攻击转0.8%击破特攻；2300攻击示例额外40%。</li>
          </ul>
          <p>攻击超过阈值后仍能经额外能力转换为击破特攻；双暴则不进入超击破公式。</p>
        </DetailSection>
        <DetailSection title="破韧前 / 破韧后">
          <p>普通超击破队通常先清空韧性，再进入超击破阶段。大丽花领域让未破韧阶段也能按削韧量产生超击破；忘归人则在第一次击破后加入云火昭，继续制造第二次弱点击破事件。</p>
        </DetailSection>
      </div>
    );
  }

  if (id === "eidolons-and-cones") {
    const tabs = ["1魂", "2魂", "3魂", "4魂", "5魂", "6魂", "光锥"];
    const copy = fireflyEidolonCopy[eidolonTab];
    return (
      <div className="firefly-card-detail">
        <ToggleRow values={tabs} current={eidolonTab} labels={Object.fromEntries(tabs.map((v) => [v, v]))} onChange={setEidolonTab} />
        <DetailSection title="机制"><ul>{copy.points.map((item) => <li key={item}>{item}</li>)}</ul></DetailSection>
        <DetailSection title="影响的资源"><p>{copy.meaning}</p></DetailSection>
        <DetailSection title="环境差异"><p>{copy.scene}</p></DetailSection>
      </div>
    );
  }

  if (id === "dahlia") {
    const tabs = ["技能", "星魂", "光锥"];
    return (
      <div className="firefly-card-detail">
        <pre className="firefly-formula">只有流萤：30×1.5=45{"\n"}大丽花领域：30×(1+50%+50%)=60{"\n"}额外火削韧：60+20=80</pre>
        <p>大丽花0魂同时改变削韧速度、未破韧阶段的超击破，以及队伍的减防/战技点/能量循环。她带来的变化不止一条增伤乘区。</p>
        <ToggleRow values={tabs} current={dahliaTab} labels={Object.fromEntries(tabs.map((v) => [v, v]))} onChange={setDahliaTab} />
        {dahliaTab === "技能" ? <>
          <DetailSection title="技能链"><ul><li>普攻偏战技点正循环。</li><li>战技开启领域，持续3回合；全队弱点击破效率+50%，未破韧敌人也能按削韧量产生超击破。</li><li>终结技全体削韧，施加败谢，约18%减防，并植入共舞者对应弱点。</li><li>天赋围绕共舞者与追加攻击；每两次追加攻击回复1战技点。</li><li>火属性角色通过攻击植弱点时，追加20固定火削韧并给大丽花回能；流萤强化战技能稳定触发。</li></ul></DetailSection>
          <DetailSection title="与流萤的联动"><p>流萤自己会植火弱，因此固定20火削韧可以稳定触发；领域又把完全燃烧自带的50%弱点击破效率继续叠高。一次强化战技由45提升到80，同时未破韧阶段也开始产生超击破。</p></DetailSection>
        </> : dahliaTab === "星魂" ? <>
          <div className="firefly-table-wrap"><table className="firefly-table"><thead><tr><th>最大韧性</th><th className="number">1魂首次额外削韧</th></tr></thead><tbody><tr><td>300</td><td className="number">75</td></tr><tr><td>600</td><td className="number">150</td></tr><tr><td>1200</td><td className="number">300</td></tr><tr><td>1800</td><td className="number">300（封顶）</td></tr></tbody></table></div>
          <ul><li>1魂：天赋超击破扩展全队；共舞者额外提高40个百分点；首次攻击额外削25%最大韧性，最低10、最高300。</li><li>2魂：全体敌人全属性抗性-20%；新敌入场自动进入败谢。</li><li>3魂：终结技+2、普攻+1。</li><li>4魂：追加攻击多5段；命中目标受到伤害提高12%。</li><li>5魂：战技+2、天赋+2。</li><li>6魂：共舞者+150%击破特攻；追加攻击后所有共舞者行动提前20%。</li></ul>
          <div className="firefly-note">1魂偏削韧时点与共舞者超击破；2魂偏抗性区与多波次自动铺状态。</div>
        </> : <>
          <ul><li>勿忘她的火焰·叠影1：击破特攻、击破伤害乘区、战技点恢复。</li><li>决心如汗珠般闪耀·叠影5：走减防，需要一定效果命中。</li><li>新手任务开始前·叠影5：偏能量循环。</li></ul>
          <p>专武偏单次击破伤害与战技点循环；1魂偏破韧时间轴与共舞者超击破。</p>
        </>}
      </div>
    );
  }

  if (id === "fugue") {
    const tabs = ["技能", "星魂", "光锥"];
    return (
      <div className="firefly-card-detail">
        <div className="firefly-table-wrap"><table className="firefly-table"><thead><tr><th>原韧性</th><th className="number">云火昭</th></tr></thead><tbody>{[300,600,1200,1800].map((value) => <tr key={value}><td>{value}</td><td className="number">{value * 0.4}</td></tr>)}</tbody></table></div>
        <p>原韧性清空后继续削云火昭；云火昭归零时再发生一次弱点击破。多出的不只是40%韧性，还包括一次新的击破事件：2魂、击破回能、击破易伤叠层等机制都有机会再次触发。</p>
        <ToggleRow values={tabs} current={fugueTab} labels={Object.fromEntries(tabs.map((v) => [v, v]))} onChange={setFugueTab} />
        {fugueTab === "技能" ? <>
          <ul><li>狐祈：提高目标击破特攻；无对应弱点时也可按50%原削韧效率削韧；该队友攻击时可给敌人减防。</li><li>终结技：全体削韧且无视弱点属性。</li><li>天赋：提供云火昭；攻击已弱点击破敌人时提供100%超击破。</li><li>敌人被弱点击破后可继续延迟行动；达到特定击破特攻阈值后，击破可给其他队友提供叠层击破特攻。</li></ul>
          <DetailSection title="狐祈的目标选择"><p>流萤已经能植火弱并承担主削韧时，狐祈也可以给灵砂等副削韧位，让更多队友参与拆韧性。</p></DetailSection>
        </> : fugueTab === "星魂" ? <>
          <ul><li>1魂：狐祈目标+50%弱点击破效率。</li><li>2魂：每次敌人被弱点击破时回能；终结技使全队行动提前24%。</li><li>3魂：战技+2、普攻+1。</li><li>4魂：狐祈目标击破伤害提高20%。</li><li>5魂：终结技+2、天赋+2。</li><li>6魂：自身+50%弱点击破效率；狐祈效果扩展全队。</li></ul>
          <p>1魂直接压缩拆韧性时间；2魂把再次击破继续转成能量和整队行动资源。长韧性、第二韧性和反复击破环境都会放大这两项收益。</p>
        </> : <>
          <ul><li>长路终有归途·叠影1：击破特攻；每次弱点击破使敌人受到的击破伤害提高18%，可叠2层。</li><li>决心如汗珠般闪耀·叠影5：继续叠减防。</li><li>孤独的疗愈·叠影5：击破特攻与能量。</li><li>新手任务开始前·叠影5：偏能量循环；2魂后终结技还承担全队24%行动提前。</li></ul>
          <p>云火昭让同一个敌人更容易连续发生两次弱点击破，因此专武的两层击破易伤也更容易在同一目标上建立。</p>
        </>}
      </div>
    );
  }

  if (id === "lingsha-gallagher") {
    return (
      <div className="firefly-card-detail">
        <ToggleRow values={["灵砂", "加拉赫"]} current={sustainTab} labels={{ 灵砂: "灵砂", 加拉赫: "加拉赫" }} onChange={setSustainTab} />
        {sustainTab === "灵砂" ? <>
          <DetailSection title="终结技与浮元"><ul><li>终结技：全体削韧20、全队治疗、浮元行动提前100%、敌人受到的击破伤害提高25%。</li><li>浮元：独立行动 → 群体火削韧 → 追加单体削韧 → 治疗 → 解控。</li></ul></DetailSection>
          <DetailSection title="星魂"><ul><li>1魂：自身弱点击破效率+50%；敌人被弱点击破后防御-20%。</li><li>2魂：终结技后全队击破特攻+40%，持续3回合。</li><li>3魂：终结技+2、天赋+2。</li><li>4魂：浮元行动时额外治疗当前生命最低角色。</li><li>5魂：战技+2、普攻+1。</li><li>6魂：浮元在场时全体敌人全属性抗性-20%；每次行动增加4段额外攻击与对应削韧。</li></ul></DetailSection>
          <DetailSection title="光锥"><ul><li>唯有香如故·叠影1：补击破特攻与团队易伤。</li><li>等价交换·叠影5：给低能量队友恢复能量。</li><li>一场术后对话·叠影5：提高能量循环。</li><li>何物为真·叠影5：偏自身击破/超击破输出。</li></ul></DetailSection>
          <p>控制、高生存压力、群体韧性同时存在时，灵砂一个位置会同时贡献治疗、解控、削韧和击破易伤；只比较治疗量会漏掉大半差异。</p>
        </> : <>
          <DetailSection title="加拉赫"><ul><li>强化普攻提供高单体削韧。</li><li>给敌人施加受到的击破伤害提高。</li><li>战技点循环更宽松，四星成本更低。</li><li>生存位依然能参与削韧。</li></ul></DetailSection>
          <DetailSection title="切换到灵砂"><p>群体削韧、浮元独立行动、解控和团队击破易伤上限都会提高；代价是获取成本上升，部分队伍里也更需要管理她的行动和战技点。</p></DetailSection>
          <div className="firefly-note">两者差异不止治疗量：低金队更看成本、战技点和单体拆韧；高压/群体环境更容易体现灵砂的复合价值。</div>
        </>}
      </div>
    );
  }

  if (id === "team-upgrades") {
    const routes = ["starter", "dahlia", "classic", "premium"] as const;
    const routeLabels = { ...TEAM_ROUTE_LABELS, dahlia: "低金 · 加入大丽花" };
    const routeCopy = {
      starter: {
        team: "流萤 / 同谐主 / 艾丝妲 / 加拉赫",
        jobs: ["同谐主：提供超击破与击破特攻", "艾丝妲：全队速度、攻击与火属性削韧", "加拉赫：治疗、战技点、单体削韧与击破易伤"],
        gain: "低成本就能跑完整的“拆韧→超击破”循环。",
        lose: "缺少大丽花的未破韧超击破、额外弱点击破效率与固定削韧，长韧性目标会更慢。",
      },
      dahlia: {
        team: "流萤 / 大丽花 / 同谐主 / 加拉赫",
        jobs: ["大丽花：未破韧也能超击破", "全队+50%弱点击破效率", "增加减防、固定削韧、战技点与能量支持"],
        gain: "队伍从“先破韧再出伤”变成“拆韧途中已经能出超击破”。",
        lose: "仍没有忘归人的第二韧性与再次击破，也没有灵砂的群体副削韧/解控。",
      },
      classic: {
        team: "流萤 / 阮·梅 / 同谐主 / 加拉赫",
        jobs: ["阮·梅：弱点击破效率、抗性穿透与速度/击破相关支持", "同谐主：继续负责超击破", "加拉赫：低成本生存与削韧"],
        gain: "老牌结构依然完整，尤其已有成型阮·梅时，没有必要为了“新体系”强行拆队。",
        lose: "没有大丽花的未破韧超击破，也没有忘归人的第二韧性事件。",
      },
      premium: {
        team: "流萤 / 大丽花 / 忘归人 / 灵砂",
        jobs: ["流萤：主削韧、主超击破、2魂额外回合", "大丽花：提前出伤、弱点击破效率、减防、战技点/能量", "忘归人：第二韧性、再次击破、减防、超击破", "灵砂：生存、副削韧、击破易伤、解控"],
        gain: "四个位置把破韧前、第一次击破、第二次击破和生存/副削韧接在一起。",
        lose: "造价最高，而且很多收益依赖敌人真的提供足够韧性与击破事件；低韧性目标可能出现削韧溢出。",
      },
    } as const;
    const current = routeCopy[state.teamRoute];
    return (
      <div className="firefly-card-detail">
        <ToggleRow values={routes} current={state.teamRoute} labels={routeLabels} onChange={(value) => controller.update({ teamRoute: value as typeof state.teamRoute })} />
        <h4>{current.team}</h4>
        <ul>{current.jobs.map((job) => <li key={job}>{job}</li>)}</ul>
        <DetailSection title="新增能力"><p>{current.gain}</p></DetailSection>
        <DetailSection title="仍有缺口 / 成本"><p>{current.lose}</p></DetailSection>
      </div>
    );
  }

  if (id === "damage-ledger") {
    return (
      <div className="firefly-card-detail">
        <DetailSection title="削韧：45 → 80 → 95 → 110"><pre className="firefly-formula">流萤0魂：30×1.5 = 45{"\n"}+大丽花0魂：30×2.0 + 20 = 80{"\n"}+忘归人1魂：30×2.5 + 20 = 95{"\n"}+流萤6魂：30×3.0 + 20 = 110</pre><p>这条轨道同时影响伤害基数，以及第一次弱点击破、2魂触发和完全燃烧延时出现的时点。</p></DetailSection>
        <DetailSection title="超击破倍率：310% → 350%"><pre className="firefly-formula">流萤自身 150%{"\n"}+ 忘归人 100%{"\n"}+ 大丽花0魂 60%{"\n"}= 310%{"\n\n"}大丽花1魂：350 / 310 - 1 ≈ 12.9%</pre><p>12.9%只属于这一层；大丽花1魂还会改变首次固定削韧和行动时点，因此不能直接写成“总提升12.9%”。</p></DetailSection>
        <DetailSection title="防御区"><ul><li>大丽花终结技减防</li><li>忘归人战技减防</li><li>灵砂1魂减防</li><li>流萤1魂无视防御</li><li>遗器可能提供击破/超击破无视防御</li></ul><p>这些来源需要按防御公式合并，不能和抗性区直接相加。</p></DetailSection>
        <DetailSection title="抗性区"><ul><li>大丽花2魂：全属性抗性-20%</li><li>流萤6魂：火属性抗性穿透+20%</li><li>灵砂6魂：全属性抗性-20%</li></ul><p>敌人抗性越高，这一轨越容易升值；普通低抗目标上相对温和。</p></DetailSection>
        <DetailSection title="击破易伤"><ul><li>流萤专武</li><li>忘归人专武叠层</li><li>灵砂终结技与专武</li><li>大丽花专武</li></ul></DetailSection>
        <DetailSection title="循环资源"><ul><li>战技点决定强化战技能不能连续使用。</li><li>能量决定下一次完全燃烧什么时候回来。</li><li>行动提前改变谁先动。</li><li>额外回合直接增加一次完整行动，无法稳定折算成固定增伤。</li></ul></DetailSection>
      </div>
    );
  }

  const modes = ["memory", "apocalyptic", "fiction", "arbitration"] as const;
  const modeCopy = {
    memory: "轮次与稳定轴更重要：一次削韧提速如果刚好让击破跨过轮次边界，大丽花1魂/忘归人1魂的价值会突然放大；没有跨界时，纸面提速未必对应同等实战收益。",
    apocalyptic: "首领机制、韧性与弱点击破事件更重要：长韧性、恢复韧性和阶段机制会直接决定2魂、忘归人和高弱点击破效率能触发几次。",
    fiction: "大量刷新让群攻、击杀链和额外回合更容易升值；大丽花2魂的新敌自动败谢也减少重新铺状态的等待。",
    arbitration: "当期首领机制与高压生存更重要：控制、伤害压力、锁韧和高抗性会同时改变生存位和抗性区投资的优先级。",
  };
  return (
    <div className="firefly-card-detail">
      <div className="firefly-table-wrap"><table className="firefly-table"><thead><tr><th>怪物环境</th><th>环境变化后的价值</th></tr></thead><tbody>
        <tr><td>超长韧性</td><td>大丽花1魂先砍最大韧性；忘归人1魂、流萤6魂持续提高每次削韧。</td></tr>
        <tr><td>锁韧</td><td>普通弱点击破事件消失，但大丽花0魂仍允许未破韧超击破；流萤2魂“击破”分支因此贬值。</td></tr>
        <tr><td>反复恢复韧性</td><td>流萤2魂与忘归人从“每次击破”重复获得事件价值。</td></tr>
        <tr><td>多波次</td><td>击杀链让流萤2魂更容易触发；大丽花2魂让新敌自动进入败谢，减少铺状态时间。</td></tr>
        <tr><td>高防御</td><td>流萤1魂、灵砂1魂与其他减防来源进入更关键的防御区。</td></tr>
        <tr><td>高抗性</td><td>大丽花2魂、流萤6魂、灵砂6魂直接处理抗性区。</td></tr>
        <tr><td>控制/高生存压力</td><td>灵砂的治疗、解控、浮元与副削韧同时产生价值。</td></tr>
        <tr><td>低生存压力竞速</td><td>可以减少生存投入，换更多输出或行动支持，但风险由玩家自己承担。</td></tr>
      </tbody></table></div>
      <ToggleRow values={modes} current={state.mode} labels={MODE_LABELS} onChange={(value) => controller.update({ mode: value as typeof state.mode })} />
      <p>{modeCopy[state.mode]}</p>
      <div className="firefly-note">长期机制与当前版本环境分层显示；这里保留机制差异，不把某一期环境评级写成长期事实。</div>
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
        {hitCount === null ? <><strong>锁韧期间不报“需要几次攻击”</strong><p>弱点击破×；流萤2魂的“击破”触发×；大丽花领域允许超击破✓；若实际击杀，2魂“击杀”触发仍可✓；击破延长完全燃烧×。</p></> : <><strong>{hitCount}次强化战技</strong><p>当前每次主目标削韧：{bossSkillToughness(state.investment)}。{state.investment === "dahlia-1" || state.investment === "fugue-1" || state.investment === "firefly-6" ? "其中大丽花1魂首次再按25%最大韧性削减，最高300。" : ""}</p><div className="firefly-toughness-bars"><div className="firefly-bar"><span style={{ width: "100%" }} /></div>{hasFugue && cloudflame ? <><small>第一次击破后还有云火昭：{cloudflame}韧性</small><div className="firefly-bar cloudflame"><span style={{ width: "40%" }} /></div></> : null}</div></>}
      </div>
      <button className="firefly-link-button" onClick={() => controller.update({ showBossMath: !state.showBossMath })} type="button">{state.showBossMath ? "收起计算" : "看怎么算的"}</button>
      {state.showBossMath ? <pre className="firefly-formula">流萤：30×1.5 = 45{"\n"}+大丽花0魂：30×2.0 + 20 = 80{"\n"}+忘归人1魂：30×2.5 + 20 = 95{"\n"}+流萤6魂：30×3.0 + 20 = 110{"\n"}大丽花1魂首次：min(25%×最大韧性, 300)</pre> : null}
    </section>
  );
}

function updateOneGold(controller: FireflyLessonController, patch: Partial<FireflyOneGoldConfig>) {
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
      ? "当前首领处于锁韧状态，不用攻击次数评价1魂；大丽花0魂仍保留未破韧超击破，1魂固定削韧则要等韧性恢复后再比较。"
      : `${state.bossToughness}韧性简化模型从${bossHitCount(state.bossToughness, "dahlia-0")}发缩到${bossHitCount(state.bossToughness, "dahlia-1")}发，首次额外削韧按25%最大韧性计算、最高300。`
    : recommendation.summary;

  return (
    <section className="firefly-interactive" id="firefly-one-gold">
      <header><h3>手里只有一金</h3><p>建议随当前配置、痛点、怪物环境和首领实验状态变化，不输出固定抽取榜。</p></header>
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
      <div className="firefly-control-block"><span className="firefly-control-label">当前最难受的是</span><ToggleRow values={painPoints} current={state.painPoint} labels={PAIN_POINT_LABELS} onChange={(value) => controller.update({ painPoint: value as typeof state.painPoint })} /></div>
      <div className="firefly-recommendation"><strong>{recommendation.key} · {recommendation.title}</strong><p>{recommendationSummary}</p><ul>{recommendation.details.map((detail) => <li key={detail}>{detail}</li>)}</ul></div>
    </section>
  );
}

export function FireflyDefaultLesson({ controller }: { controller: FireflyLessonController }) {
  const { state } = controller;
  return (
    <div className="firefly-lesson-panel"><div className="firefly-lesson-shell">
      <header className="firefly-lesson-hero"><h2>流萤超击破体系</h2><p>从按钮、削韧和超击破一路看到配队、怪物环境与“一金怎么花”。</p><div className="firefly-version-note">数据按4.2加强后的流萤。若外部资料仍写旧版35%/50%超击破倍率或旧2魂冷却，不采用。</div></header>
      <nav className="firefly-directory" aria-label="流萤课程目录">
        {FIREFLY_CARD_ORDER.map((id) => <button className={`firefly-chip${state.activeCardId === id ? " is-active" : ""}`} key={id} onClick={() => controller.update({ activeCardId: id })} type="button">{FIREFLY_CARD_LABELS[id]}</button>)}
        <a className="firefly-chip" href="#firefly-boss-experiment">首领实验</a><a className="firefly-chip" href="#firefly-one-gold">一金怎么花</a>
      </nav>
      <div className="firefly-card-list">{FIREFLY_CARD_ORDER.map((id, index) => {
        const expanded = state.expandedCardId === id;
        const content = cardSummaries[id];
        return <article className={`firefly-card${state.activeCardId === id ? " is-active" : ""}`} key={id} onMouseEnter={() => controller.update({ activeCardId: id })}>
          <div className="firefly-card-header"><div><span className="firefly-card-index">{String(index + 1).padStart(2, "0")}</span><h3>{FIREFLY_CARD_LABELS[id]}</h3></div><button aria-expanded={expanded} className="firefly-expand" onClick={() => controller.update({ activeCardId: id, expandedCardId: expanded ? null : id })} type="button">{expanded ? "收起" : "展开"}</button></div>
          <p className="firefly-card-summary">{content.summary}</p><div className="firefly-data-row">{content.data.map((item) => <span className="firefly-data-pill" key={item}>{item}</span>)}</div>{expanded ? <CardDetail id={id} controller={controller} /> : null}
        </article>;
      })}</div>
      <div className="firefly-interactions"><BossExperiment controller={controller} /><OneGoldDecision controller={controller} /></div>
      <footer className="firefly-footer">首领实验使用简化计算模型；抽取建议由当前配置、痛点和怪物状态共同决定，不写入长期学习事实。</footer>
    </div></div>
  );
}
