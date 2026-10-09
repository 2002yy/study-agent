# 隔离模型能力 A/B（2026-10-09）

状态：实验底座本地验收；正式调用、语义结论及 RP-1 GO 均未取得。
替代 b7fecabc handoff 的生产规划适配下一刀；本轮不改 src、生产路由、UI、学习写入、研究预算或发布权。

## 对照与解释

- A 直接调用现有 ResearchSemanticSession.interpret 和 ResearchDecision.parse，保存原始响应及首次校验错误。不修复模型编号。
- B 只接收自然语言 tasks/question 的最小 JSON 传输，程序按原问题、行号及完整文本分配稳定 ID；不做主题分类、相似度匹配或语义改写。传输接受不代表正确规划。
- 固定证据阶段也比较规划约束：同题、同份真实资料快照、相同回答提示，分别携带同组同重复的有效规划。无合法规划则记录 blocked，不暗中补一个通用规划。
- 因此第二阶段测量规划条件对证据使用的整体影响，不是独立的纯推理因果测量。另报有合法规划子集及无条件任务完成率，避免幸存者偏差。
- 任务类别只用于实验分层，不成为执行入口白名单。

## 冻结与调用

工具 tools/research_ability_ab.py 完全隔离；不调用搜索、chat API、生产 repository 或发布服务。只使用已有 configured_completion。
实际本地配置核对：flash=`deepseek-flash`，temperature=0，max_tokens=1400，timeout=5s，JSON object，thinking disabled，SDK retries=0。
该名称是提供商模型别名，后端不可变模型修订号 NOT_OBSERVED；不能声称已锁定提供商内部权重版本。
两个阶段共用原 interpreter 的 task-specific 配置；若环境覆盖额度或配置变化，拒绝继续，须重新冻结。公开配置不包含密钥或 provider 地址。

完整第一轮：24题 × A/B × 2重复 = 96次规划；固定证据阶段最多再96次回答调用（规划失败会减少实际调用数），上限192，分别记账。
当前公开题准备18题，六能力各3、L1/L2/L3各6；独立保留题6道另行解封。
不能预设保留题恰好补成每能力4题、每难度8题；解封后先核对分布，冻结完整清单及评分标准，再开始正式调用。
公开题及证据还需完成来源快照与完整答案标准；当前 rubric 是预登记规划评分要点，不能冒充固定证据标准答案。
每题事先指定事实/条件义务、证据不足行为、严重错误判据。自然阶段12题须在查看输出前选定。
同一最终 manifest 包含原题、人工标准和真实来源 text/url/SHA；CLI 必须传 expected SHA，随机种子20261009，每组两次，随机交错，无自动重试、增额或失败后改题。
固定证据依赖同一 manifest、代码及配置冻结的 planning registry；来源哈希错、跨题/跨组/重复编号错均拒绝。
输出目录必须新建，既有原始材料不能覆盖。原始请求/响应独立落盘，迟到响应保存但不重新取得有效资格；延迟、调用次数、错误原因记录，未取得 token/费用即 NOT_OBSERVED。

## 保留题与盲审

封存文件 C:/Users/Zhang/Downloads/study-agent-rp1-holdout-6.sealed，18151 bytes。
本地密文 SHA-256：26b26a41a09d1d4b9613aca59375980df3db6d3c960c700e541b98be1466dc83。
用户声明冻结的明文 SHA-256：8d1a36422ebadbe6107cc1aa4233da9e553719b5ef07e179794434259387c72b。
只计算密文摘要；未尝试解密，未检查明文/答案。明文哈希尚未独立核验。
题目及标准由未参与本底座开发的 GPT-6 制定（用户交接），最终独立人类盲审者由用户明确为用户本人。
代码冻结并提供完整 HEAD/配置/预算后，才接收解封明文及校验 SHA；不在解封后针对保留题调提示。

blind-review.json 使用随机匿名标签、相同输出格式，移除组别、RQ ID、请求提示和程序校验结论；organizer-key.json 为单独揭盲材料。
组织者只交 reviewer 文件；先评分并冻结评分哈希，后揭盲。用户兼组织者及审阅者时须自律不查看 key/原始 prompt。
文字风格仍可能透露组别，故为尽力匿名化，不声称完全不可辨识盲法。原始输出留给评分后争议复核。
自动核对只判断引用 ID、原文子串、来源哈希等结构；存在引用绝不等于语义支持。所有 semantic_support 保持 PENDING_HUMAN_REVIEW。
分别报告规划覆盖/精确/条件保持、合格证据覆盖、错误支持、最终覆盖、成本/时延、完成率和危险错误率；不以平均分或少量零错误授权发布。

## 停止与下一门

固定证据有缺引用/不存在或错位引用等结构风险即停止该批，保存已完成匿名包；语义严重错误由人类复核后停止相关风险路径。
纯规划格式失败只记录，不转成证据成功。不得利用重试或修复改变事实、身份、阈值或既有研究预算。
自然 Lookup→Standard→Deep 实验入口尚未实现，本工具故意不接受 natural phase。不能以纯规划 B 成功冒充 Deep 或产品能力合格。
下一步：提供冻结代码 HEAD → 接收保留题并验证明文哈希 → 冻结完整24题、真实资料/答案标准及12题自然选择 → 第一轮配对调用 → 用户盲审 → 才决定自然研究实验切片。
RP-1 保持 NO-GO；b7fecabc 通用合同与只读诊断保留，既有源证据/身份/预算/Deep-4B 不变。

## 本地底座验收

16项新测试PASS；命名L2 research-ability-ab-v1 288PASS/117.01秒，包含原规划与Lookup/Deep权威相邻回归。
全src/tests/tools Ruff与新文件format PASS；mypy src当前122/基线128/NEW0；工具单独mypy最终PASS。
首轮工具mypy两处字典类型推断错误，仅补类型注解后16项复验，未变更运行行为，不重复L2或生产L3。
公開题manifest真实文件SHA bd0e1fee8e33c04c0877643088680bf80fe6f074e60966ffc51eee6ed09abbdb；dry-run生成72行，实际模型调用0。
初次预检因Windows换行导致字符串摘要不同于落盘字节而拒绝；修正外部准备器按file bytes计算SHA，原题内容未改，未绕过校验器。
范围仅工具、定点测试、命名gate及两份文档；diff-check PASS，src及UI/A线无改动。最终完整HEAD/工作树clean由Git与外部closeout.json恢复。
验证记录保留首次tool-mypy失败，不把旧失败日志覆盖为通过。无push/PR/CI；不是RP-1 CLOSED或能力结论。

## 解封与资料准备（2026-10-09）

代码冻结头 `cb32617ce4ec8aaab4050e257f1056a79917c247` 的干净状态、harness SHA和实际模型配置，在解封登记前再次核对一致。
cryptography缺失，解密依赖仅安装到外部证据目录 decrypt-deps，不改项目venv/requirements或冻结代码。
AES-256-GCM认证PASS；密文和原始明文字节SHA均与用户给定值一致；holdout-6.json原样保存，六题各100分，未重生成或改答案标准。
本次由同一执行agent在代码冻结后解封/登记，不虚称另有独立保管员；未以解封题修改代码、提示或模型预算。
用户仍是最终独立人类审阅者；模型仅辅助整理，不能被记录为人类审阅者。

完整题面登记 question-registry-24.json SHA195b5134486dc5b15783fe8e665cc190abcaee439af8ca848e61f56388d5d39b；96行调度dry-run PASS，模型调用0。
实际分层：L1/L2/L3=6/8/10；事实3、机制4、比较4、时间5、定量4、规则4。不能称原建议的完全均衡24题，不重新贴难度标签凑数。
输出前预选自然12题：F1/F2、M3/H05、C3/H04、T2/H06、Q2/Q3、R1/R2，每能力两题；尚未执行或实现自然B入口。
保留题原mode为两题fixed_evidence、一题deterministic_rule、三题live_reference。

取得19份参考网页的正文/原始字节快照（公开资料17份＋RFC9110和Python3.12 asyncio两份），保存HTTP状态、URL、原始/正文/片段SHA与位置。
只算归档，不算合格证据覆盖：来源选择/片段完整性/公开18题完整答案标准仍待复核冻结。4次资料准备失败保存原样：gzip官方站403、唐代博物馆页429、伦敦票价页403、星铁官方动态页未观察到Firefly锚点。不改题、不以网页成功读取替代字段支持。

发现确定性入口限制：H01/H02虚构公告和H03给定棋盘均有完整source_packet；按真实file URI及原文SHA表达其出处时，冻结sources_for拒绝source_url（只接受HTTPS），3/3、模型调用0。
这是隔离底座的资料表示限制，不是模型理解/推理失败。不能给资料编造HTTPS网址、借无关官方URL承载题包，或解封后偷偷改sources_for/提示来变绿。
已向用户请求澄清先继续公开资料准备、还是先运行独立纯规划扫描并暂缓固定证据；未收到回复前只继续资料准备，不执行正式模型调用。
外部 model-ability-ab/ 保存unseal-report、原始holdout、24登记、96调度、provided-packet-preflight与两个snapshot目录；不在仓库记录解密密钥或明文答案。
当前结果：解封完整性CLOSED、24题登记/调度预检PASS；完整数据/固定证据实验尚未READY，RP-1仍NO-GO，能力判决NOT_OBSERVED。
