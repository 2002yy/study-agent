import {
  DOUPO_CARD_LABELS,
  DOUPO_CARD_ORDER,
  DOUPO_FACT_LABELS,
  DOUPO_KNOWLEDGE_MATRIX,
  DOUPO_KNOWLEDGE_MOMENT_LABELS,
  DOUPO_LOOP_ORDER,
  DOUPO_LOOP_PROFILES,
  DOUPO_LOOP_STAGE_LABELS,
  DOUPO_LOOP_STAGE_ORDER,
  DOUPO_VALUATION,
  DOUPO_VALUATION_POINT_LABELS,
  DOUPO_VALUATION_SERIES_LABELS,
  DOUPO_WITNESS_LABELS,
  createDefaultDoupoLessonState,
  doupoValuationGap,
  type DoupoCardId,
  type DoupoFactId,
  type DoupoKnowledgeMoment,
  type DoupoKnowledgeStatus,
  type DoupoLessonController,
  type DoupoLoopId,
  type DoupoValuationPoint,
  type DoupoValuationSeriesId,
  type DoupoWitnessId,
} from "./defaultDoupoLesson";
import "./firefly-lesson.css";
import "./doupo-lesson.css";

type StructureBeat = {
  title: string;
  body: string;
};

type CardAnalysis = {
  summary: string;
  data: string[];
  scene: string;
  beats: StructureBeat[];
  mechanism: string;
};

const CARD_ANALYSIS: Record<DoupoCardId, CardAnalysis> = {
  debt: {
    summary: "爽点循环的起点不是赢，而是先让读者清楚地知道：有一笔账以后必须还。",
    data: ["第7章", "尊严债", "三年到期"],
    scene: "退婚发生在萧家大厅。宗门权力、父亲尊严、家族见证和主角此刻的弱势被放进同一场景里。",
    beats: [
      { title: "先有旧价格", body: "三年低谷让“萧炎就是废物”成为现场默认解释。" },
      { title: "再把损失公开化", body: "婚约处理方式让损失从两个人的私事扩散到萧战和萧家的关系网络。" },
      { title: "最后写出到期日", body: "三年之约把模糊屈辱改造成未来必须公开验证的合同。" },
    ],
    mechanism: "这一章的任务是建债，不是还债。债越清楚，未来兑现越不需要靠旁白提醒读者为什么该爽。",
  },
  delay: {
    summary: "延迟不是拖戏。真正有效的延迟，是把今天无法可信结算的问题拖到未来更昂贵的验证条件里。",
    data: ["权力差", "家族风险", "延迟增值"],
    scene: "萧炎面对的不是一个同龄人，而是云岚宗权力在萧家空间里的投影。立刻升级冲突会把父亲和家族一起拖进后果。",
    beats: [
      { title: "现在不能还", body: "实力、势力和公共可信度都不足，今天赢一场嘴仗也改不了社会价格。" },
      { title: "等待必须改变条件", body: "三年不是把同一场争吵搬到未来，而是等双方拥有可公开比较的新事实。" },
      { title: "等待期间继续涨价", body: "真实价值持续上升，旧社会价格更新更慢，未来的落差因此越来越大。" },
    ],
    mechanism: "好延迟会制造“真实价值上涨、外界估值滞后”的剪刀差；坏延迟只是作者把账放着不管。",
  },
  "social-valuation": {
    summary: "“废物”不是一句骂人台词，而是一套多人共享、会真实改变行为的旧估值。",
    data: ["旧标签", "圈层", "行为变化"],
    scene: "同辈、乌坦城势力、纳兰嫣然和云岚宗并不同时得到信息，也不会同时改价。",
    beats: [
      { title: "价格来自共享模型", body: "三段斗之气、低谷、退婚等事实被拼成“未来有限”的统一预测。" },
      { title: "价格落到行为", body: "谁靠近、谁轻视、谁愿意押资源、谁重新评估风险，这些才是价格的现实后果。" },
      { title: "不同圈层更新速度不同", body: "萧家先看到测试，乌坦城稍后核验，纳兰与云岚宗更晚被迫重算。" },
    ],
    mechanism: "爽感不来自所有人同时震惊，而来自同一个真实价值逐层穿透不同社会圈层。",
  },
  "evidence-ladder": {
    summary: "同一个结论反复出现并不等于重复；只要每次新证据都在关闭一个新的退路。",
    data: ["30～40章", "独立证据", "第三方核验"],
    scene: "第一次七段测试出现后，旧模型还能说是偶然、仪器问题或家族内部自证，所以故事继续换证据类型。",
    beats: [
      { title: "正式测量", body: "先让旧模型出现裂缝。" },
      { title: "独立实战", body: "把“仪器错了”的解释关掉。" },
      { title: "严格复测", body: "把“上次操作问题”的解释继续关掉。" },
      { title: "外部核验", body: "结论跨出萧家，开始获得独立信誉。" },
    ],
    mechanism: "证据梯的价值不在数字更大，而在每一级都让旧解释少一条逃生路。",
  },
  "layered-update": {
    summary: "多轮爽点的底层不是“惊讶升级”，而是观察者的旧模型一次比一次更难维持。",
    data: ["异常", "验证", "重估", "回溯"],
    scene: "人物不会因为主角每多打一拳就自动获得新信息。真正有增量的是：新事实是否迫使他们换一套解释世界的模型。",
    beats: [
      { title: "异常", body: "新事实先和旧模型不兼容，但人物还能嘴硬。" },
      { title: "验证", body: "替代解释被独立证据逐个关闭。" },
      { title: "重新定价", body: "人物开始改变未来预期和现实行为。" },
      { title: "回溯重构", body: "新事实强到足以改写此前已经发生过的旧场景。" },
    ],
    mechanism: "每一轮反应都应该对应一次模型变化；只有表情升级、没有解释变化的那一轮通常是空转。",
  },
  "real-failure": {
    summary: "热门角色也需要真失败。它的价值是烧掉确定性，让下一次成功重新变贵。",
    data: ["316章附近", "真失败", "重新下注"],
    scene: "炼药师大会里岩枭第一次炼制确实失败，对手炎利的表现又足够强，连主角自己都短暂失去确定答案。",
    beats: [
      { title: "失败不能撤销", body: "药鼎里的失败结果是真的，不能下一句就说其实全在计划里。" },
      { title: "希望真的转移", body: "场内人物有合理理由把冠军预期转向炎利。" },
      { title: "主角重新下注", body: "外部局面没替他变好，他仍选择再开一炉。" },
      { title: "失败留下状态变化", body: "高压过程推动新的能力变化，后续不是简单回到失败前。" },
    ],
    mechanism: "真失败把“主角肯定会赢”拆掉，再让读者重新下注；这比制造一群降智嘲讽者更值钱。",
  },
  "false-ending": {
    summary: "假终局最强的地方，是先让一个错误结论在当时看起来完全合理。",
    data: ["321章附近", "炸炉", "错误共识"],
    scene: "药鼎开裂、公开炸炉、白雾遮住核心结果，大会程序几乎准备收尾。此刻“岩枭失败”是理性旁观者也会接受的判断。",
    beats: [
      { title: "失败信号足够强", body: "裂缝和炸炉先把公共判断推向同一个方向。" },
      { title: "信息暂时被遮住", body: "白雾制造短窗口，让错误共识有时间成立。" },
      { title: "硬证据翻掉终局", body: "三纹青灵丹仍然存在，实物结果直接推翻刚形成的结论。" },
      { title: "专业审计收尾", body: "七名专业人物继续检查，把“炸炉是否损坏丹药”这条退路也关掉。" },
    ],
    mechanism: "信息遮蔽 → 公共错误共识 → 实物硬证据 → 专业审计。爽点来自合理判断被事实反转，不来自作者强行骗镜头。",
  },
  "identity-merge": {
    summary: "身份揭露之所以能炸，是因为两份已经各自增值很久的账户突然变成同一个人。",
    data: ["第337章", "双账户", "回溯重构"],
    scene: "“萧炎”承载退婚、旧废物标签和三年之约；“岩枭”承载炼药大会冠军、异火和专业认可。很多场内人物一直把它们当成两个人。",
    beats: [
      { title: "两份账户先独立增值", body: "没有前面的分账积累，掉马就只是公布名字。" },
      { title: "合并制造模型冲突", body: "认可岩枭、低估萧炎的角色无法继续同时保留两套旧评价。" },
      { title: "过去一起被重算", body: "大会、异火、沙漠线索和旧选择获得新的统一解释。" },
    ],
    mechanism: "最强的身份揭露不是“现在更强”，而是“过去几百章都得重看一遍”。",
  },
  "moral-settlement": {
    summary: "大爽点还需要边界。三年之约结的是公开羞辱与尊严债，不是把对方的人生自主权一起没收。",
    data: ["332～340章", "尊严债", "结算边界"],
    scene: "最终胜负已经证明萧炎不是当年的低估值人物，但如何定义旧债，决定这场回报是完成结算还是制造新的不公。",
    beats: [
      { title: "先认清原债", body: "核心问题是借宗门权势公开处理婚约、伤及萧战和萧家尊严。" },
      { title: "公开事实完成偿还", body: "胜负让三年前的旧价格在同样公开的场域失效。" },
      { title: "不把债无限外扩", body: "结算到原债边界为止，才能让爽感保持正当性。" },
    ],
    mechanism: "回报越大，越需要和原债保持对应；否则“受不公者翻身”会滑成“新的支配者出现”。",
  },
  "reader-pay": {
    summary: "长篇高潮不能只负责开新坑。先把读者等了几百章的旧账完整支付，再让新的因果接管。",
    data: ["Reader Pay", "旧账 CLOSED", "End Delta"],
    scene: "三年之约把胜负、身份、旧估值和尊严债集中结算；萧炎准备离开后，云棱与墨承相关因果再改变场面。",
    beats: [
      { title: "先兑现旧承诺", body: "读者等待的三年之约必须得到可感知、不可撤销的结果。" },
      { title: "再固定新价格", body: "新估值要进入后续关系和风险判断，不能换地图就清零。" },
      { title: "最后制造新债", body: "旧循环真正闭合之后，新冲突才有资格接管注意力。" },
    ],
    mechanism: "理想顺序是：Reader Pay → 旧账 CLOSED → End Delta → 下一轮新债。",
  },
};

const witnessOrder: DoupoWitnessId[] = [
  "xiao-yan",
  "nalan-yanran",
  "liu-ling",
  "nalan-jie",
  "yunlan-disciples",
  "reader",
];
const factOrder: DoupoFactId[] = ["not-waste", "yanxiao-champion", "same-person"];
const valuationSeries: DoupoValuationSeriesId[] = ["reader", "clan", "city", "nalan", "yunlan"];
const valuationPoints: DoupoValuationPoint[] = [
  "retirement",
  "clan-test",
  "external-audit",
  "alchemy",
  "duel-open",
  "identity-merge",
  "settlement",
];
const shortValuationPointLabels: Record<DoupoValuationPoint, string> = {
  retirement: "退婚",
  "clan-test": "家族测试",
  "external-audit": "外部复测",
  alchemy: "炼药大会",
  "duel-open": "约战开场",
  "identity-merge": "身份合并",
  settlement: "结算",
};

function ChoiceRow<T extends string>({
  values,
  current,
  labels,
  onChange,
}: {
  values: readonly T[];
  current: T;
  labels: Record<T, string>;
  onChange: (value: T) => void;
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

function CardDetail({ id }: { id: DoupoCardId }) {
  const analysis = CARD_ANALYSIS[id];
  return (
    <div className="firefly-card-detail doupo-card-depth">
      <div className="doupo-scene-setup">
        <strong>这一段在循环里做什么</strong>
        <p>{analysis.scene}</p>
      </div>
      <div className="doupo-evidence-ledger">
        {analysis.beats.map((beat, index) => (
          <div className="doupo-evidence-beat" key={beat.title}>
            <span>{String(index + 1).padStart(2, "0")}</span>
            <div>
              <strong>{beat.title}</strong>
              <p>{beat.body}</p>
            </div>
          </div>
        ))}
        <div className="doupo-card-conclusion">
          <strong>这一环为什么有用</strong>
          <p>{analysis.mechanism}</p>
        </div>
      </div>
    </div>
  );
}

function LoopAnalyzer({ controller }: { controller: DoupoLessonController }) {
  const loop = DOUPO_LOOP_PROFILES[controller.state.activeLoopId];
  const stage = controller.state.activeLoopStage;
  const loopLabels = Object.fromEntries(
    DOUPO_LOOP_ORDER.map((id) => [id, DOUPO_LOOP_PROFILES[id].label]),
  ) as Record<DoupoLoopId, string>;

  return (
    <section className="firefly-interactive" id="doupo-loop">
      <header>
        <h3>爽点循环总图 · 看一笔账怎么从欠下滚到下一轮</h3>
        <p>四组样本不是四个孤立名场面，而是四个不同尺度的循环：建债、增值、揭示、重新定价、回溯，再把余波交给下一轮。</p>
      </header>
      <ChoiceRow
        values={DOUPO_LOOP_ORDER}
        current={controller.state.activeLoopId}
        labels={loopLabels}
        onChange={(activeLoopId) =>
          controller.update({ activeLoopId, activeLoopStage: "debt" })
        }
      />
      <div className="firefly-note">
        <strong>{loop.chapters}</strong> · {loop.oneLine}
      </div>
      <div className="doupo-gate-grid">
        {DOUPO_LOOP_STAGE_ORDER.map((loopStage, index) => (
          <button
            aria-pressed={stage === loopStage}
            className={`doupo-gate${stage === loopStage ? " is-on" : ""}`}
            key={loopStage}
            onClick={() => controller.update({ activeLoopStage: loopStage })}
            type="button"
          >
            <strong>{String(index + 1).padStart(2, "0")}</strong>
            <span>{DOUPO_LOOP_STAGE_LABELS[loopStage]}</span>
            <small>{stage === loopStage ? "正在看" : "展开"}</small>
          </button>
        ))}
      </div>
      <div className="doupo-gate-result">
        <strong>{DOUPO_LOOP_STAGE_LABELS[stage]}</strong>：{loop.stages[stage]}
      </div>
    </section>
  );
}

function KnowledgeMap({ controller }: { controller: DoupoLessonController }) {
  const moment = controller.state.knowledgeMoment;
  const matrix = DOUPO_KNOWLEDGE_MATRIX[moment];
  const statusLabel: Record<DoupoKnowledgeStatus, string> = {
    yes: "已经知道",
    no: "还不知道",
    updating: "旧判断正在松动",
  };
  const statusClass: Record<DoupoKnowledgeStatus, string> = {
    yes: "is-match",
    no: "",
    updating: "is-miss",
  };

  return (
    <section className="firefly-interactive" id="doupo-knowledge">
      <header>
        <h3>人物认知差 · 同一事实不会同时到达所有人</h3>
        <p>爽点的燃料之一，就是读者早知道、角色晚知道；不同角色又因为位置不同，在不同时间被迫改价。</p>
      </header>
      <ChoiceRow
        values={["duel-open", "model-breaks", "identity-reveal"] as DoupoKnowledgeMoment[]}
        current={moment}
        labels={DOUPO_KNOWLEDGE_MOMENT_LABELS}
        onChange={(knowledgeMoment) => controller.update({ knowledgeMoment })}
      />
      <div className="doupo-knowledge-wrap">
        <table className="firefly-table doupo-knowledge-table">
          <thead>
            <tr>
              <th>观察者</th>
              {factOrder.map((fact) => (
                <th key={fact}>{DOUPO_FACT_LABELS[fact]}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {witnessOrder.map((witness) => (
              <tr key={witness}>
                <td><strong>{DOUPO_WITNESS_LABELS[witness]}</strong></td>
                {factOrder.map((fact) => {
                  const status = matrix[witness][fact];
                  return (
                    <td key={fact}>
                      <span className={`doupo-knowledge-guess ${statusClass[status]}`}>
                        <span>{statusLabel[status]}</span>
                      </span>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <small>“旧判断正在松动”表示反常证据已经出现，但人物还没把旧模型完全扔掉。</small>
    </section>
  );
}

function ValuationMap({ controller }: { controller: DoupoLessonController }) {
  const point = controller.state.valuationPoint;
  const selectedPointIndex = valuationPoints.indexOf(point);
  const chartWidth = 720;
  const chartHeight = 280;
  const left = 48;
  const right = 22;
  const top = 18;
  const bottom = 58;
  const innerWidth = chartWidth - left - right;
  const innerHeight = chartHeight - top - bottom;
  const xFor = (index: number) => left + (innerWidth * index) / (valuationPoints.length - 1);
  const yFor = (value: number) => top + innerHeight * (1 - value / 100);
  const gridValues = [0, 25, 50, 75, 100];

  return (
    <section className="firefly-interactive" id="doupo-valuation">
      <header>
        <h3>估值滞后曲线 · 真实价值先涨，社会价格后追</h3>
        <p>这里画的是五个观察圈层对“萧炎”这个名字的相对社会价格，用来看谁先更新、谁最后被迫追价。</p>
      </header>
      <ChoiceRow
        values={valuationPoints}
        current={point}
        labels={DOUPO_VALUATION_POINT_LABELS}
        onChange={(valuationPoint) => controller.update({ valuationPoint })}
      />
      <div className="doupo-chart-wrap">
        <svg
          aria-label="五条社会估值随剧情推进变化的结构示意曲线"
          className="doupo-valuation-chart"
          role="img"
          viewBox={`0 0 ${chartWidth} ${chartHeight}`}
        >
          {gridValues.map((value) => (
            <g key={value}>
              <line className="doupo-chart-grid" x1={left} x2={chartWidth - right} y1={yFor(value)} y2={yFor(value)} />
              <text className="doupo-chart-y-label" x={8} y={yFor(value) + 4}>{value}</text>
            </g>
          ))}
          <line
            className="doupo-chart-cursor"
            x1={xFor(selectedPointIndex)}
            x2={xFor(selectedPointIndex)}
            y1={top}
            y2={chartHeight - bottom}
          />
          {valuationSeries.map((series) => {
            const points = valuationPoints
              .map((valuationPoint, index) => `${xFor(index)},${yFor(DOUPO_VALUATION[valuationPoint][series])}`)
              .join(" ");
            return (
              <g className={`doupo-series series-${series}`} key={series}>
                <polyline className="doupo-valuation-line" data-series={series} fill="none" points={points} />
                {valuationPoints.map((valuationPoint, index) => (
                  <circle
                    className="doupo-valuation-point"
                    cx={xFor(index)}
                    cy={yFor(DOUPO_VALUATION[valuationPoint][series])}
                    key={valuationPoint}
                    r={point === valuationPoint ? 4.5 : 2.8}
                  />
                ))}
              </g>
            );
          })}
          {valuationPoints.map((valuationPoint, index) => (
            <text
              className={`doupo-chart-x-label${point === valuationPoint ? " is-active" : ""}`}
              key={valuationPoint}
              textAnchor="middle"
              x={xFor(index)}
              y={chartHeight - 25}
            >
              {shortValuationPointLabels[valuationPoint]}
            </text>
          ))}
        </svg>
      </div>
      <div className="doupo-chart-legend">
        {valuationSeries.map((series) => (
          <div className={`doupo-legend-item series-${series}`} key={series}>
            <i />
            <span>{DOUPO_VALUATION_SERIES_LABELS[series]}</span>
            <strong>{DOUPO_VALUATION[point][series]}</strong>
          </div>
        ))}
      </div>
      <div className="firefly-note">
        当前结构示意差：读者领先四个社会圈层平均约 {doupoValuationGap(point)} 点。炼药大会阶段“岩枭”已经单独涨价，但这份价值还没有记到“萧炎”名下。
      </div>
      <small>0～100 只用于把相对变化画出来，不是原文提供的数值。</small>
    </section>
  );
}

function IdentityMerge({ controller }: { controller: DoupoLessonController }) {
  const merged = controller.state.identityMerged;
  const reactions = [
    ["纳兰嫣然", "此前认可的炼药天才，与三年前自己轻视的人变成同一人。"],
    ["柳翎", "大会冠军岩枭与眼前的决斗者萧炎合并为一个能力账户。"],
    ["纳兰桀", "自己已经欣赏的年轻人，与家族当初推出去的人合并。"],
    ["法犸", "炼药天赋与战斗天赋从两份高价值档案合成一份。"],
    ["古河", "青色异火把沙漠中此前解释不通的事件重新串起来。"],
  ] as const;

  return (
    <section className="firefly-interactive" id="doupo-identity">
      <header>
        <h3>双账户并账 · 看过去怎么被一起重算</h3>
        <p>掉马真正值钱的前提，是两个身份都已经分别积累过关系、信誉和误判。</p>
      </header>
      <div className="doupo-profile-grid">
        <article>
          <span>账户 A</span>
          <h4>萧炎</h4>
          <p>被退婚者 · 旧“废物”标签 · 恢复修炼 · 三年之约对手</p>
        </article>
        <article>
          <span>账户 B</span>
          <h4>岩枭</h4>
          <p>炼药师大会冠军 · 异火 · 高阶炼药评价 · 帝国新高价值身份</p>
        </article>
      </div>
      <button
        className={`doupo-merge-button${merged ? " is-merged" : ""}`}
        onClick={() => controller.update({ identityMerged: !merged })}
        type="button"
      >
        {merged ? "拆开两个账户重新看" : "合并：萧炎 === 岩枭"}
      </button>
      {merged ? (
        <div className="doupo-repricing-list">
          {reactions.map(([name, text]) => (
            <div key={name}>
              <strong>{name}</strong>
              <p>{text}</p>
            </div>
          ))}
        </div>
      ) : (
        <p className="muted">现在两份社会价格仍然分开。合并以后，变化最大的不是现在，而是过去。</p>
      )}
    </section>
  );
}

export function DoupoDefaultLesson({ controller }: { controller: DoupoLessonController }) {
  const { state } = controller;

  return (
    <div className="firefly-lesson-panel doupo-lesson-panel">
      <div className="firefly-lesson-shell doupo-lesson-shell">
        <header className="firefly-lesson-hero">
          <h2>《斗破苍穹》的爽点循环怎么转起来</h2>
          <p>沿四组原文样本直接拆：旧估值怎么形成，情绪债怎么越滚越贵，硬证据怎样公开兑现，再怎么把余波交给下一轮。</p>
          <div className="firefly-version-note">
            这里关心的是剧情内部的认知状态变化：谁还在用旧价格看萧炎，哪些事实已经涨价，什么时候公开证据把旧模型逼到退场，以及一次结算如何回写过去几百章。
          </div>
        </header>

        <nav className="firefly-directory" aria-label="斗破爽点循环目录">
          <a className="firefly-chip" href="#doupo-loop">爽点循环总图</a>
          {DOUPO_CARD_ORDER.map((id) => (
            <button
              className={`firefly-chip${state.activeCardId === id ? " is-active" : ""}`}
              key={id}
              onClick={() => controller.update({ activeCardId: id })}
              type="button"
            >
              {DOUPO_CARD_LABELS[id]}
            </button>
          ))}
          <a className="firefly-chip" href="#doupo-knowledge">人物认知差</a>
          <a className="firefly-chip" href="#doupo-valuation">估值滞后</a>
          <a className="firefly-chip" href="#doupo-identity">双账户并账</a>
        </nav>

        <div className="firefly-interactions doupo-interactions">
          <LoopAnalyzer controller={controller} />
        </div>

        <div className="firefly-card-list">
          {DOUPO_CARD_ORDER.map((id, index) => {
            const expanded = state.expandedCardId === id;
            const analysis = CARD_ANALYSIS[id];
            return (
              <article
                className={`firefly-card${state.activeCardId === id ? " is-active" : ""}`}
                key={id}
                onMouseEnter={() => controller.update({ activeCardId: id })}
              >
                <div className="firefly-card-header">
                  <div>
                    <span className="firefly-card-index">{String(index + 1).padStart(2, "0")}</span>
                    <h3>{DOUPO_CARD_LABELS[id]}</h3>
                  </div>
                  <button
                    aria-expanded={expanded}
                    className="firefly-expand"
                    onClick={() =>
                      controller.update({
                        activeCardId: id,
                        expandedCardId: expanded ? null : id,
                      })
                    }
                    type="button"
                  >
                    {expanded ? "收起" : "展开"}
                  </button>
                </div>
                <p className="firefly-card-summary">{analysis.summary}</p>
                <div className="firefly-data-row">
                  {analysis.data.map((item) => (
                    <span className="firefly-data-pill" key={item}>{item}</span>
                  ))}
                </div>
                {expanded ? <CardDetail id={id} /> : null}
              </article>
            );
          })}
        </div>

        <div className="firefly-interactions doupo-interactions">
          <KnowledgeMap controller={controller} />
          <ValuationMap controller={controller} />
          <IdentityMerge controller={controller} />
        </div>
        <footer className="firefly-footer">
          四组样本：第7章、30～40章、炼药师大会316～322章附近、三年之约332～340章附近。章节号只作定位；原文事实与结构解释分开，结构示意刻度不冒充原文数值。
        </footer>
      </div>
    </div>
  );
}

export function createStandaloneDoupoControllerState() {
  return createDefaultDoupoLessonState();
}
