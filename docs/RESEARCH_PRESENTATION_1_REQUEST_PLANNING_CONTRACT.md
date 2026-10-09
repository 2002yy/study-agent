# RP-1 通用请求规划与路由适用域合同

本刀为合同与只读诊断，基线a49ef872；不切生产路由、模型协议、状态/schema、
预算、stop或发布权威。PROJECT_STATUS仍为唯一进度入口。

## 1. 三类失败与证据边界

上批真实S3自然Deep与重启恢复成功，字段资格没有成功：唯一supports0.6低于原0.7，
其余lead0.05，发布日期无绑定。强度门不放宽；Lookup已有版本/定位资格仍保留。
有可读来源、有绑定、对原问题有充分语义支持是三个不同结论。

G1流萤的第一条已记录失败是semantic_request_planning/question_id：
interpret输出被ResearchDecision.parse→questions拒绝，decision_admitted=false/FALLBACK。
候选读取阶段最终0reads/2searches/candidate_exhausted；之后原严格字段终态入口又返回
requested_claim_plan_unavailable。后者不是唯一根因；即使修RQ格式仍不能保证来源或handoff合格。
原快照没有解释器原始响应，因此不能猜测具体非法ID、自动替换其版本或给旧任务补资格。

W1围棋基本教学没有Standard/Deep，回答存在五个确定性图/规则/练习反例。
query_plan虽记录knowledge_kind=derivable，force_retrieval仍为true，实际2searches/0reads；
“没有Deep”不等于“无需搜索的教学路由已经正确”。当前既无棋盘状态合同，也无图/规则共源验证。
独立正确样件不修复原回答、不证明长期掌握。

## 2. 重用机制，不绑定主题

已有semantic_recovery ResearchEpisode/ResearchDecision能表达一般主题的1–6个RQ及≤5条
候选查询，且保持身份、绑定、私有地址等校验。这是策略建议，非证据或发布资格。
真正窄口是ChatService.complete_turn的官方字段fallback路径：requested_lookup_fields
依赖official_plan与LABELS，decide_lookup_terminal以这些字段决定VERIFIED/Standard handoff。
Standard计划、字段binder和Deep shadow随后也消费这个窄字段合同。
不能仅给字段planner加“配队”“围棋”词，或绕开第一道门把所有复杂文本送进Deep。

可复用所有权清单（基线a49ef872；本刀未改这些源码）：
`src/web/semantic_recovery.py::questions/ResearchDecision.parse/ResearchSemanticSession.interpret`
负责现有RQ协议与首次schema拒绝；
`src/application/chat_service.py::_official_publication_required/complete_turn`
决定官方字段fallback与记录Lookup终态；
`src/web/research/lookup_terminal.py::requested_lookup_fields/decide_lookup_terminal/load_standard_handoff`
负责窄字段计划与有资格的handoff；
`src/web/research/standard_plan.py::validate_plan`消费未解决字段；
`src/web/research/field_unit_shadow.py::declare/observe`只旁路记录已定义字段。
后续先查这些所有权与自本基线以来的增量，不重复全仓审计。

下一生产适配应重用现有RQ/来源/持久执行器，并把如下三个所有权分开：

| 合同 | 负责什么 | 不能证明什么 |
| --- | --- | --- |
| 原问题/RQ计划 | 保存目标、全量请求、条件、出处跨度与待验证问题 | 资料存在、答案已支持、自动Deep资格 |
| 证据资格 | 按主张类型验证身份/版本/适用条件/hash/span/来源独立性与支持关系 | 用户已掌握、审核即发布 |
| 路由/执行资格 | 判断本地验证、Lookup、Standard、Deep所需能力及剩余合法资源 | 长回答即深研、来源数量即完整回答 |

## 3. 一般请求单元（设计目标，尚未实施）

服务端冻结original_question及SHA、thread/turn/task身份、原条件与用户指定目标版本；
不从搜到的内容生成或删减需求。每单元保留原问题quote/span、类型、适用对象/条件、
所需验证能力、未确定部分以及server-owned稳定ID。类型按能力表达：
事实查证、机制解释、条件化比较、可复现计算、规则/程序执行、技能练习。
类型不是事实资格，领域专用来源适配器也不能给路由或发布自动盖章。

RQ身份方案：优先复用已持久RQ；新任务可采用严格结构化、有界的槽位提案，
服务端在完整验证后绑定稳定ID及引用映射，而非要求模型临时创造任意字符串ID。
不能对已有任意错误ID简单加rq-前缀、用数组位置替代丢失引用、删除非法行或重新归属事实。
任何协议适配必须保留原内容/全部引用、明确错task/RQ拒绝，以及旧版本恢复兼容；
尚未取得G1原始响应，因此这一方案不是已修复question_id的结论。

原问题完整保留并不证明分解完整；quote/span/ID通过只证明结构绑定。
未分类请求必须显式保留，超过现有1–6 RQ/≤5候选容量须保留backlog或报告规划能力不足，
不截断用户义务，不顺带增加模型/搜索额度。语义完整性仍NOT_EVALUATED，不能自评为已支持。

## 4. 路由规则与独立资格

简单已支持事实沿原正式路径完成，不无故升级。
稳定规则/可计算练习优先本地规则或计算器验证；证据缺口与规则执行失败分别记录。
涉及新版本、实测争议或外部事实时再要求查证，课程长短不能决定联网或Deep。
通用Standard入口需要合法原问题/RQ计划、正常结束且有可验证相关正文、真实未解决的
可行动义务、策略许可与可信预算/截止记录；仅有格式失败、提供商失败或无正文不足以升级。
自然Deep仍由Standard原资格、可行动关键缺口和持久trigger决定；不以用户提到“详细”
“Deep”或领域名直接创建child。取消、身份冲突、未知相关性和恢复不确定保持原fail-closed。

一般正文相关性不得冒充支持；每单元按照事实、计算、实测、社区观点等类别使用不同
合格条件和语义核验，不能复用“精确版本字符串出现”验证一切机制/优劣。
未支持/部分支持/冲突保持分别表达，原Deep-4A审计候选不获得发布权。

围棋等规则教学的图、动作和判定须来自同一结构化状态；通用要求同样适用于棋盘、
几何图、代码执行和实验组件。规则引擎验证合法状态/操作，模型解释绑定这些结果，
渲染器不从自由文本另猜图。未经交互验证不写掌握状态。生产UI/教学线独立接入。

## 5. 泛化验收纪律

按能力与失败种类预登记，而非为某角色/品牌/版本写捷径。
保留不同游戏、新实体的条件比较、设备实测、历史争议、工艺机制与规则/推导教学样本；
至少一种未参与实现的主题留作真正holdout。合成单测不是holdout效果验收。
检验：新实体改名/版本变更仍保留原义务；未知条件明确未解；相邻版本、错RQ、
无正文、私有地址、冲突、超预算与取消仍拒绝；简单VERIFIED不升级；
格式修复不改变事实；自然运行和恢复保持同一lineage。
域无关确定性测试只证明协议/诊断可复用；不能称为自然Deep或游戏/围棋产品PASS。

## 6. 本刀的可执行诊断

`tools/trace_research_request_routing.py --db <原DB> --turn-id <原turn> --out <新文件>`
只读观察原query_plan、语义规划错误序列、官方字段适用域、实际来源读取与记录路由。
保留第一条已记录规划错误与后续终态错误，不把后者冒充首断点。
对Deep复用原trace工具的terminal/publication/hash/state验证；不造RQ/child、补写字段、
调用模型/提供商或授予semantic/publication权威。缺失值保持NOT_RECORDED。
校验原query、thread/turn/run所有权；参数化SQL、DB/WAL fingerprint、拒绝输出覆盖DB及sidecars。
报告的decision_admitted仅为原记录，RQ相关性或读取计数不转换为支持资格。

集中回放上批5例原DB，不新增真实运行、不倒写旧证据。测试覆盖8种主题下的原内容保留、
两种独立阻断、既有泛化RQ协议与窄字段合同的差异、未知/错误身份/只读输出负控。
本阶段关闭后唯一下一生产切片：**现有语义规划器的原始响应观测与有界RQ身份绑定协议适配**，
先取得首次schema拒绝原始值，再以跨主题验证证明格式修复不改变原问题、RQ引用或事实。
通用handoff切换与语义支持资格另立门，尚未实施；预算、发布、UI与A学习持久状态冻结。

## 7. 本刀关闭证据

29定点PASS/7.10秒：8主题原问题/分层阻断、8主题既有RQ解析与窄字段区别、
读取/相关性不授予支持、缺值未知、错query/owner/run、参数化SQL、DB/sidecar覆盖拒绝与CLI只读。
命名L2 `research-request-routing-trace-v1`完整包含L1影响集，272PASS/100.83秒。
Ruff全src/tests/tools、新两文件format PASS，mypy current122/baseline128/resolved6、NEW0，
diff-check/scope PASS。无生产/shared model/persistence/cutover变化，不触发新L3；
8dcf的4311PASS6SKIP生产证据保留，不能声称新全量回归。

原五例只读trace经10项检查PASS，DB/WAL fingerprint、main DB SHA与原lineage不变。
G1确认为question_id先拒绝、零正文、窄字段无计划；W1合法semantic advice已admitted，
仍无支持/Lookup终态，证明“格式修好”不能解决全部领域/教学问题。
本刀无新provider、run或server，无事后给旧链声明字段、无push/PR/CI；
contract/trace LOCAL CLOSED，通用生产路由和领域产品仍未资格化，RP-1 NO-GO。
外部`r6c-request-planning-contract/`保存五trace、replay.json、验证日志和最终closeout。
此处8主题为确定性协议对照，未运行独立真实holdout，不把它们作为效果泛化证据。
