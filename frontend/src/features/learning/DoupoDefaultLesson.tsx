import { useState } from "react";

import {
  DOUPO_CARD_LABELS,
  DOUPO_CARD_ORDER,
  DOUPO_FACT_LABELS,
  DOUPO_GATE_LABELS,
  DOUPO_GATE_QUESTIONS,
  DOUPO_KNOWLEDGE_MATRIX,
  DOUPO_KNOWLEDGE_MOMENT_LABELS,
  DOUPO_VALUATION,
  DOUPO_VALUATION_POINT_LABELS,
  DOUPO_VALUATION_SERIES_LABELS,
  DOUPO_WITNESS_LABELS,
  createDefaultDoupoLessonState,
  doupoGateDiagnosis,
  doupoValuationGap,
  type DoupoCardId,
  type DoupoFactId,
  type DoupoGateId,
  type DoupoKnowledgeMoment,
  type DoupoKnowledgeStatus,
  type DoupoLessonController,
  type DoupoValuationPoint,
  type DoupoValuationSeriesId,
  type DoupoWitnessId,
} from "./defaultDoupoLesson";
import "./firefly-lesson.css";
import "./doupo-lesson.css";

type ExerciseOption = {
  id: string;
  label: string;
};

type EvidenceBeat = {
  title: string;
  body: string;
};

type CardLesson = {
  summary: string;
  data: string[];
  setup: string;
  question: string;
  options: ExerciseOption[];
  correctOptionIds: string[];
  evidence: EvidenceBeat[];
  conclusion: string;
  transfer: string;
};

const CARD_LESSONS: Record<DoupoCardId, CardLesson> = {
  debt: {
    summary:
      "第7章结束时萧炎没有赢，也没有让所有人改观。为什么这一章却能制造延续几百章的期待？",
    data: ["第7章", "Reader Bet", "未来合同"],
    setup:
      "只看退婚大厅这一段：强势宗门一方公开处理婚约；萧炎此时客观上仍弱；他能反驳、能反写休书，却还不能靠实力让社会重新定价。",
    question: "真正被欠下、需要三年后用事实结清的主要是什么？",
    options: [
      { id: "marriage", label: "纳兰嫣然不愿继续婚约本身" },
      { id: "dignity", label: "借宗门权力公开处理婚约，对萧战与萧家造成的尊严债" },
      { id: "power", label: "萧炎当时修为不够高，所以欠一场单纯的战力展示" },
      { id: "romance", label: "两个人没有建立感情，所以欠一条感情线" },
    ],
    correctOptionIds: ["dignity"],
    evidence: [
      {
        title: "公开场域先把债社会化",
        body: "冲突发生在萧家大厅，父亲、长老与云岚宗来客都在场。损失不只属于两个人，而会被整个关系网络记住。",
      },
      {
        title: "十二岁旧成绩只够让读者下注",
        body: "萧炎拿自己过去成为斗者的事实反驳“永远是废物”的判断，但这只是反主张，还不足以让现场社会立即改价。",
      },
      {
        title: "三年约把模糊屈辱变成可验证合同",
        body: "时间、地点、公开胜负被固定下来。读者从此知道：未来会有一个双方都无法绕开的现实结果。",
      },
      {
        title: "反写休书是局部夺回行动权",
        body: "这能让萧炎当场不完全被动，却没有消除外界对萧家的低估；大账因此没有提前结清。",
      },
      {
        title: "未来结算标准被冻结为“现实”",
        body: "父子对未来的期待最终落到事实而不是争辩：到约定时点，让公开结果迫使旧评价退出。",
      },
    ],
    conclusion:
      "第7章完成的不是“当场打脸”，而是 Reader Bet + Debt + Deadline：读者先下注，一笔可理解的尊严债被建立，并且有了未来公开验收点。",
    transfer:
      "迁移时先问：你的高潮在一百章后发生，那么今天这一章究竟冻结了哪笔债、哪条期限、哪种未来证据？",
  },
  delay: {
    summary:
      "如果当场反击才最爽，为什么故事反而把冲突推迟三年？先判断延迟是不是作者硬拖。",
    data: ["权力差", "现实约束", "延迟合法性"],
    setup:
      "此时萧炎仍处低谷，纳兰嫣然背后是云岚宗。冲突一旦升级，承受后果的并不只有萧炎本人，萧战与整个萧家都在风险链上。",
    question: "如果第7章立刻把冲突升级成武力反击，最关键的结构损失是什么？",
    options: [
      { id: "pace", label: "只是节奏会太快，别的都不影响" },
      { id: "world", label: "世界内权力差被无视，萧家承担外溢风险，未来公开验证也被提前透支" },
      { id: "hero", label: "主角会显得不够忍耐，但爽点反而更完整" },
      { id: "villain", label: "纳兰嫣然会少一次出场机会" },
    ],
    correctOptionIds: ["world"],
    evidence: [
      {
        title: "主角个人愤怒不能覆盖家族风险",
        body: "萧炎面对的不只是同龄人，而是宗门权力在家族空间里的投影；立即升级会把父亲与家族一并拖入后果。",
      },
      {
        title: "延迟必须有世界内原因",
        body: "“现在不能公正结算”不是作者旁白，而是角色可以理解的现实约束。这样等待才不是空转。",
      },
      {
        title: "三年后换的是验证条件",
        body: "延迟不是把同一场争吵复制到未来，而是等待双方拥有能被公开比较、能被旁观者承认的新事实。",
      },
      {
        title: "等待期间估值差可以持续扩大",
        body: "真实价值上升、旧社会价格滞后，才让未来的公开更新拥有越来越大的落差。",
      },
    ],
    conclusion:
      "有效延迟的核心是“现在无法取得可信结算 → 未来建立更强的公共验证条件”。没有现实约束的拖延只是欠账；有约束的延迟会放大账面价值。",
    transfer:
      "检查你的长线伏笔：为什么不能今天解决？答案必须来自权力、信息、能力、制度或空间条件，而不是“作者还不想写高潮”。",
  },
  "social-valuation": {
    summary:
      "“废物”不是一句骂人台词。它是谁共同维护的旧价格？又具体改变了哪些人的行为？",
    data: ["旧标签", "圈层", "行为后果"],
    setup:
      "三年低谷把“萧炎很弱”固化成一个多人共享的社会模型：同辈、外部势力、婚约关系和传言网络都在用它预测萧炎的未来。",
    question: "怎样才算社会估值真的完成更新？",
    options: [
      { id: "shock", label: "围观者惊讶一次就算更新" },
      { id: "number", label: "主角报出一个更高修为数字就算更新" },
      { id: "behavior", label: "人物开始改变合作、资源投入、风险判断、关系距离或权限配置" },
      { id: "reader", label: "只要读者知道主角很强就算更新" },
    ],
    correctOptionIds: ["behavior"],
    evidence: [
      {
        title: "旧标签有明确内容",
        body: "“三段斗之气、被退婚者、弱者、不值得重视”这些判断会被不同圈层反复调用，而不只是背景辱骂。",
      },
      {
        title: "统一测试让“价格”第一次可测",
        body: "家族正式标尺把“强不强”从口水判断变成可公开比较的数据，旧价格因此第一次受到硬冲击。",
      },
      {
        title: "人际距离随新证据变化",
        body: "测试与实战之后，有人重新靠近，有人继续拒绝更新；这说明估值不是表情，而是关系选择。",
      },
      {
        title: "外部势力开始重新分配注意力",
        body: "消息传出家族后，专业人物主动核验增长速度；再往后，各方开始推演萧家的未来位置并调整关系。",
      },
    ],
    conclusion:
      "社会估值 P 不是战力 V 的别名。真正的 Repricing 要落到行为：谁愿意接近你、相信你、押资源、改变风险模型，甚至重新安排未来。",
    transfer:
      "写“众人改观”时删掉所有震惊表情，只保留后续行动。如果情节仍然成立，说明你写的是重新定价；否则多半只是反应噪声。",
  },
  "evidence-ladder": {
    summary:
      "石碑已经显示七段，为什么作者还要安排萧克挑战、严格复测和外部势力核验？",
    data: ["30～40章", "证据升级", "第三方审计"],
    setup:
      "第一次公开测试已经给出异常数据，但一个长期被认定为“废物”的人突然恢复，合理怀疑不会因为一个数字立刻清零。",
    question: "哪条证据链最能解释为什么同一结论需要被反复验证？",
    options: [
      { id: "bigger", label: "七段 → 八段 → 九段：只要数字不断变大就够了" },
      { id: "ladder", label: "正式测量 → 怀疑测试误差 → 独立实战 → 严格复测 → 外部第三方核验 → 资源行为改变" },
      { id: "crowd", label: "围观人数越来越多，所以结论自然越来越真" },
      { id: "speech", label: "主角解释修炼原因，再由长老宣布大家必须相信" },
    ],
    correctOptionIds: ["ladder"],
    evidence: [
      {
        title: "统一标尺：七段",
        body: "第一次测试把旧标签打出裂缝，但现场仍有人无法把结果与“三年废物”模型兼容。",
      },
      {
        title: "合理反证：测试会不会有问题",
        body: "萧克利用制度允许的挑战主动提出怀疑，这不是降智，而是在替旧模型寻找最后一条解释。",
      },
      {
        title: "独立实战：一掌击败挑战者",
        body: "第二条证据不再依赖同一块石碑；能力从“仪器数字”变成可观察行为。",
      },
      {
        title: "严格复测：把监督条件拉高",
        body: "成人仪式上更严格的公开复测继续关闭“上一次偶然/操作问题”的怀疑。",
      },
      {
        title: "外部审计：家族之外的人来核实",
        body: "乌坦城势力与专业人物不再依赖萧家自证；结论跨出原圈层，获得独立信誉。",
      },
      {
        title: "现实跑得比传闻更快",
        body: "外界来验证旧消息时，新成绩已经再次前进；社会估值因此持续落后于真实价值。",
      },
      {
        title: "最终证据是行为配置改变",
        body: "当各方开始调整合作、关注与未来判断，证据链才从“大家信了”推进到真正的社会重新定价。",
      },
    ],
    conclusion:
      "强证据链不是同一个数字连续放大，而是每一级证据都关闭上一层仍然合理的替代解释：测量、实战、复测、外部审计、社会行为依次接管证明责任。",
    transfer:
      "给你的高潮列出怀疑者仍能提出的三个合理问题，然后为每个问题准备性质不同的证据，而不是准备三次更大的数值。",
  },
  "layered-update": {
    summary:
      "所谓“三翻四震”如果只剩四次惊讶就很薄。真正反复更新的到底是什么？",
    data: ["异常", "模型废弃", "回溯重构"],
    setup:
      "同一批人物不会因为每次主角多打一拳就重新获得信息。真正有增量的是：新证据是否逼他们放弃一个旧解释，并建立一个覆盖更广的新模型。",
    question: "哪一种序列最接近原文里的认知升级？",
    options: [
      { id: "faces", label: "惊讶 → 更惊讶 → 极度惊讶 → 全场失声" },
      { id: "model", label: "发现异常 → 验证不是偶然 → 重新定价 → 身份/事实合并后回溯重构过去" },
      { id: "damage", label: "小招 → 大招 → 更大招 → 最终必杀" },
      { id: "crowd", label: "朋友震惊 → 路人震惊 → 长老震惊 → 全城震惊" },
    ],
    correctOptionIds: ["model"],
    evidence: [
      {
        title: "第一层：异常",
        body: "七段、从容化解攻击等事实先让旧印象出现局部不兼容，但人物仍可尝试保留原模型。",
      },
      {
        title: "第二层：验证",
        body: "实战、严格复测、连续化解更高强度攻击，把“偶然、仪器、运气”等解释逐个关闭。",
      },
      {
        title: "第三层：重新定价",
        body: "人物不再只承认“这次表现不错”，而开始重新判断萧炎的成长速度、未来上限和关系价值。",
      },
      {
        title: "第四层：回溯重构",
        body: "身份合并后，人物必须重新解释此前已经经历过的大会、异火、沙漠线索与自己的旧判断。",
      },
    ],
    conclusion:
      "“三翻四震”只能描述表现层。底层机制是连续证据迫使观察者反复废弃旧模型：异常 → 验证 → 重新定价 → 回溯重构。",
    transfer:
      "下一次写多轮反应时，为每一轮标注“旧模型是什么、哪条新证据击穿它、角色接下来会因此做什么”。标不出来的那一轮可以删。",
  },
  "real-failure": {
    summary:
      "炼药师大会里第一次炼制是真的失败。先停在失败发生的那一刻：接下来最有价值的写法是什么？",
    data: ["316章附近", "真失败", "重新下注"],
    setup:
      "岩枭此时已经是热门选手，不能再重复“所有人把他当废物”。他尝试更高风险的火焰转换后确实失败，对手炎利又拿出更强表现，连主角自己都短暂失去确定答案。",
    question: "为了让后面的翻盘更值钱，下一步最应该发生什么？",
    options: [
      { id: "undo", label: "立即说明刚才是假失败，恢复主角无敌确定性" },
      { id: "mock", label: "让全场突然降智嘲讽岩枭，复制早期废柴结构" },
      { id: "rebet", label: "保留真实损失，让希望转移；主角在没有确定答案时重新下注，并让失败改变后续能力状态" },
      { id: "skip", label: "直接切到颁奖，下一章再用旁白说他其实赢了" },
    ],
    correctOptionIds: ["rebet"],
    evidence: [
      {
        title: "失败首先必须是真的",
        body: "药鼎里留下失败结果，萧炎本人也承认高估了掌控能力；读者不能把它解释成故意表演。",
      },
      {
        title: "希望暂时转向对手",
        body: "炎利拿出足够强的成果，观众和专业人物都有理由重新判断冠军归属，而不是配角强行嘲讽。",
      },
      {
        title: "主角出现短暂茫然",
        body: "在缺少药老即时兜底的情况下，失败真正侵入主角决策，重新振作因此需要成本。",
      },
      {
        title: "重新承诺发生在证据仍不利时",
        body: "萧炎选择再开一炉时，外部局面没有替他变好；这才是一次新的 Reader Bet，而不是赛后补口号。",
      },
      {
        title: "失败改变能力状态",
        body: "高压过程推动灵魂力量突破，后续炼制不是简单回到失败前的原状态。",
      },
    ],
    conclusion:
      "真失败的价值在于烧掉确定性。它让读者和主角都必须重新下注；只要失败会改变后续状态，翻盘就不再是“成功按钮再按一次”。",
    transfer:
      "给主角一次失败时，不要只问“损失了什么”，还要问“这次失败是否改变了他的能力、策略、关系或读者确定性”。",
  },
  "false-ending": {
    summary:
      "先把321章结果遮住：药鼎开裂、公开炸炉、白雾遮住结果，大会程序已经准备收尾。此刻你会怎样判？",
    data: ["321章附近", "错误共识", "延迟揭晓"],
    setup:
      "第二轮炼制已把风险推到更高层：药鼎裂缝公开出现，随后真的炸炉；白雾让核心结果暂时不可见，连官方判断都几乎要转向炎利。先不要看烟雾之后。",
    question: "在白雾散开前，最合理的场内公共结论是什么？",
    options: [
      { id: "success", label: "大家应该立刻知道丹药成功，因为主角不会输" },
      { id: "failure", label: "按现有公开证据，岩枭大概率失败，炎利几乎锁定冠军" },
      { id: "cheat", label: "观众应该马上认定有人作弊" },
      { id: "none", label: "炸炉没有任何信息价值，所有人都应保持完全中立" },
    ],
    correctOptionIds: ["failure"],
    evidence: [
      {
        title: "裂缝先建立失败即将确定的信号",
        body: "连专业人士都知道这种状态危险，旁观者形成失败预期并不愚蠢。",
      },
      {
        title: "爆炸 + 白雾制造信息遮蔽窗口",
        body: "关键不是爆炸声势，而是所有人暂时看不到真正结果，于是公共判断可以先收敛到一个错误终局。",
      },
      {
        title: "官方程序几乎准备宣布对手胜利",
        body: "错误共识进入制度层，假终局不再只是路人表情，而是即将成为正式结果。",
      },
      {
        title: "揭晓：三纹青灵丹仍然存在",
        body: "白雾散开后，实物结果直接推翻刚形成的结论；不是主角靠一句“其实我成功了”夺回解释权。",
      },
      {
        title: "七名专业人物继续检查",
        body: "炸炉是否损坏丹药仍是合理怀疑，因此作者补上第三方审计，把最后的替代解释也关掉。",
      },
      {
        title: "一次比赛结果升级为人才估值",
        body: "高阶炼药师的评价把“这次赢了”继续推向“这个年轻人的长期上限可能更高”。",
      },
    ],
    conclusion:
      "假终局必须先让错误判断变得合理，再用不可辩驳的新事实翻转它。这里的核心不是“又炸一次”，而是信息遮蔽 → 公共错误共识 → 实物证据 → 专家审计。",
    transfer:
      "设计假终局时先写一份“如果我是理性旁观者，为什么此刻也会判断主角输了”的证据清单。写不出来，就只是作者骗镜头。",
  },
  "identity-merge": {
    summary:
      "“萧炎很强”只更新现在；“岩枭就是萧炎”为什么会让人物连过去都一起重算？",
    data: ["第337章", "双账户", "回溯性重估"],
    setup:
      "此前社会里存在两份互不相干的档案：萧炎承载被退婚、旧废物标签与三年之约；岩枭承载炼药大会冠军、异火与专业认可。读者知道两者相同，很多场内人物不知道。",
    question: "身份揭露最强的增量是什么？",
    options: [
      { id: "power", label: "只证明萧炎当前战斗力又高了一点" },
      { id: "name", label: "只是给主角增加一个新的外号" },
      { id: "retro", label: "把两个独立高低估值账户合并，迫使人物重算自己过去的一串判断" },
      { id: "crowd", label: "让更多围观者能喊出主角名字" },
    ],
    correctOptionIds: ["retro"],
    evidence: [
      {
        title: "纳兰嫣然：两套互相冲突的评价相撞",
        body: "她已经能认可岩枭这个同龄炼药天才，却仍背着三年前对萧炎的旧判断；账户合并后两套评价不能同时保持原样。",
      },
      {
        title: "柳翎与法犸：专业能力和战斗身份合并",
        body: "大会冠军不再是另一个人，眼前决斗者也不再只是战斗线角色，人物必须把两条能力证据汇总。",
      },
      {
        title: "纳兰桀：此前欣赏对象回写家族旧决定",
        body: "已经被高度欣赏的年轻人与当初家族主动推出去的人变成同一个人，旧选择因此获得新的成本解释。",
      },
      {
        title: "古河：旧谜团被新身份回溯解释",
        body: "异火等线索把沙漠中此前解释不通的事件重新串起来，新事实开始改写过去场景。",
      },
      {
        title: "揭露后仍继续现场增值",
        body: "身份合并并没有立刻结束高潮，后续危险能力展示继续给新合并账户补上现场证据。",
      },
    ],
    conclusion:
      "身份合并的强度取决于回溯范围：它不是“萧炎 += 很厉害”，而是“萧炎 === 岩枭”，让当前价值、过去判断与未解线索同时重新计算。",
    transfer:
      "隐藏身份只有在两个身份各自积累过独立关系、信誉和误判时才值钱。没有双账户积累，揭面就只是信息公布。",
  },
  "moral-settlement": {
    summary:
      "三年之约最后究竟在结哪笔账？如果把“退婚自主权”和“公开羞辱方式”混成一件事，结局会变味。",
    data: ["332～340章", "尊严债", "伦理边界"],
    setup:
      "最终胜负已经证明萧炎不是当年的低估值人物。但“赢了”还不等于情绪债结算正确：主角如何定义旧债、又如何处理当年的为奴为婢约定，决定了整个回报的伦理方向。",
    question: "最应该被结算的对象是什么？",
    options: [
      { id: "choice", label: "纳兰嫣然拥有选择婚约的自主权本身" },
      { id: "dignity", label: "借宗门权力公开处理婚约、伤及萧家尊严的方式与由此形成的旧判断" },
      { id: "slave", label: "必须严格执行为奴为婢，越重越能证明爽感" },
      { id: "win", label: "只要战斗赢了就够了，旧账是什么并不重要" },
    ],
    correctOptionIds: ["dignity"],
    evidence: [
      {
        title: "最终胜负先结实力问题",
        body: "现场已经无法继续维持“萧炎是废物”的旧模型，人物进一步开始重算年龄、成长速度与未来上限。",
      },
      {
        title: "双方把旧事重新定义为处理方式问题",
        body: "结算焦点落到当年如何借宗门与公开场域处理婚约，而不是把“她不愿嫁”本身定义成罪。",
      },
      {
        title: "拒绝把旧债升级成新支配",
        body: "萧炎没有执行为奴为婢，而是释放这条承诺；这阻止受不公者在胜利后变成新的不公者。",
      },
      {
        title: "休书被处理，主角自己也卸下长期负担",
        body: "结算不是无限追债，而是把持续三年的身份与尊严冲突真正关闭。",
      },
    ],
    conclusion:
      "强回报需要道德对称：结算强度不能越过原债的合法边界。三年之约偿还的是公开处理方式与尊严债，而不是惩罚女性拥有退婚选择。",
    transfer:
      "给复仇/雪耻高潮做一次 G7 检查：主角最后拿走的东西，是否比当初真正被夺走的还多？如果多，爽点可能会发生道德反转。",
  },
  "reader-pay": {
    summary:
      "如果三年之约在“全场震惊”那一格直接黑屏，和先把旧债结清再打开新因果链，有什么差别？",
    data: ["Reader Pay", "旧债 CLOSED", "End Delta"],
    setup:
      "一个长线高潮既要兑现旧承诺，又不能让故事失去继续前进的动力。两件事顺序错了，就会出现“为了留悬念故意不给结算”或“结算完一切归零”。",
    question: "哪一种收尾更符合长篇状态机？",
    options: [
      { id: "cut", label: "胜负一出、众人震惊，立刻切卷；旧关系以后再说" },
      { id: "delta", label: "先让胜负、尊严债和旧身份真正关闭，再由云棱/墨承相关因果改变现场状态" },
      { id: "new", label: "高潮还没结清就突然抛出更大反派，把旧债留到以后" },
      { id: "reset", label: "进入新地图后让所有人忘掉这次重新估值，重新从被轻视开始" },
    ],
    correctOptionIds: ["delta"],
    evidence: [
      {
        title: "先支付 Reader Pay",
        body: "胜负、成长估值与三年前的尊严债都要得到明确状态变化，读者等待几百章的核心承诺不能被新悬念抢走。",
      },
      {
        title: "旧账必须真的 CLOSED",
        body: "人物承认处理方式、旧约被放下、主角负担解除，说明这条状态链已经有结束条件。",
      },
      {
        title: "再产生 End Delta",
        body: "萧炎准备离开后，云棱叫住他，随后墨承相关身份链重新接管局面；新因果改变的是结算后的状态。",
      },
      {
        title: "持久重新定价不能换地图清零",
        body: "高潮形成的新社会价格必须进入后续关系与风险判断，否则前面建立的证据价值会被作品自己撤销。",
      },
    ],
    conclusion:
      "长篇高潮的理想顺序是 Reader Pay → 旧账 CLOSED → End Delta。先完整支付承诺，再让新的因果改变状态，而不是用新悬念赖掉旧账。",
    transfer:
      "给每个大高潮分别写两行：本场必须永久关闭什么？结束后一秒钟，哪个新事实让局面与开场不同？这两行就是 Reader Pay 与 End Delta。",
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
const valuationSeries: DoupoValuationSeriesId[] = [
  "reader",
  "clan",
  "city",
  "nalan",
  "yunlan",
];
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
const knowledgeMoments: DoupoKnowledgeMoment[] = [
  "duel-open",
  "model-breaks",
  "identity-reveal",
];
const gateOrder: DoupoGateId[] = ["G1", "G2", "G3", "G4", "G5", "G6", "G7"];

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

function CardDetail({
  id,
  selectedOptionId,
  revealed,
  onSelect,
  onReveal,
}: {
  id: DoupoCardId;
  selectedOptionId?: string;
  revealed: boolean;
  onSelect: (optionId: string) => void;
  onReveal: () => void;
}) {
  const lesson = CARD_LESSONS[id];
  const answered = Boolean(selectedOptionId);
  const correct = selectedOptionId
    ? lesson.correctOptionIds.includes(selectedOptionId)
    : false;

  return (
    <div className="firefly-card-detail doupo-card-depth">
      <div className="doupo-scene-setup">
        <strong>先冻结在这个时刻</strong>
        <p>{lesson.setup}</p>
      </div>
      <fieldset className="doupo-exercise">
        <legend>{lesson.question}</legend>
        <div className="doupo-option-grid">
          {lesson.options.map((option) => (
            <button
              aria-pressed={selectedOptionId === option.id}
              className={`doupo-option${selectedOptionId === option.id ? " is-selected" : ""}`}
              key={option.id}
              onClick={() => onSelect(option.id)}
              type="button"
            >
              {option.label}
            </button>
          ))}
        </div>
      </fieldset>
      {answered ? (
        <div className={`doupo-prediction-state${correct ? " is-hit" : " is-rethink"}`}>
          <strong>{correct ? "你的判断抓到了关键变量。" : "先保留这个判断，不急着改答案。"}</strong>
          <span>下一步不是看标准答案，而是让证据链自己把可行解释逐层关掉。</span>
        </div>
      ) : (
        <p className="doupo-prediction-hint">先选一个判断，证据链才会解锁。</p>
      )}
      <button
        className="doupo-reveal-button"
        disabled={!answered}
        onClick={onReveal}
        type="button"
      >
        {revealed ? "证据链已展开" : "查看证据链，再修正判断"}
      </button>
      {revealed ? (
        <div className="doupo-evidence-ledger">
          {lesson.evidence.map((beat, index) => (
            <div className="doupo-evidence-beat" key={beat.title}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <div>
                <strong>{beat.title}</strong>
                <p>{beat.body}</p>
              </div>
            </div>
          ))}
          <div className="doupo-card-conclusion">
            <strong>修正后的模型</strong>
            <p>{lesson.conclusion}</p>
          </div>
          <div className="doupo-transfer-note">
            <strong>迁移检查</strong>
            <p>{lesson.transfer}</p>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function KnowledgeExperiment({ controller }: { controller: DoupoLessonController }) {
  const [guesses, setGuesses] = useState<Record<string, DoupoKnowledgeStatus>>({});
  const [revealedMoments, setRevealedMoments] = useState<
    Partial<Record<DoupoKnowledgeMoment, boolean>>
  >({});
  const moment = controller.state.knowledgeMoment;
  const matrix = DOUPO_KNOWLEDGE_MATRIX[moment];
  const revealed = Boolean(revealedMoments[moment]);
  const statusLabel: Record<DoupoKnowledgeStatus, string> = {
    yes: "知道",
    no: "不知道",
    updating: "正在更新",
  };
  const nextStatus: Record<DoupoKnowledgeStatus, DoupoKnowledgeStatus> = {
    no: "updating",
    updating: "yes",
    yes: "no",
  };
  const guessKey = (witness: DoupoWitnessId, fact: DoupoFactId) =>
    `${moment}|${witness}|${fact}`;
  const cycleGuess = (witness: DoupoWitnessId, fact: DoupoFactId) => {
    const key = guessKey(witness, fact);
    setGuesses((current) => ({
      ...current,
      [key]: current[key] ? nextStatus[current[key]] : "no",
    }));
  };
  const resetMoment = () => {
    setGuesses((current) =>
      Object.fromEntries(
        Object.entries(current).filter(([key]) => !key.startsWith(`${moment}|`)),
      ),
    );
    setRevealedMoments((current) => ({ ...current, [moment]: false }));
  };

  return (
    <section className="firefly-interactive" id="doupo-knowledge">
      <header>
        <h3>人物知识状态 · 先预测再对照</h3>
        <p>不要先看答案。给每个人标“知道 / 不知道 / 正在更新”，再打开证据账本。</p>
      </header>
      <ChoiceRow
        values={knowledgeMoments}
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
                <td>
                  <strong>{DOUPO_WITNESS_LABELS[witness]}</strong>
                </td>
                {factOrder.map((fact) => {
                  const key = guessKey(witness, fact);
                  const guess = guesses[key];
                  const expected = matrix[witness][fact];
                  const matches = guess === expected;
                  return (
                    <td key={fact}>
                      <button
                        aria-label={`${DOUPO_WITNESS_LABELS[witness]}：${DOUPO_FACT_LABELS[fact]}`}
                        className={`doupo-knowledge-guess${revealed && guess ? (matches ? " is-match" : " is-miss") : ""}`}
                        onClick={() => cycleGuess(witness, fact)}
                        type="button"
                      >
                        <span>{guess ? statusLabel[guess] : "未判断"}</span>
                        {revealed ? (
                          <small>证据账本：{statusLabel[expected]}</small>
                        ) : (
                          <small>点击切换</small>
                        )}
                      </button>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="doupo-experiment-actions">
        <button
          className="doupo-reveal-button"
          onClick={() =>
            setRevealedMoments((current) => ({ ...current, [moment]: true }))
          }
          type="button"
        >
          对照证据账本
        </button>
        <button className="doupo-secondary-button" onClick={resetMoment} type="button">
          重置本时刻
        </button>
      </div>
      <small>
        “正在更新”表示人物已经得到反常证据，但旧模型尚未完全退出。重点不是猜满分，而是看同一事实为什么在不同人脑中有不同到达时间。
      </small>
    </section>
  );
}

function ValuationExperiment({ controller }: { controller: DoupoLessonController }) {
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
  const xFor = (index: number) =>
    left + (innerWidth * index) / (valuationPoints.length - 1);
  const yFor = (value: number) => top + innerHeight * (1 - value / 100);
  const gridValues = [0, 25, 50, 75, 100];

  return (
    <section className="firefly-interactive" id="doupo-valuation">
      <header>
        <h3>社会估值曲线 · 看见“价值领先、认知滞后”</h3>
        <p>这里画的不是战力，而是五个观察圈层在七个时点给“萧炎”这个名字的相对社会价格。</p>
      </header>
      <ChoiceRow
        values={valuationPoints}
        current={point}
        labels={DOUPO_VALUATION_POINT_LABELS}
        onChange={(valuationPoint) => controller.update({ valuationPoint })}
      />
      <div className="doupo-chart-wrap">
        <svg
          aria-label="五条社会估值随时间变化的教学曲线"
          className="doupo-valuation-chart"
          role="img"
          viewBox={`0 0 ${chartWidth} ${chartHeight}`}
        >
          {gridValues.map((value) => (
            <g key={value}>
              <line
                className="doupo-chart-grid"
                x1={left}
                x2={chartWidth - right}
                y1={yFor(value)}
                y2={yFor(value)}
              />
              <text className="doupo-chart-y-label" x={8} y={yFor(value) + 4}>
                {value}
              </text>
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
              .map(
                (valuationPoint, index) =>
                  `${xFor(index)},${yFor(DOUPO_VALUATION[valuationPoint][series])}`,
              )
              .join(" ");
            return (
              <g className={`doupo-series series-${series}`} key={series}>
                <polyline
                  className="doupo-valuation-line"
                  data-series={series}
                  fill="none"
                  points={points}
                />
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
        当前教学估值差：读者领先四个社会圈层平均约 {doupoValuationGap(point)} 点。注意大会阶段“岩枭”已经形成独立高价值账户，但很多人仍没有把这份价格记到“萧炎”名下；第337章才发生账户合并。
      </div>
      <small>0～100 只是把相对变化画出来的教学量表，不是原文提供的数值。看曲线形状，不要把数字当史料。</small>
    </section>
  );
}

function IdentityMergeExperiment({ controller }: { controller: DoupoLessonController }) {
  const merged = controller.state.identityMerged;
  const reactions = [
    ["纳兰嫣然", "此前认可的炼药天才，与三年前自己轻视的人变成同一人。"],
    ["柳翎", "大会冠军岩枭与眼前的决斗者萧炎合并为一个能力账户。"],
    ["纳兰桀", "自己已经欣赏的年轻人，与家族当初推出去的人合并。"],
    ["法犸", "炼药天赋与战斗天赋从两份高估值档案合成一份。"],
    ["古河", "青色异火把沙漠中此前解释不通的事件重新串起来。"],
  ] as const;
  return (
    <section className="firefly-interactive" id="doupo-identity">
      <header>
        <h3>身份合并 · 手动执行一次回溯性重新估值</h3>
        <p>普通掉马只增加一个新事实；这里会让多个角色重算已经发生过的历史。</p>
      </header>
      <div className="doupo-profile-grid">
        <article>
          <span>档案 A</span>
          <h4>萧炎</h4>
          <p>被退婚者 · 旧“废物”标签 · 恢复修炼 · 三年之约对手</p>
        </article>
        <article>
          <span>档案 B</span>
          <h4>岩枭</h4>
          <p>炼药师大会冠军 · 异火 · 高阶炼药评价 · 帝国新高价值身份</p>
        </article>
      </div>
      <button
        className={`doupo-merge-button${merged ? " is-merged" : ""}`}
        onClick={() => controller.update({ identityMerged: !merged })}
        type="button"
      >
        {merged ? "拆开两个账户重新看" : "执行：萧炎 === 岩枭"}
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
        <p className="muted">现在两套评价仍然分离。先保留这个信息差，再执行合并。</p>
      )}
    </section>
  );
}

function SevenGateAudit({ controller }: { controller: DoupoLessonController }) {
  const toggle = (gate: DoupoGateId) =>
    controller.update({
      gates: {
        ...controller.state.gates,
        [gate]: !controller.state.gates[gate],
      },
    });
  return (
    <section className="firefly-interactive" id="doupo-gates">
      <header>
        <h3>重新估值七门</h3>
        <p>把任意一门关掉，观察一个“废柴→暴露实力→全场震惊”结构为什么会变轻。</p>
      </header>
      <div className="doupo-gate-grid">
        {gateOrder.map((gate) => (
          <button
            aria-pressed={controller.state.gates[gate]}
            className={`doupo-gate${controller.state.gates[gate] ? " is-on" : ""}`}
            key={gate}
            onClick={() => toggle(gate)}
            title={DOUPO_GATE_QUESTIONS[gate]}
            type="button"
          >
            <strong>{gate}</strong>
            <span>{DOUPO_GATE_LABELS[gate]}</span>
            <small>{controller.state.gates[gate] ? "通过" : "关闭"}</small>
          </button>
        ))}
      </div>
      <div className="doupo-gate-result">{doupoGateDiagnosis(controller.state)}</div>
    </section>
  );
}

export function DoupoDefaultLesson({ controller }: { controller: DoupoLessonController }) {
  const { state } = controller;
  const [answers, setAnswers] = useState<Partial<Record<DoupoCardId, string>>>({});
  const [revealedCards, setRevealedCards] = useState<
    Partial<Record<DoupoCardId, boolean>>
  >({});

  return (
    <div className="firefly-lesson-panel doupo-lesson-panel">
      <div className="firefly-lesson-shell doupo-lesson-shell">
        <header className="firefly-lesson-hero">
          <h2>长篇小说为什么会让你爽</h2>
          <p>用《斗破苍穹》的四组原文样本，追踪读者预期、人物知识边界、社会估值与长期情绪债。</p>
          <div className="firefly-version-note">
            这不是十张“文学结论卡”。每张都先停在原文尚未揭晓的位置：你先判断，再看证据，再修正模型。原文事实与结构解释分开；《斗破》是升级流成熟期的高完成度代表，不宣称它发明了升级流。
          </div>
        </header>

        <nav className="firefly-directory" aria-label="斗破课程目录">
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
          <a className="firefly-chip" href="#doupo-knowledge">人物知识</a>
          <a className="firefly-chip" href="#doupo-valuation">估值曲线</a>
          <a className="firefly-chip" href="#doupo-identity">身份合并</a>
          <a className="firefly-chip" href="#doupo-gates">重新估值七门</a>
        </nav>

        <div className="firefly-card-list">
          {DOUPO_CARD_ORDER.map((id, index) => {
            const expanded = state.expandedCardId === id;
            const lesson = CARD_LESSONS[id];
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
                <p className="firefly-card-summary">{lesson.summary}</p>
                <div className="firefly-data-row">
                  {lesson.data.map((item) => (
                    <span className="firefly-data-pill" key={item}>{item}</span>
                  ))}
                </div>
                {expanded ? (
                  <CardDetail
                    id={id}
                    selectedOptionId={answers[id]}
                    revealed={Boolean(revealedCards[id])}
                    onSelect={(optionId) =>
                      setAnswers((current) => ({ ...current, [id]: optionId }))
                    }
                    onReveal={() =>
                      setRevealedCards((current) => ({ ...current, [id]: true }))
                    }
                  />
                ) : null}
              </article>
            );
          })}
        </div>

        <div className="firefly-interactions doupo-interactions">
          <KnowledgeExperiment controller={controller} />
          <ValuationExperiment controller={controller} />
          <IdentityMergeExperiment controller={controller} />
          <SevenGateAudit controller={controller} />
        </div>
        <footer className="firefly-footer">
          四组样本：第7章、30～40章、炼药师大会316～322章附近、三年之约332～340章附近。章节号只作定位，课程事实来自此前 evidence ledger；教学解释与教学量表不冒充原文原句或原始数值。
        </footer>
      </div>
    </div>
  );
}

export function createStandaloneDoupoControllerState() {
  return createDefaultDoupoLessonState();
}
