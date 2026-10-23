# Study Agent 当前状态

> **唯一进度入口**
> 更新：2026-10-18（补充要求显示它实际改了什么：只认创建者、不复述原问题；下一刀改为助手增量回复）
> 产品定义：**Study Agent 是体验接近 GPT-6 Chat 的智能聊天与研究 Agent。自然聊天、自主研究、持续交互、智能 UI、统一多模态、工具执行是六项通用核心能力；长期学习与教学是其上的专业场景。**

本文件只维护当前权威状态、可复核边界和唯一下一门。2026-10-06 本次收敛前的完整状态原样归档到 [`archive/PROJECT_STATUS_PRE_177_FINAL_REVIEW_2026-10-06.md`](archive/PROJECT_STATUS_PRE_177_FINAL_REVIEW_2026-10-06.md)；更早历史继续由既有 archive 与 Git 历史持有。

## 0. Current Handoff（cold-start 入口）

**2026-10-23 CLI候选#280主线重绑（第二次，面向当前main）。** 初始head 15d5bd62b99ad9418b6a87aa55202700c4b1a501，
本次显式吸收已提交main 42992932e115568be54d6e85a34f4b68335d84ea（#255合并后），不读取其他工作树WIP。
base已从 codex/studyctl-ci-live-20261021 改为 main：原base下 `refs/pull/280/merge` 只证明本片能合进#279分支，
不构成对main的证据，故不能借用旧绿灯。
源码冲突仅 docs/PROJECT_STATUS.md（追加式，双方新交接全部保留），tools/ci_scope.py、tests/test_ci_scope.py、
tests/stage_gates.json 由Git自动合并，已两向核对：main侧147条/#280侧154条 -> 合并后157条，双方零丢失、悬空0；
ci_scope main侧25条/#280侧36条 -> 39条，双方零丢失、悬空0。
合并树组成精确等于 main 11 文件 + #280 20 文件，无额外增删；CLI 八片（#270/#273/#274/#276-#279/#280）逐片改动文件 0 缺失。
本提交只补交接，不重复已被CI覆盖的相同测试；新head必须重新绑定CI，旧绿不授予新提交。

**2026-10-23 CLI候选#280主线重绑。** 初始head e9886e00a8eb5a74a3dd1f46e458881c6f257f57，
显式吸收已提交 0fa9b6b6d4ab38129cc3f002bb21c535e3a7887d（refs/heads/codex/studyctl-ci-live-20261021）；不读取其他工作树WIP。
远端main已由2b3e2764前进到ee89db18，可信采集对旧PR base/当前main不一致正确BLOCKED，
不是网络/代理缺陷，不放宽版本一致性门。源码冲突只允许交接文档，双方新交接保留；
保留本片独立功能；吸收冻结父片的目录游标存在性修复与已提交main，不吸收兄弟分支。
已完成命名studyctl L1 422 PASS/1 SKIP（既有Windows symlink权限限制）、
工具mypy/Ruff/格式/diff通过；受测代码提交aae8da99045fcbd2dd4428d46a2e85a9ef4ef1fb。
实际子进程核验 11类断言通过，输入hash不变；构造GitHub记录与真实只读采集分别标记，不授予merge_authorized。
src树与已提交main完全一致，统一复用本批src mypy 122/128 NEW0，未放宽baseline。
本提交只补交接，src/tools/tests树与受测代码一致，不重复相同源码L1或本地L3。
新head必须重新绑定CI/完整审阅；旧绿灯不授予新提交。
一次真实GitHub只读采集：main ee89db18edb23da9cd35ab3a7afe6ac963b3319b，观察结果PASS，11次API；不是本分支CI或CLI全线合并许可。
验证目录 D:/study-agent-validation/studyctl-live-rebind-20261023/280/。
下一动作：逐片检查现有CLI候选完整审阅和exact-head CI，成熟片依赖顺序合main并重绑后继；不再增加诊断命令。完整真实研究run与质量验收仍待样本，不用构造数据代替。


**2026-10-23 CLI候选#279主线重绑。** 初始head c2b5822e34a8360e88e4df84de566083e387f934，
显式吸收已提交 59d27840e516ad90b7e44fad550f1125b3fb585c（59d27840e516ad90b7e44fad550f1125b3fb585c）；不读取其他工作树WIP。
远端main已由2b3e2764前进到ee89db18，可信采集对旧PR base/当前main不一致正确BLOCKED，
不是网络/代理缺陷，不放宽版本一致性门。源码冲突只允许交接文档，双方新交接保留；
保留本片独立功能；吸收冻结父片的目录游标存在性修复与已提交main，不吸收兄弟分支。
已完成命名studyctl L1 393 PASS/1 SKIP（既有Windows symlink权限限制）、
工具mypy/Ruff/格式/diff通过；受测代码提交2bea2414932487b7f4abda016c1304b3247e4840。
实际子进程核验 8类断言通过，输入hash不变；构造GitHub记录与真实只读采集分别标记，不授予merge_authorized。
src树与已提交main完全一致，统一复用本批src mypy 122/128 NEW0，未放宽baseline。
本提交只补交接，src/tools/tests树与受测代码一致，不重复相同源码L1或本地L3。
新head必须重新绑定CI/完整审阅；旧绿灯不授予新提交。
验证目录 D:/study-agent-validation/studyctl-live-rebind-20261023/279/。
下一动作：当前提交推送后仅查一次CI并继续后继独立候选；远端新head门与审阅未收口前不合main。


**2026-10-23 CLI-05B混合run失败出口回归。** 只绑定已提交#277核心修复；命令层补push/旧head两种混合记录用例，要求当前PR已知失败经入口保留FAIL/4、完整记录与被检head，merge_authorized仍false。输入只读，工具自身SHA与目标SHA继续分列；不发起gh/网络、不改workflow或产品src。下一门命名studyctl与实际CLI回执，CI只留一次观察不等完成。


**2026-10-23 CLI候选#278主线重绑。** 初始head fddeae9a502b9516ad48ce8240a7c3a0a4d868e3，
显式吸收已提交 7f3381a73539fafde3b86cea1e472bd09e730d61（refs/heads/codex/studyctl-ci-evidence-20261021）；不读取其他工作树WIP。
远端main已由2b3e2764前进到ee89db18，可信采集对旧PR base/当前main不一致正确BLOCKED，
不是网络/代理缺陷，不放宽版本一致性门。源码冲突只允许交接文档，双方新交接保留；
保留本片独立功能；吸收冻结父片的目录游标存在性修复与已提交main，不吸收兄弟分支。
已完成命名studyctl L1 351 PASS/1 SKIP（既有Windows symlink权限限制）、
工具mypy/Ruff/格式/diff通过；受测代码提交be813aadb7424a52722c2d533a7dfa3fc065dde6。
实际离线核验 8类断言通过，输入hash不变；离线快照/步骤回执只证明所给记录，不能授予合并资格。
src树与已提交main完全一致，统一复用本批src mypy 122/128 NEW0，未放宽baseline。
本提交只补交接，src/tools/tests树与受测代码一致，不重复相同源码L1或本地L3。
新head必须重新绑定CI/完整审阅；旧绿灯不授予新提交。
验证目录 D:/study-agent-validation/studyctl-offline-rebind-20261023/278/。
下一动作：当前提交推送后仅查一次CI并继续后继独立候选；远端新head门与审阅未收口前不合main。


**2026-10-23 CLI-05A失败按单条run归属修复。** 审阅P2确认：旧实现用全列表身份一致性决定失败归属，导致当前head的PR失败被无关push/旧head记录降成BLOCKED。改为逐run同时满足已匹配PR元数据、exact head、pull_request、completed及失败结论才FAIL/4；无关记录仍保留gap，不能掩盖已知失败，也不能将外部失败归给成功PR。新增8项回归，5个混合失败用例在旧代码均FAIL（负控），修复后核心32项通过。离线真实性/时效/required policy缺口与merge_authorized=false不变。一次错误工作目录的pytest收集失败已改从目标工作树运行，不改生产代码掩盖环境问题。下一门：本片完整命名L1与实际模块回执，再推送；后继CLI只绑定冻结提交。


**2026-10-23 CLI候选#277主线重绑。** 初始head 6835a2b75300035a6c07ebd00e70e1e5ddaa2ba3，
显式吸收已提交 200fd25029a9b966cce68094b833359c6c87de86（200fd25029a9b966cce68094b833359c6c87de86）；不读取其他工作树WIP。
远端main已由2b3e2764前进到ee89db18，可信采集对旧PR base/当前main不一致正确BLOCKED，
不是网络/代理缺陷，不放宽版本一致性门。源码冲突只允许交接文档，双方新交接保留；
保留本片独立功能；吸收冻结父片的目录游标存在性修复与已提交main，不吸收兄弟分支。
已完成命名studyctl L1 336 PASS/1 SKIP（既有Windows symlink权限限制）、
工具mypy/Ruff/格式/diff通过；受测代码提交95d8e7c0c3ba87eb7dc65e564befbef832218bae。
实际离线核验 7类断言通过，输入hash不变；离线快照/步骤回执只证明所给记录，不能授予合并资格。
src树与已提交main完全一致，统一复用本批src mypy 122/128 NEW0，未放宽baseline。
本提交只补交接，src/tools/tests树与受测代码一致，不重复相同源码L1或本地L3。
新head必须重新绑定CI/完整审阅；旧绿灯不授予新提交。
验证目录 D:/study-agent-validation/studyctl-offline-rebind-20261023/277/。
下一动作：当前提交推送后仅查一次CI并继续后继独立候选；远端新head门与审阅未收口前不合main。


**2026-10-23 CLI候选#276主线重绑。** 初始head 8f19c60cca76e9d3325d9fe5c084986fa6ad0567，
显式吸收已提交 11cc5327ed0594a5856935951ec465ddf777df11（11cc5327ed0594a5856935951ec465ddf777df11）；不读取其他工作树WIP。
远端main已由2b3e2764前进到ee89db18，可信采集对旧PR base/当前main不一致正确BLOCKED，
不是网络/代理缺陷，不放宽版本一致性门。源码冲突只允许交接文档，双方新交接保留；
保留本片独立功能；吸收冻结父片的目录游标存在性修复与已提交main，不吸收兄弟分支。
已完成命名studyctl L1 304 PASS/1 SKIP（既有Windows symlink权限限制）、
工具mypy/Ruff/格式/diff通过；受测代码提交3acb4532b4226e84291f7f058575bb7343f3492d。
实际CLI 4类命令断言通过，输入hash不变；SQLite/修改记录为构造数据，历史B5不是新真实研究。
src树与已提交main完全一致，统一复用本批src mypy 122/128 NEW0，未放宽baseline。
本提交只补交接，src/tools/tests树与受测代码一致，不重复相同源码L1或本地L3。
新head必须重新绑定CI/完整审阅；旧绿灯不授予新提交。
验证目录 D:/study-agent-validation/studyctl-followon-rebind-20261023/276/。
下一动作：当前提交推送后仅查一次CI并继续后继独立候选；远端新head门与审阅未收口前不合main。


**2026-10-23 #274同步冻结分页修复。** 固定自身e9f09616，吸收已提交父片
11bb263a4bf21cb907a28f4c833ff52bfac9a28d，仅交接冲突保留双方，SQLite查询/回归测试自动合入。
src与main仍相同，不借父片旧全门；catalog/research/recording/CLI直接消费者
73 PASS/1 SKIP，四工具mypy/Ruff/格式/diff通过，受测组合bebf6b7f97334690b8bd5d71c06d669cc3dfe24f。
实际CLI四例跨父子分支证明未知边界2/合法末尾0，SQLite字节不变。
本提交只补交接，src/tools/tests与受测树相同；推送新head不等CI，不重复L3。
旧287全门只属于审阅修复前代码；此小修复按直接影响集验证，新headCI/审阅前不合main。
证据 D:/study-agent-validation/studyctl-research-rebind-20261023/artifact-review-sync/。

**2026-10-23 #273分页审阅修复。** finding4333785509 有效：同快照摘要但不存在的after
会跳过真实run或返回空成功页。现在在同一内存快照以BINARY精确查边界，必须唯一存在才分页；
不含边界的第一页不受影响，未知边界按原InvalidCursor映射参数错2，输入不变/不回显游标。
三种边界负控（不存在/超出末尾/错误大小写）在旧代码均实际失败，修复后catalog/research/CLI
直接影响集57 PASS/1 SKIP；三工具mypy/Ruff/格式/diff通过，src未变且122/128 NEW0复用。
先前271项门属于修复前版本，不借给新head；此有界小修复仅跑直接影响集，不重复L3。
证据 D:/study-agent-validation/studyctl-research-rebind-20261023/catalog-review-fix/。
下一动作：推送本片并将同一冻结修复同步#274，重跑直接消费者；新head CI/审阅未完成不合main。


**2026-10-23 CLI候选#274主线重绑。** 初始head 14087de6e614b2028752b4a8cd2c19a050961247，
显式吸收已提交 7cd4ded5e938074f45b2e31cc9e5daf1a7e687d1（refs/heads/codex/studyctl-research-catalog-20261021）；不读取其他工作树WIP。
远端main已由2b3e2764前进到ee89db18，可信采集对旧PR base/当前main不一致正确BLOCKED，
不是网络/代理缺陷，不放宽版本一致性门。源码冲突只允许交接文档，双方新交接保留；
生产研究/执行逻辑保持自身冻结实现，新main的DeepSeek/回答模块按已提交源码合入。
已完成命名studyctl L1 287 PASS/1 SKIP（既有Windows symlink权限限制）、
工具mypy/Ruff/格式/diff通过；受测代码提交a9e7c6c904ed3b9fe8e9de34795d5f71f1603c60。
src树与已提交main完全一致，统一复用本批src mypy 122/128 NEW0，未放宽baseline。
本提交只补交接，src/tools/tests树与受测代码一致，不重复相同源码L1或本地L3。
新head必须重新绑定CI/完整审阅；旧绿灯不授予新提交。
验证目录 D:/study-agent-validation/studyctl-research-rebind-20261023/274/。
下一动作：当前提交推送后仅查一次CI并继续后继独立候选；远端新head门与审阅未收口前不合main。


**2026-10-23 CLI候选#273主线重绑。** 初始head 15c6b2d8e410266829a94181769c17ba42aa83a7，
显式吸收已提交 c955f34aaef57f0958e47b23b2348d45a7121070（refs/heads/codex/studyctl-research-inspect-20261021）；不读取其他工作树WIP。
远端main已由2b3e2764前进到ee89db18，可信采集对旧PR base/当前main不一致正确BLOCKED，
不是网络/代理缺陷，不放宽版本一致性门。源码冲突只允许交接文档，双方新交接保留；
生产研究/执行逻辑保持自身冻结实现，新main的DeepSeek/回答模块按已提交源码合入。
已完成命名studyctl L1 271 PASS/1 SKIP（既有Windows symlink权限限制）、
工具mypy/Ruff/格式/diff通过；受测代码提交bea35939164ad0aa6fcb37c8033ac587c885bd54。
src树与已提交main完全一致，统一复用本批src mypy 122/128 NEW0，未放宽baseline。
本提交只补交接，src/tools/tests树与受测代码一致，不重复相同源码L1或本地L3。
新head必须重新绑定CI/完整审阅；旧绿灯不授予新提交。
验证目录 D:/study-agent-validation/studyctl-research-rebind-20261023/273/。
下一动作：当前提交推送后仅查一次CI并继续后继独立候选；远端新head门与审阅未收口前不合main。


**2026-10-23 CLI候选#270主线重绑。** 初始head 3741298283b2b8c4421f857eb168a1cfe3b461cf，
显式吸收已提交 ee89db18edb23da9cd35ab3a7afe6ac963b3319b（refs/remotes/origin/main）；不读取其他工作树WIP。
远端main已由2b3e2764前进到ee89db18，可信采集对旧PR base/当前main不一致正确BLOCKED，
不是网络/代理缺陷，不放宽版本一致性门。源码冲突只允许交接文档，双方新交接保留；
生产研究/执行逻辑保持自身冻结实现，新main的DeepSeek/回答模块按已提交源码合入。
已完成命名studyctl L1 255 PASS/1 SKIP（既有Windows symlink权限限制）、
工具mypy/Ruff/格式/diff通过；受测代码提交cbda32ef17d1e51105ca37d3a93776fdc6d63f20。
src树与已提交main完全一致，统一复用本批src mypy 122/128 NEW0，未放宽baseline。
本提交只补交接，src/tools/tests树与受测代码一致，不重复相同源码L1或本地L3。
新head必须重新绑定CI/完整审阅；旧绿灯不授予新提交。
验证目录 D:/study-agent-validation/studyctl-research-rebind-20261023/270/。
下一动作：当前提交推送后仅查一次CI并继续后继独立候选；远端新head门与审阅未收口前不合main。
**2026-10-20 本轮第二片：#257有界入口审阅修复。** 原head80912bb0281a6e00ed997f6f96c136a5628e097b / CI39389277406 SUCCESS有未解决审阅PRRT_kwDOSYWoX86uPjuj：FastAPI先解析正文再进入开关。新增5项负控在旧代码实际FAIL（日志D:/study-agent-validation/events-ingress-negative.log）；现不自动绑定请求model，先检查enabled，再以4KiB总量/2秒总读取期限读取JSON并验证身份字段，然后逐操作授权。默认关闭不读取正文；Content-Length非法400、超大413，实际分块累计也受限，不信伪造长度，停滞408；所有非法请求均不调用授权/额度/SDK。保留拒绝客户端历史/工具/预算/证据和显示流/取消/清理协议，自身30 PASS/21.36s，最终命名L1 conversation_events_routes **596 PASS/152.17s**，mypy122/128 NEW0、Ruff/format/diff-check PASS，候选密钥与新head CI以发布结果恢复。此片仅4文件增量，不改生产注册、schema、发布权威或用户配置，无真实付费调用、无本地L3。

本轮第一片#249已重绑main069fc126，merge450614da及候选1c1c3a69234aa5380436ce7bf118d3ba5dac3e3a，命名L1 456 PASS/123.69s、mypy NEW0、Ruff/diff-check/secret findings0，7文件增量；PR base main，exact-head pull_request CI39421932157后台。root main已ff到069fc126且保留4个原ZIP。#256旧CI39388736380已定位：frontend 468 PASS/1 FAIL，ReadingWorkspace.test.tsx:157本地行跳转焦点期望line2但停line1；frontend代码不在该PR改动内，故记录相邻阻塞而非顺手改阅读功能或收窄CI规避失败。诊断D:/study-agent-validation/owned-binding-frontend-ci.log；gh大包下载4分钟无输出，终止已核实的该下载进程后改用带连接/读取timeout的requests下载成功（仅打印出现GBK编码错误，日志完整已保存），未改网络配置。#256不合并，真实模型质量/3–5秒首答/生产切换继续未验收。下一独立片：先处理#249最新审阅/CI并顺序整合自身#251，再补API宿主的操作生命周期；不等待CI才开发，不将旧head绿灯授予修复head。

**2026-10-20 本轮两片发布收口。** #256（owned binding）head efcf71be937d1cf0084cb836d690257c463a0fc2 / PR CI39388736380仍后台；#257（可选SSE API）实现head358f330962bc9dc2b5d03abc5f0fa7175101e5cc / PR CI39389109743后台，两PR暂无审阅thread，本段仅文档随新head触发CI，不借旧head绿灯。#257命名L1 580 PASS/142.97s、mypy122/128 NEW0、Ruff/format/diff-check PASS、候选secret findings0，7文件独立增量；两新功能工作树代码冻结且显式提交，未取其他窗口WIP。#248已合main069fc1267010580c2c74ba3c1bb92f0e459458a5，exact-main push CI39388835099 SUCCESS。根工作树仍在8a66eccf（仅4个原未跟踪ZIP）；Git HTTPS间歇TLS握手失败，功能分支已用命令级schannel/HTTP1.1成功推送，根main fetch尚未成功，未改全局配置。下一轮先恢复fetch并ff根main，再逐片重绑自身#249回答runner到main并补可选API宿主结算；新#256/#257待exact-head CI/审阅及各自父片成熟后再顺序合入，不等待CI才开发。

**2026-10-20 CL-1I-2：默认关闭的可选SSE API（本轮第二新功能片）。** branch codex/conversation-events-api-20261020，基于自身第一片#256最终efcf71be937d1cf0084cb836d690257c463a0fc2（实现45e10ad0，后续仅文档），未取其他窗口WIP。create_conversation_events_router不自动注册生产app；宿主必须显式提供start_run、逐操作authorize和on_closed，并在服务器侧启用。POST /chat/threads/{thread_id}/turns/{turn_id}/agent-events只接受operation_id，禁止客户端历史/工具/预算/证据字段；默认404、未授权403、过期owned操作409、Last-Event-ID重放409，均在准入/SDK前拒绝。SSE保持provisional/unverified；正常结束、发送头失败、首帧断线和ASGI取消均关闭自有会话并调用一次宿主结束回调；清理等待上限1秒，超时取消而非无限持有HTTP。宿主仍负责原操作CAS结算、费用和正式发布，不在此写ChatTurn或放行证据门。

最终命名L1 conversation_events_routes **580 PASS/142.97s**（自身14项真实ASGI/SDK假HTTP），mypy122/128 NEW0、Ruff/format/diff-check PASS；生产代码和门配置已冻结，文档更新不重跑联合门。无真实凭据/网络/付费调用、无生产入口切换/持久schema变化，无本地L3。候选SHA由本段提交恢复，PR和密钥检查另记发布结果。#256 head efcf71be / pull_request CI39388736380后台；#247已合main8a66eccf67993673c88455b97f096d5aabd634e8，exact-main push CI39386079662 SUCCESS；#248重绑main head035cffa5bb68ce81839b74d6b5be4f77215f2809，命名L1 299 PASS、mypy NEW0，exact-head PR CI39388341261 SUCCESS且无审阅finding后已squash合入。根main原有4个未跟踪ZIP保留。唯一下一执行片：逐片重绑自身已通过的回答生成候选到main，同时为可选API宿主补持久操作准入/结束结算；在这些边界和真实模型资格通过前不注册生产路由，不声称前3–5秒首答或完整产品验收。

**2026-10-20 CL-1I-1最终候选。** owned绑定最终命名L1 conversation_owned_binding **566 PASS/136.06s**，自身14项（含SQLite WAL并发快照、只读不创建/不写入、真实SDK假HTTP绑定与取消），mypy122/128 NEW0、Ruff/format/diff-check PASS、候选secret findings0。初次562 PASS/4 FAIL仅为测试路径/序列化假设，修复测试后14项及最终566项均通过，生产实现未因该错误更改。初始自身#255后合main8a66eccf，集成基线907d6600只恢复2个已合main上下文文件，逐字校验一致；新实现审阅范围907d6600..候选为7文件，PR相对#255另含这2个不变main依赖，无其他窗口WIP。候选SHA以本段提交恢复。下一片可选API基于此冻结成果继续，只有身份请求、显式宿主授权/结束回调，默认关闭、不自动注册生产app，不等CI才推进。

**2026-10-20 CL-1I-1：服务端owned聊天操作绑定（本轮第一新功能片）。** branch codex/conversation-owned-binding-20261020，初始自身#255冻结15c10c03，合入自身已发布main8a66eccf后得到基线907d6600；仅恢复已合main的conversation_decision_context及其测试，二者与main逐字一致，loop保留自身已冻结可选生成器/handler实现，未取其他窗口WIP。SQLiteChatSnapshotReader通过mode=ro、query_only和单BEGIN读取thread/current/最近6条completed历史，关闭连接、不创建数据库或做恢复写入；WAL并发取消负控证明三次SELECT同快照，下一次读取能看到取消。OwnedConversationBinding只接thread/turn/operation身份，复用既有快照projection检查，服务器回调提供工具/研究/证据/额度与模型准入，执行前持续刷新，不接收客户端历史/预算/工具目录。此处不创建/完成/释放ChatTurn，不改正式发布门；调用者仍负责身份授权与操作生命周期。

自身14项真实SQLite/SDK假HTTP已PASS/6.85s，mypy122/128 NEW0、Ruff/format PASS；初次联合562 PASS/4 FAIL是测试假设错误（decision wire history为role/content对象、upsert不写cancel字段），现改走现有request_turn_cancel CAS并验证accepted，生产代码未改变；最终命名门执行中，结果另记。未改schema/共享core模型/生产路由，无真实网络/付费调用，无本地L3。下一独立片：默认关闭、显式授权且只读身份请求的可选SSE router，由宿主提供操作结束回调，继续保持provisional/unverified。
**2026-10-23 #257 合入前归档 #275 交接记录。** #275（codex/studyctl-event-pages-20261021，head 44b16f155）与 #280 不是祖先关系，其功能由 #276–#280 吸收并已随 #280 的合并提交 e4a3c779 进入 main；按superseded 收口，保留其原交接记录如下，便于追溯当时的门禁与skip 口径。


**（归档）以下为 #275 的交接记录。其功能已被 #276–#280 吸收并随 #280 合并进入 main（合并提交 e4a3c779）；#275 与 #280 不是祖先关系，故按superseded 收口，保留原记录备查。**
**2026-10-23 CLI候选#275主线重绑。** 初始head 9bd92f4f60b99ab74327cac4cc77bcd8d4aee8bf，
显式吸收已提交 11cc5327ed0594a5856935951ec465ddf777df11（11cc5327ed0594a5856935951ec465ddf777df11）；不读取其他工作树WIP。
远端main已由2b3e2764前进到ee89db18，可信采集对旧PR base/当前main不一致正确BLOCKED，
不是网络/代理缺陷，不放宽版本一致性门。源码冲突只允许交接文档，双方新交接保留；
保留本片独立功能；吸收冻结父片的目录游标存在性修复与已提交main，不吸收兄弟分支。
已完成命名studyctl L1 306 PASS/1 SKIP（既有Windows symlink权限限制）、
工具mypy/Ruff/格式/diff通过；受测代码提交6aa541a4085fc2842b4668c485c9a0bf4924016f。
实际CLI 7类命令断言通过，输入hash不变；SQLite/修改记录为构造数据，历史B5不是新真实研究。
src树与已提交main完全一致，统一复用本批src mypy 122/128 NEW0，未放宽baseline。
本提交只补交接，src/tools/tests树与受测代码一致，不重复相同源码L1或本地L3。
新head必须重新绑定CI/完整审阅；旧绿灯不授予新提交。
验证目录 D:/study-agent-validation/studyctl-followon-rebind-20261023/275/。
下一动作：当前提交推送后仅查一次CI并继续后继独立候选；远端新head门与审阅未收口前不合main。


**2026-10-20 CL-1H-2：单次消费的显示进度流（本轮第二新功能片）。** branch codex/conversation-progress-stream-20261020，初始固定自身服务756f0eaa，已ff绑定其最终文档父片#254 dd17b5f11564159dd731421807bd8b0c846d57ac（仅交接，无生产变化）；未取其他窗口WIP。conversation_progress_stream立即claim原ConversationLoopSession，支持未读close、单次消费、拒绝并发读取、取消传播与内层资源释放。只投影计划focus、阶段/最终答案、澄清、工具状态和终态；不输出模型reason、原始工具正文、prompt/history或证据摘要。所有帧固定unverified/provisional，answered终态不授予发布/证据权威。root request_id关联同一run，sequence与哈希event_id仅本流显示去重，不提供持久恢复/重放权限；SSE采用单行JSON数据，正文换行不能注入event/data字段。缺失终态、源异常、SDK清理失败输出一个脱敏failed终态，调用者取消仍传播。

最终命名L1 conversation_progress_stream **534 PASS/143.66s**（自身10项，含真实SDK服务完整初步→工具→最终显示），mypy122/128 NEW0、Ruff/format/diff-check PASS，候选密钥扫描另见发布结果。当前仅应用层DTO/SSE编码，不注册HTTP路由或写ChatTurn，不切生产聊天、费用或证据/发布权威，无真实网络/付费模型、无本地L3。候选SHA以本段提交恢复，下一片：把显式选择服务与owned聊天操作绑定到可选API入口，沿用原证据/发布门。

本轮#246在e663d9a6 / CI39377648481 SUCCESS / 无finding后合main b6aee2b72e8904e0a382bd9a93469168f48bf71b，exact-main CI39381453432 SUCCESS，根main已ff且4外部ZIP保留。#247重绑main L1 413 PASS、mypy122/128，但head2c681ed6缺失新CI；追加交接head3bfefb2c已推送触发synchronize，必须绑定新head CI，不能借旧3390fafd绿灯。#253 URLfinding4321928343已修复并resolve，head835e0aad / CI39381952927后台、L1 515 PASS；#254服务headdd17b5f1 / CI39382951751后台、L1 524 PASS。两新功能片只基于自身冻结成果，不等CI才开发。

**2026-10-20 CL-1H-1最终候选。** DeepSeek可选应用服务已吸收自身#253修复835e0aad（merge756f0eaa，仅交接冲突保留双方），最终命名L1 conversation_deepseek_service **524 PASS/140.58s**，自身9项SDK假HTTP，mypy122/128 NEW0、Ruff/format/diff-check PASS、候选secret findings0；相对835e0aad独立7文件，候选SHA以本段提交恢复，未取其他窗口WIP。初始519仅为旧父片的初步证据，新联合门已覆盖URL canonical真实SDK回归。创建/claim/关闭未读run不建SDK，取消/关闭/终态都释放自有客户端，共享模型准入不因新service/session重启而自动重置；默认生产ChatService/HTTP不变。下一片安全进度流基于此自身冻结代码继续，本轮不等CI。

**2026-10-20 CL-1H-1：DeepSeek可选应用服务（本轮第一新功能片）。** branch codex/conversation-deepseek-service-20261020，初始固定自身#253 7c39a460，发布前显式吸收本轮URL修复835e0aad；未取其他窗口WIP。DeepSeekConversationService.start把同一model admission用于决策及回答，返回单次消费ConversationLoopSession；只创建/claim/关闭未读run不会创建SDK或发送请求，实际消费时才进入owned DeepSeek会话并受控执行loop。阶段后关闭/调用者取消按内层loop→SDK顺序释放，终态返回前owned SDK已关闭，保留原脱敏/unknown/去重回执；只在应用层显式调用，不改ChatService/HTTP生产入口或发布权威。宿主继续负责所有权快照、工具权限与真实费用授权。

初步命名L1 conversation_deepseek_service **519 PASS/125.32s**（自身9项真实SDK假HTTP），mypy122/128 NEW0、Ruff/format PASS；包括初步→工具→完整最终输入、未读关闭、阶段后关闭、取消SDK、过期不发送、重启同request不重复扣费、provider失败和单次claim。该初片本地冻结后吸收父片已验515项URL修复，再跑最终联合门；旧7c父片结果不授予最终候选。无真实凭据/网络/付费请求、生产切换或本地L3。下一独立片：消费此服务回执的安全进度投影，分离阶段答案、工具状态与终态，始终保留provisional/unverified边界。
**2026-10-20 #253 审阅修复 / DeepSeek URL规范化。** finding4321928343有效：原校验rstrip后允许URL却存原字符串，SDK可能发/v1//chat/completions。新增4组尾斜杠负控在旧7c39a460均实际FAIL，保留日志D:/study-agent-validation/deepseek-url-negative.log；现冻结settings在验证后存canonical rstrip值，真实SDK假HTTP新增双斜杠路径回归，实际线缆路径保持/v1/chat/completions。最终命名L1 conversation_deepseek_session **515 PASS/151.91s**，mypy122/128 NEW0、Ruff/format/diff-check PASS；无SDK真实调用/配置修改/生产切换，无本地L3。新head以本段提交恢复，旧7c39a460 / CI39377762994 SUCCESS不能授予修复head。修复将显式带入本轮DeepSeek应用服务与进度流两个自身独立片，未取其他窗口WIP。

**2026-10-20 本轮两片最终交付候选 / 仅DeepSeek。** 第一片#252 head2b9b9f5bc389d5e5e148aff91ed3c3f8c41423b3 / pull_request CI39377002020后台，命名L1 495 PASS/128.64s，暂无finding。第二片固定该自身父片，最终命名L1 conversation_deepseek_session **510 PASS/134.10s**，自身15项真实SDK/假HTTP PASS，mypy122/128 NEW0、Ruff/format/diff-check PASS、secret findings0，候选SHA以本段提交恢复；7文件独立增量，无其他窗口WIP。初次509 PASS/1 FAIL是SDK空header的断言错误，已修为验证不继承外部组织/项目值，并完成15项与最终510项复验；不是生产逻辑故障或未知原因，不触发全量。测试不使用真实凭据或网络，用户配置未改，未做真实付费/模型质量/首答延迟验收；生产聊天未切换，无本地L3。

本轮#244在0f914244 / CI39296775208 SUCCESS无finding后合main5cd917ad，#245在226c0d31 / CI39376484599 SUCCESS且两finding已解决后合main9ae37d4caac71935b75fc85c1b93c75502e466e9；前main5cd917ad push CI39376017114 SUCCESS，新main push CI39377570868后台。#246已重绑该main，heade663d9a654b4dca3b139aa6da704de632ca2e212 / CI39377648481后台；生产/测试树与已验证d7102e3a完全相同，复用277 PASS/94.49s且不借旧CI授予新head。先前凭据问题已由用户“只要deepseek”明确解除；当前仅DeepSeek配置与端点，不使用OpenAI服务，不再阻塞。唯一下一执行片：将DeepSeek会话接入可选服务入口并验证请求生命周期，继续按最新head审阅/CI逐片合main。

**2026-10-20 CL-1G-2：DeepSeek专属SDK会话（本轮第二新功能片）。** branch codex/conversation-deepseek-session-20261020，固定base自身#252 2b9b9f5bc389d5e5e148aff91ed3c3f8c41423b3，不取其他窗口WIP。用户已选定仅DeepSeek，先前凭据问题已解除，不选择或使用OpenAI服务。DeepSeekConversationSettings只读取显式传入的DEEPSEEK_API_KEY、DEEPSEEK_MODEL_FLASH/PRO_NAME与DEEPSEEK_BASE_URL映射；没有OPENAI_*或通用model回退，密钥repr隐藏，endpoint仅HTTPS api.deepseek.com根/v1。owned单次异步session不触碰共享客户端，默认HTTP关闭重定向/环境代理，显式空SDK组织/项目/webhook避免继承OPENAI_*元数据；关闭后已有transport/generator也不能发送。提供同一transport给决策和BoundedAnswerGenerator，不切生产路由。

使用真实SDK与httpx.MockTransport（内存假HTTP）验证序列化、完整两次调用loop、503仅一次、不自动重试、期限取消、拒绝跨提供方重定向与客户端关闭；所有配置/凭据均为显式fake，未发起真实网络/付费请求，不修改用户凭据。初始断言误把“无外部组织值”写成“完全无header”：SDK对显式空字符串发送空header，现断言其值为空且不继承foreign环境值，15项自身用例全部PASS/6.87s；生产代码未因此改变。mypy122/128 NEW0，Ruff/format PASS，最终命名门发布前另记。精确登记模块/测试CI与消费者，无前缀通配或强制门缩小，无本地L3。下一片：DeepSeek会话与生产服务的显式选择接线及观察回执，真实模型质量/首答延迟和货币费用仍另有验收门。

**2026-10-20 CL-1G-1：仅DeepSeek传输适配器（本轮第一新功能片）。** 用户已明确“不用openai，只要deepseek”，覆盖此前待选状态；不使用OpenAI服务/配置，不发起真实付费调用。branch codex/conversation-model-transport-20261020，固定base自身#251 9f0c1f14b8b8702bcc5e6b28205798604590efe7，不取其他窗口WIP。DeepSeekConversationTransport接受宿主注入客户端和model，统一支持现有ModelDecisionRequest/ModelAnswerRequest；决策JSON object、回答正文，固定thinking disabled、stream false、每次SDK副本max_retries=0，验证预算参数并拒绝无法禁用重试的客户端。只收单条stop完成且无refusal/tool_calls的非空有界正文，截断/多choice不自动修复或重试；沿用原runner的准入/期限/过期与错误脱敏。本模块不读环境、不创建客户端、不授予费用/证据/发布权威；下一片才做DeepSeek专属配置及owned SDK生命周期，明确禁止OPENAI_*回退。精确登记新模块和测试CI路径。命名L1 conversation_deepseek_transport **495 PASS/128.64s**，mypy122/128 NEW0、Ruff/format/diff-check PASS、secret findings0；候选SHA以本段提交恢复，未改生产聊天/业务schema，无本地L3。

本轮另已合#244到main5cd917ad，#245重绑head226c0d31 / CI39376484599后台、L1 394 PASS；#246 head d7102e3a / CI39376553152 SUCCESS、L1 277 PASS，仍按依赖顺序主线重绑，不能合入未过门的父片。根main已ff同步，4外部ZIP保留。

**2026-10-20 本轮两片最终收口 / CL-1F-2。** 第二片已吸收自身#249最终48e41f6c3763e332c7ee084291f15c455b6ebf00（merge e1d47e8f，仅交接冲突保留双方），最终命名L1 conversation_answer_generator **471 PASS/115.19s**，mypy122/128 NEW0、Ruff/format/diff-check PASS、候选secret findings0，工作树在本段所属提交后干净。第一片最终456 PASS/155.57s，负控旧候选失败已留证；远端finding4316987054确认同一期限缺陷，已在最终48e41f6c修复并resolve，CI39297650133绑定该head后台，旧1a5ad399不借绿灯。第二片增量仅9文件（相对48e41f6c），PR与新head由本段所属提交及GitHub恢复；未取其他窗口WIP。

#242已在91af16b5 / CI39262262003 SUCCESS / finding已解决后合main ab1e5ab4fc562fc8a64e504dde20e4ccef06536f；根main已ff同步且保留4个外部ZIP，exact-main push CI39296224656后台，前main cf70e688 CI39261429543 SUCCESS。#244重绑main后的head0f9142442e0a15bee84a32a7d88a9112b7d88e96 / CI39296775208后台，L1 132 PASS，不借旧head。无本地L3、SDK/真实付费调用、生产聊天/证据或发布权威切换；单次transport控制流不代表真实模型质量或首答延迟合格。唯一下一执行片：现有提供方传输合同的离线接线资格与生成费用边界，继续在后台CI期间独立推进，成熟片按新head审阅和CI逐片合main。

**2026-10-20 CL-1F-2：loop原生受控回答生成（本轮第二片）。** branch codex/conversation-answer-generator-20261020，初始冻结base自身#249 1a5ad399b4792f5551cc08ff3bdbb6b22d6fae59；发布前显式吸收本轮#249最终期限修复，不取其他窗口WIP。新增BoundedAnswerGenerator与脱敏AnswerGenerationError，loop可选answer_generator使用内部latest投影读当前快照，工具后的最终回答不会被raw root身份误判；与旧answer_handler互斥，默认路径不变。保留外层动作/总时限、预算、去重和取消，内层再做生成准入与精确fresh检查；失败停止，不把错误当回答、不触发后续tool。原dispatch失败回执仍保守handler_error/unknown，不把生成失败升级成已发布或证据权威。可共享决策和回答总额度；新模块/测试精确登记，未知范围仍扩大。无SDK/真实付费调用/生产路由/业务schema或发布资格切换，无本地L3。初步命名L1 conversation_answer_generator **470 PASS/171.18s**，mypy122/128 NEW0、Ruff/format/diff-check PASS、secret findings0；本地冻结初片，吸收父片最终期限修复后的联合门另记，不以旧父片结果授予最终候选。下一执行片：基于已有提供方传输合同做离线接线资格，不扩大到自动付费或正式回答发布。
**2026-10-21 #269主线重绑与CI观察竞态修复。** #266与#267分别在20766b28/CI39459399448、eb68ad1b/CI39554111731 SUCCESS且完整review无阻断后expected-head合main，当前main9de6b4aea45c2624f4e2b9ec07ed1cf1182ad5fe / push39611131236最后in_progress。此分支从9dfae10c吸收该main（无树冲突/生产变化），显式取自身独立96047bfb测试修复：killpg之后最多2秒观察停止、保留全部清理断言、活进程负控和/proc删除竞态处理。Linux20次实际执行8次立即仍活但20次均停止，原#278 run39593484878仅此时序断言失败，非确认生产逃逸。源修复直接影响集208 PASS，最终窄增量32 PASS；本分支同生产/测试树复用该证据，Ruff/diff-check另验。新SHA以本段提交恢复，改PR base main并推送绑定新CI；旧9df或子片旧绿灯不得借用。无src/workflow改动、本地L3或模型调用；后续自身CLI候选继续显式吸收本片冻结修复。

**2026-10-20 #249重绑main：有界回答生成片。** branch codex/conversation-answer-runner-20261020，原已审阅48e41f6c3763e332c7ee084291f15c455b6ebf00，吸收已合#248的main069fc1267010580c2c74ba3c1bb92f0e459458a5，merge450614da；仅docs/manifest/精确CI路径冲突，保留自身answer_runner登记及双方交接，不取其他窗口WIP。生产answer_runner及自身测试与48e41f6c逐字一致，已包含结束快照读取后再次检查deadline的已解决审阅修复；与main仍为7文件独立增量。最终命名L1 conversation_answer_runner **456 PASS/123.69s**，mypy122/128 NEW0、Ruff/diff-check PASS；密钥检查与exact-head CI另记发布结果，无本地L3。根main已ff到069fc126且仅4个原未跟踪ZIP。本轮并行修#257入口审阅问题：开关先于正文解析，正文4KiB/2秒有界，负控5项在旧head实际失败。#256旧CI39388736380因frontend required汇总失败，诊断下载中，未放行合并；#257旧head80912bb0 CI39389277406 SUCCESS不能授予新修复head。下一片：本候选推送/重绑main后继续自身#251生成器接线的逐片整合，研究/模型真实质量与生产切换仍未验收。

**2026-10-20 #249 最终期限修复。** 自审新增负控slow_completion_snapshot：发送及返回都在限内，但第三次（完成时）快照读取耗时超过总期限。旧1a5ad399确实返回completed，负控1 FAIL/34 deselected，日志D:/study-agent-validation/answer-deadline-negative.log。修复在输出校验后、交付前再次验证总期限，超时正文不交付且标unknown；长度检查先于strip。该缺陷局限于新opt-in runner，无共享/持久/生产权威变更，按L1复验，不以明确负控失败为未知原因强制全量。mypy122/128 NEW0，Ruff/format PASS；最终命名L1 conversation_answer_runner **456 PASS/155.57s**，mypy122/128 NEW0、Ruff/format/diff-check PASS、secret findings0；新候选SHA以本段提交恢复。修复将显式带入第二片，旧1a5ad399 / CI39296855483不能授予修复head。

**2026-10-20 CL-1F-1：回答生成的有界调用（本轮第一片）。** branch codex/conversation-answer-runner-20261020，固定base自身#248 39e38bd37116397312971f284b02d63e37d70a98，不取其他窗口WIP。新增AnswerLimits/ModelAnswerRequest/AnswerResult与generate_conversation_answer，注入单次transport，无SDK或真实调用。answer阶段身份独立命名空间且不随提议措辞/阶段分类/可变摘要改变；精确累计系统说明及JSON数据字符，预留输出token；复用准入协议和自有SQLite实现，不变更schema。预留前、实际发送前及返回后核验精确快照；过期/换题不发或不交付，所有准入不退款不重试。超时/调用者取消不等待忽略取消的transport，迟到结果丢弃；异常只返回脱敏状态。已有决策和回答可共享同一总额度，不能将此台账称为货币费用授权。注册模块与测试两个精确CI路径，保留未知范围扩大。未接loop/生产聊天/付费模型/发布权威，无本地L3。命名L1 conversation_answer_runner **455 PASS/128.90s**，mypy122/128 NEW0、Ruff/format/diff-check PASS、候选secret findings0；候选SHA由本段提交恢复。下一片把生成器作为可选loop适配器并接入内部派生fresh快照，避免宿主错误地用raw root身份验最终回答。

#242在91af16b5 / pull_request CI39262262003 SUCCESS / 原finding已解决后expected-head合入main ab1e5ab4（完整SHA以Git恢复）；#244已重绑该main，生产源与已合main相同，正在验证独立CI范围。#247/#248原冻结head CI39262160573/39262581250均SUCCESS且暂无finding，仍需依赖顺序逐片主线重绑，不能直接整线打包。


**2026-10-22 CLI parent-fix binding.** Frozen parent dd70dc0474c134d9e1c7a025188d2f261f4de8fe; previous candidate 1c2291155eb6fb76c0fdaa75eacf4768a54c3408. Only handoff and the verified execution-test repair changed; all other src/tools/tests/gate trees are unchanged. Executor and complete execution-test blobs match 96047bfb (208 PASS impact set plus final 32 PASS); reuse the previous candidate's unchanged-layer gates. No local L3 or workflow/model calls. New exact-head CI/review is required; old green is not reused. Next: merge only after this candidate qualifies.


**2026-10-22 CLI parent-fix binding.** Frozen parent 3741298283b2b8c4421f857eb168a1cfe3b461cf; previous candidate 440e8705425c939ac68b6a2b57965d392cf1c90b. Only handoff and the verified execution-test repair changed; all other src/tools/tests/gate trees are unchanged. Executor and complete execution-test blobs match 96047bfb (208 PASS impact set plus final 32 PASS); reuse the previous candidate's unchanged-layer gates. No local L3 or workflow/model calls. New exact-head CI/review is required; old green is not reused. Next: merge only after this candidate qualifies.


**2026-10-22 CLI parent-fix binding.** Frozen parent 15c6b2d8e410266829a94181769c17ba42aa83a7; previous candidate 407c2373cd12e51967c83adaa14228d2560f492c. Only handoff and the verified execution-test repair changed; all other src/tools/tests/gate trees are unchanged. Executor and complete execution-test blobs match 96047bfb (208 PASS impact set plus final 32 PASS); reuse the previous candidate's unchanged-layer gates. No local L3 or workflow/model calls. New exact-head CI/review is required; old green is not reused. Next: merge only after this candidate qualifies.


**2026-10-22 CLI parent-fix binding.** Frozen parent 14087de6e614b2028752b4a8cd2c19a050961247; previous candidate 4ff20cde16da8359a5688cf6323f6bea672a9413. Only handoff and the verified execution-test repair changed; all other src/tools/tests/gate trees are unchanged. Executor and complete execution-test blobs match 96047bfb (208 PASS impact set plus final 32 PASS); reuse the previous candidate's unchanged-layer gates. No local L3 or workflow/model calls. New exact-head CI/review is required; old green is not reused. Next: merge only after this candidate qualifies.


**2026-10-22 CLI parent-fix binding.** Frozen parent 8f19c60cca76e9d3325d9fe5c084986fa6ad0567; previous candidate 928b0760d3c969c9c8422272ac24cf83e373232c. Only handoff and the verified execution-test repair changed; all other src/tools/tests/gate trees are unchanged. Executor and complete execution-test blobs match 96047bfb (208 PASS impact set plus final 32 PASS); reuse the previous candidate's unchanged-layer gates. No local L3 or workflow/model calls. New exact-head CI/review is required; old green is not reused. Next: merge only after this candidate qualifies.


**2026-10-22 CLI parent-fix binding.** Frozen parent 6835a2b75300035a6c07ebd00e70e1e5ddaa2ba3; previous candidate c67cfbb7e0c7d8c2181f97f22d84e87b64146e82. Only handoff and the verified execution-test repair changed; all other src/tools/tests/gate trees are unchanged. Executor and complete execution-test blobs match 96047bfb (208 PASS impact set plus final 32 PASS); reuse the previous candidate's unchanged-layer gates. No local L3 or workflow/model calls. New exact-head CI/review is required; old green is not reused. Next: merge only after this candidate qualifies.


**2026-10-22 #280事件归属审阅4337733124。** 有效finding：同SHA但push/其他PR的failed check曾覆盖identity gap而误报当前PR FAIL。现先核对suite/event/PR，身份不符立即保留BLOCKED，不能接纳其failure；main遇PR失败同理。三个负控覆盖push→PR、其他PR、PR→main。直接影响集212 PASS/60.09s（自身42项），Ruff/format/工具mypy/diff-check通过；#279规则分页thread PRRT_kwDOSYWoX86uyvo5已修并解决，本轮event修复推送后解决#280 thread PRRT_kwDOSYWoX86uzC8L。最终head以本段提交恢复；子CLI吸收后需联合门，不能借旧390项作为最终新行为证据。src/workflow不变、无本地L3/模型调用。后续仅main整合、当前head review/CI与完整真实run验收。

**2026-10-21 CLI-04E归档数值比较。** branch codex/studyctl-recording-compare-20261021 / worktree D:/study-agent-validation/studyctl-recording-compare-20261021，独立固定自身#274 407c2373cd12e51967c83adaa14228d2560f492c，与事件分页为同父片兄弟分支，不依赖对方WIP。新增research compare，复用B5有界JSON读取/既有摘要投影，一次读取每输入避免重复读造成来源变化；仅同schema/run/完整问题与reference_date相同时计算已记录计数right-left。缺项delta=null，原停止码/门状态/缺证据提示分别保留，问题正文不输出；同一文件标same_artifact，各侧artifact SHA256独立。未知模型/执行配置/完整事件/引用支持明确缺失，固定PARTIAL，不做质量优劣或发布判定；不同任务/日期/坏记录阻断。自身14项通过，最终联合门与静态证据收口补记；src/历史产物不改，无L3/模型请求，CI遵用户要求后查。两个兄弟片最终整合时需保留parser/影响集精确路径并集，不覆盖另一片。
**2026-10-22 CLI parent-fix binding.** Frozen parent 15c6b2d8e410266829a94181769c17ba42aa83a7; previous candidate 407c2373cd12e51967c83adaa14228d2560f492c. Only handoff and the verified execution-test repair changed; all other src/tools/tests/gate trees are unchanged. Executor and complete execution-test blobs match 96047bfb (208 PASS impact set plus final 32 PASS); reuse the previous candidate's unchanged-layer gates. No local L3 or workflow/model calls. New exact-head CI/review is required; old green is not reused. Next: merge only after this candidate qualifies.

**状态口径：** `Standard = CLOSED ✅`；`Lookup` 保持其既有已验收状态；`Deep-1 / Deep-2 / Deep-3T / Deep-3 / Deep-4A = CLOSED ✅`；`Deep-4B = NO-GO`；`Learning State-1 L1 = CLOSED ✅`（authority `0de80751`）；`Learning State-1 L2–L6 = 未 CLOSED`（下一门 = 验收收尾）；`UI = 后置`（独立交互合同另开一 PR）。


**2026-10-22 CLI-05可信采集与全CLI合流候选最终门。** #280 branch codex/studyctl-ci-collect-20261021 / worktree D:/study-agent-validation/studyctl-ci-collect-20261021；冻结父#279 c2b5822e34a8360e88e4df84de566083e387f934、分页兄弟#275 9bd92f4f60b99ab74327cac4cc77bcd8d4aee8bf，保留compare/分页/CI parser、精确CI路径和命名影响集并集，冲突仅docs/manifest/CI路径。最终命名studyctl **409 PASS/1 SKIP/210.12s**，日志D:/study-agent-validation/studyctl-github-unified-final-l1-20261022.log；Ruff、四个变更模块format、8工具mypy、diff-check及唯一20文件scope通过，无src/workflow变化、本地L3、模型或真实研究请求。skip仍为Windows symlink权限。受测代码提交2f509c63，后续仅docs，最终SHA以本段提交恢复；最后secret与clean/实际CLI回执在提交后执行，不重复同树门。

已完成可信只读采集（collect指定PR、main指定当前main/push，required合同/完整规则与review分页/身份前后核对/预算/脱敏）和两个有效审阅修复：4337605902规则分页、4337733124错event失败归属。#279 thread PRRT_kwDOSYWoX86uyvo5已解决，#280 thread PRRT_kwDOSYWoX86uzC8L在最终推送后解决。命令级回执D:/study-agent-validation/studyctl-github-cli-final-e2e-20261022/manifest.json，按实际观察保留pending、错head、dry-run阻断，不授予merge_authorized。之前真实资格采集支持#266/#267/#269 expected-head合main，当前main2b3e27648719c1fda9f2486c6de4ec584f1199d1；push39641686708最后in_progress，不能声称CLI全线REMOTE GO。

父片冻结重绑清单/一次CI：D:/study-agent-validation/studyctl-rebound-candidates-20261022.json、studyctl-rebound-ci-once-20261022.json；#270 base已main/head3741298283b2b8c4421f857eb168a1cfe3b461cf/CI39642003837最后in_progress，其余后续同样新head后台，不借旧绿灯。下一唯一执行片：检查#270当前head完整审阅及精确CI，通过后expected-head合main，逐片推进#273/#274/#275/#276/#277/#278/#279/#280；分支合流/main验收与完整真实run业务样本仍未完成。根目录四个未跟踪ZIP保留，其他开发工作未动。

**2026-10-21 CLI-05D实时采集命令。** branch codex/studyctl-ci-collect-20261021 / worktree D:/study-agent-validation/studyctl-ci-collect-20261021，固定自身#279 a24b9daae934a296a80992541fc0d5668eaacad2。ci collect显式PR/repository/SHA；ci main验证当前main与push事件；required-check只声明项目要求，不修改服务器规则。dry-run零网络/零输出写入并BLOCKED，已有output在网络前拒绝，所有API异常脱敏，外层代码SHA与所查远端SHA分列。命名studyctl 386 PASS/1 SKIP/190.50s（自身13项）；Ruff与explicit-package-bases工具mypy通过。另显式吸收自身独立测试修复96047bfb的tests/test_studyctl_execution.py（不取其他WIP），纯测试增量单独重验32项，生产树不变。

#266精确20766b28 / pull_request CI39459399448 SUCCESS / 完整review无阻断后合main5f0e616e518ca3deb193778d9a17780eacd393a6，push39609573752最后in_progress；#267精确eb68ad1b / pull_request CI39554111731 SUCCESS / 完整review无阻断后合main9de6b4aea45c2624f4e2b9ec07ed1cf1182ad5fe，push39611131236最后in_progress。均expected-head保护，不等待CI才继续开发；根目录四个ZIP原样保留。#278旧head CI失败不可合并，测试修复正在#269重新绑定main及后续候选。真实可信采集已可用，但CLI全线main整合、完整真实run验收仍未完成；下一片按新head审阅与CI逐片收口，不扩展更多命令。无模型/付费请求、workflow/src改动或本地L3。
**2026-10-22 #280事件归属审阅4337733124。** 有效finding：同SHA但push/其他PR的failed check曾覆盖identity gap而误报当前PR FAIL。现先核对suite/event/PR，身份不符立即保留BLOCKED，不能接纳其failure；main遇PR失败同理。三个负控覆盖push→PR、其他PR、PR→main。直接影响集212 PASS/60.09s（自身42项），Ruff/format/工具mypy/diff-check通过；#279规则分页thread PRRT_kwDOSYWoX86uyvo5已修并解决，本轮event修复推送后解决#280 thread PRRT_kwDOSYWoX86uzC8L。最终head以本段提交恢复；子CLI吸收后需联合门，不能借旧390项作为最终新行为证据。src/workflow不变、无本地L3/模型调用。后续仅main整合、当前head review/CI与完整真实run验收。

**2026-10-22 CLI parent-fix binding.** Frozen parent fddeae9a502b9516ad48ce8240a7c3a0a4d868e3; previous candidate 970fc710b51862918c5f9c32ccd4c4ce13d074ea. Only handoff and the verified execution-test repair changed; all other src/tools/tests/gate trees are unchanged. Executor and complete execution-test blobs match 96047bfb (208 PASS impact set plus final 32 PASS); reuse the previous candidate's unchanged-layer gates. No local L3 or workflow/model calls. New exact-head CI/review is required; old green is not reused. Next: merge only after this candidate qualifies.

**2026-10-22 #279审阅修复4337605902。** 有效finding：rules/branches接口默认分页，原单请求可能漏后续required check/未知门。现复用10页/100条/总deadline预算读取全部规则，规则无独立id，完整JSON指纹用于重复页校验；不足或超限阻断。两个负控明确旧第一页行为PASS，而第二页新增required check/未知门必须BLOCKED；另验页数耗尽。直接影响集209 PASS/60.45s（自身39项），Ruff/format/工具mypy/diff-check通过；不重复此前373项不变层。另吸收自身96047bfb的完整执行测试修复，与已验208+最终32项的测试/执行器blob相同。下一步绑定已冻结父片后推新head并解决该thread，不借旧head CI。

#269最新dd70dc0474c134d9e1c7a025188d2f261f4de8fe / pull_request CI39611831046 SUCCESS、完整review无阻断后expected-head合main2b3e27648719c1fda9f2486c6de4ec584f1199d1。CLI后续候选已逐片吸收其冻结测试修复，仅docs/执行测试变化；src/tools/其余tests/manifest完全不变，复用旧层验证而不机械全量。下一唯一门仍是各新head审阅/CI与main资格，不增加新CLI功能。

**CLI-05C最终本地门。** 命名studyctl 373 PASS/1 SKIP/203.31s（自身36项），Ruff、独立工具mypy、diff-check通过；skip仍为Windows symlink权限。真实采集13次请求/PR、11次/main；#266按已采精确head20766b28与完整审阅检查expected-head合入main5f0e616e（完整SHA见Git），新main push CI单独记录，不借旧main绿灯。原根目录四个review ZIP保留。下一片基于本片冻结提交接CLI；#278原CI竞态单独修复，不修改门或忽略失败。

**2026-10-21 CLI-05C可信GitHub采集核心。** branch codex/studyctl-ci-live-20261021 / worktree D:/study-agent-validation/studyctl-ci-live-20261021，固定自身#278 c67cfbb7e0c7d8c2181f97f22d84e87b64146e82。新增只读gh适配器：固定github.com、只允许GET与固定GraphQL查询，90秒/80请求/每响应2MiB/每流10页；不继承调试/其他host设置、不输出响应错误正文。采集保护设置/生效rules、全部check runs/statuses/actions、完整threads和reviews，前后核对PR与base/policy。404只有admin权限且branch明确unprotected才能解释为无保护；空server政策仍须显式project required checks，否则BLOCKED。检查绑定SHA/app/suite/event/PR，skip/neutral/未知规则/缺权限/分页耗尽/状态变化阻断；PASS只证明观察到的GitHub检查与审阅门，merge_authorized仍false，本地验收与expected-head合并由调用者负责。

真实只读回执D:/study-agent-validation/studyctl-github-live-smoke-20261021：#266精确20766b28 PASS、main精确069fc126 PASS；#278精确c67cfbb7 FAIL，run39593484878（pull_request）仅失败test_timeout_after_parent_exit_still_cleans_descendant，5028 PASS/6 SKIP，不借绿灯合并。初步自身36+CI路由76共112 PASS；联合门最终证据补记。无workflow/src变化、L3、模型或付费请求。下一片接ci collect/main入口，并单独修复Linux子进程停止观察竞态，再按当前head收口CLI候选。
**2026-10-22 CLI parent-fix binding.** Frozen parent 6835a2b75300035a6c07ebd00e70e1e5ddaa2ba3; previous candidate c67cfbb7e0c7d8c2181f97f22d84e87b64146e82. Only handoff and the verified execution-test repair changed; all other src/tools/tests/gate trees are unchanged. Executor and complete execution-test blobs match 96047bfb (208 PASS impact set plus final 32 PASS); reuse the previous candidate's unchanged-layer gates. No local L3 or workflow/model calls. New exact-head CI/review is required; old green is not reused. Next: merge only after this candidate qualifies.

**2026-10-21 CLI-05B最终本地门。** 命名studyctl **337 PASS/1 SKIP/181.26s**，含父片24个证据判定和本片13个CLI接线用例；七工具mypy、Ruff/新模块format/diff-check PASS，无src/workflow变化、L3或live查询。父片#277 head928b0760d3c969c9c8422272ac24cf83e373232c；本片最终SHA由本段所属提交恢复。提交后读取旧本地CI快照和构造step回执做实际CLI回放，明确不是当前GitHub状态或真实合并资格，回执D:/study-agent-validation/studyctl-ci-offline-e2e-20261021/manifest.json。当前建设缺口清单已写STUDYCTL与外部实施计划；下一正式片可信live采集，不扩展更多诊断命令。用户要求不等CI，本轮仅发布PR，不查询/等待CI或合main。

**2026-10-21 CLI-05B离线CI命令接线。** branch codex/studyctl-ci-cli-20261021 / worktree D:/study-agent-validation/studyctl-ci-cli-20261021，基于自身已提交CLI-05A，吸收冻结事件补强928b0760d3c969c9c8422272ac24cf83e373232c（无其他工作树WIP）。新增ci inspect --snapshot/--github-repo/--pr/--exact-head和ci outcomes --receipt/--exact-head/--run-id/--event；参数缺失先拒绝，输入错误脱敏，外层CLI代码SHA与被检head分列。离线snapshot不能获merge GO；raw outcomes仅复用已有门作记录回放，真实性/当前PR资格不在此命令内。自身13 PASS/10.52s，包含禁止gh/网络子进程、跨checkout来源、实际entrypoint JSON；联合门吸收父修复后收口补记。无GitHub/CI查询、workflow修改、L3或模型请求。下一正式片是live required policy/check contexts/review/main采集，不以此离线入口声称CLI-05整体完成；STUDYCTL文档已列Study和其余五仓库剩余方向。
**2026-10-22 CLI parent-fix binding.** Frozen parent 8f19c60cca76e9d3325d9fe5c084986fa6ad0567; previous candidate 928b0760d3c969c9c8422272ac24cf83e373232c. Only handoff and the verified execution-test repair changed; all other src/tools/tests/gate trees are unchanged. Executor and complete execution-test blobs match 96047bfb (208 PASS impact set plus final 32 PASS); reuse the previous candidate's unchanged-layer gates. No local L3 or workflow/model calls. New exact-head CI/review is required; old green is not reused. Next: merge only after this candidate qualifies.

**2026-10-21 CLI-05A事件元数据补强。** 最终人工检查补上workflow event的类型/已知名称白名单，避免未知对象在诊断输出中回显任意内容；自身CI模块24 PASS/6.07s，Ruff/format/mypy/diff-check PASS，既有failed_steps与下层未变，不重跑同树下层门。最终CLI分支吸收此冻结修复后跑完整命名studyctl联合门，不能仅借前置323结果；此片最终SHA由本段提交恢复，CI仍后查。

**2026-10-21 CLI-05A最终本地门。** 已冻结代码34eb2916c4360a6663bbc2d3c80f049212726426，命名studyctl **323 PASS/1 SKIP/176.40s**，含23个CI证据/原始outcome用例及原CI规则直接影响集；既有Windows symlink权限跳过。mypy、Ruff/新模块format/diff-check PASS，src/CI workflow未变、无L3或网络查询。此后仅文档收口，不重复同树门。最终SHA由本段提交恢复；下一自身分支只基于此已提交候选接CLI，CI仍留后查。完整live required checks/main证据采集还没实现，离线快照不能授予merge GO。

**2026-10-21 CLI-05A离线CI证据核心。** branch codex/studyctl-ci-evidence-20261021 / worktree D:/study-agent-validation/studyctl-ci-evidence-20261021，固定自身#276 4ff20cde16da8359a5688cf6323f6bea672a9413。新studyctl_ci只读2MiB JSON，兼容已存prs/checks查询快照，绑定仓库URL/PR/head/event与review分页，不复制评论正文；缺policy/check contexts/live freshness/main证据不能GO，同head明确failure可FAIL，旧head或未知结论仅BLOCKED。另复用既有failed_steps回放raw outcome，不被conclusion假绿覆盖，pytest_impact及可选frontend/browser语义不改；可选离线step回执身份head/run/event与routing必须完整。raw回放PASS只证明提供记录满足步骤门，不代表authenticity或合并许可。无live GitHub调用/CI等待/工作流修改；CLI下一片接线。自身＋直接outcomes初步60 PASS/14.57s，补未知conclusion负控后联合门收口补记；src未变，无L3/模型费用。
**2026-10-22 CLI parent-fix binding.** Frozen parent 14087de6e614b2028752b4a8cd2c19a050961247; previous candidate 4ff20cde16da8359a5688cf6323f6bea672a9413. Only handoff and the verified execution-test repair changed; all other src/tools/tests/gate trees are unchanged. Executor and complete execution-test blobs match 96047bfb (208 PASS impact set plus final 32 PASS); reuse the previous candidate's unchanged-layer gates. No local L3 or workflow/model calls. New exact-head CI/review is required; old green is not reused. Next: merge only after this candidate qualifies.

**2026-10-21 CLI-04E最终本地门。** 命名studyctl **300 PASS/1 SKIP/174.67s**（自身14 PASS/12.79s），六工具mypy、Ruff/新增模块format/diff-check PASS，src与历史B5文件未变，无L3/模型调用。最终候选SHA由本段提交恢复，提交后记录同一Git归档真实CLI自比较回执；same_artifact=true/各计数delta0也固定PARTIAL，不能当两次实验或质量通过。兄弟分页片#275 headb964344ae409b08ed5f0425d2a18cc06b6f3bbf9已独立发布，L1 302 PASS/1 SKIP；二者同父407c但未相互合并，后续联合时需保留parser/命名影响集并集。用户要求不等CI，本轮不查CI、不合main。下一执行片CLI-05 exact-head CI只读核验，复用现有outcome规则，缺必需证据则BLOCKED，不运行或轮询工作流。

**2026-10-21 CLI-04E归档数值比较。** branch codex/studyctl-recording-compare-20261021 / worktree D:/study-agent-validation/studyctl-recording-compare-20261021，独立固定自身#274 407c2373cd12e51967c83adaa14228d2560f492c，与事件分页为同父片兄弟分支，不依赖对方WIP。新增research compare，复用B5有界JSON读取/既有摘要投影，一次读取每输入避免重复读造成来源变化；仅同schema/run/完整问题与reference_date相同时计算已记录计数right-left。缺项delta=null，原停止码/门状态/缺证据提示分别保留，问题正文不输出；同一文件标same_artifact，各侧artifact SHA256独立。未知模型/执行配置/完整事件/引用支持明确缺失，固定PARTIAL，不做质量优劣或发布判定；不同任务/日期/坏记录阻断。自身14项通过，最终联合门与静态证据收口补记；src/历史产物不改，无L3/模型请求，CI遵用户要求后查。两个兄弟片最终整合时需保留parser/影响集精确路径并集，不覆盖另一片。
**2026-10-22 CLI parent-fix binding.** Frozen parent 14087de6e614b2028752b4a8cd2c19a050961247; previous candidate b964344ae409b08ed5f0425d2a18cc06b6f3bbf9. Only handoff and the verified execution-test repair changed; all other src/tools/tests/gate trees are unchanged. Executor and complete execution-test blobs match 96047bfb (208 PASS impact set plus final 32 PASS); reuse the previous candidate's unchanged-layer gates. No local L3 or workflow/model calls. New exact-head CI/review is required; old green is not reused. Next: merge only after this candidate qualifies.

**2026-10-21 CLI-04D最终本地门。** 命名studyctl **302 PASS/1 SKIP/181.26s**，自身事件页16 PASS/16.07s；五工具mypy、Ruff/新增模块format/diff-check PASS，src与历史归档未动，无L3或模型请求。既有Windows symlink权限用例仍跳过，未隐藏其他失败。最终SHA由本段提交恢复，提交后记录构造SQLite的实际分页命令回执，不将其当真实模型质量验收。兄弟比较分支基于同父407c，不依赖本片WIP；后续整合保留二者parser与影响集登记，CI留后查。

**2026-10-21 CLI-04D有界事件页。** branch codex/studyctl-event-pages-20261021 / worktree D:/study-agent-validation/studyctl-event-pages-20261021，固定自身#274提交407c2373cd12e51967c83adaa14228d2560f492c。SQLite inspect默认50条、显式1～100条，游标绑定snapshot SHA256/run_id/sequence，坏格式参数错，跨源/未知位置阻断。total_event_count/events_returned/has_more/next_event_cursor明确内容范围；覆盖判据仍来自整条已验证state.trace，不把分页面输出当完整记录。B5 summary拒绝事件选项，不伪造timeline。自身聚焦与联合门结果收口补记；src/持久schema不动，无新研究/费用或L3。下一片已有B5诊断的只读数值差异，保持PARTIAL且不作质量优劣裁决；CI遵用户要求留后查。
**2026-10-22 CLI parent-fix binding.** Frozen parent 15c6b2d8e410266829a94181769c17ba42aa83a7; previous candidate 407c2373cd12e51967c83adaa14228d2560f492c. Only handoff and the verified execution-test repair changed; all other src/tools/tests/gate trees are unchanged. Executor and complete execution-test blobs match 96047bfb (208 PASS impact set plus final 32 PASS); reuse the previous candidate's unchanged-layer gates. No local L3 or workflow/model calls. New exact-head CI/review is required; old green is not reused. Next: merge only after this candidate qualifies.

**2026-10-21 CLI-04C干净提交命令验收。** 生产候选b054a58c7e37672541a0333c9a3b8892ddf2ea9c上实际执行5类CLI业务样例，结果PASS/0（历史空库目录）、FAIL/2（limit0）、BLOCKED/3（归档run身份不匹配）、PARTIAL/3（Git B5真实诊断）、FAIL/4且child1（系统Python无pytest的环境失败）。每条stdout单JSON，argv/head/原始退出码和stderr分开保留；输入B5/历史DB的SHA256前后相同，无旁文件。回执D:/study-agent-validation/studyctl-business-examples-20261021/manifest.json；不是新模型实验或真实研究质量验收。后续只有本文档与使用说明变化，复用同src/tools/tests树的286 PASS/1 SKIP、mypy/Ruff/format证据，不重跑全套。目录片#273 head440e8705425c939ac68b6a2b57965d392cf1c90b、归档片最终head由本段提交恢复，两片独立推送，CI遵用户要求未查。下一片有界事件分页；CI/main合并资格后续按对应head独立核对。

**2026-10-21 CLI-04C最终本地门。** 命名studyctl **286 PASS/1 SKIP/118.48s**，含16个归档JSON回放/坏输入/真样本断言，继承目录片270 PASS/1 SKIP。五工具mypy、Ruff/新增模块format/diff-check PASS，src与历史B5文件未改，无本地L3或新真实研究。最终候选SHA由本段提交恢复；Git归档回放仍为PARTIAL，不转成研究质量GO。下一动作记录干净候选实际CLI的成功/参数错/前提阻断/环境执行失败回执，独立PR、CI留后查。

**2026-10-21 CLI-04C：消费Git已归档B5真实诊断。** branch codex/studyctl-recorded-research-20261021 / worktree D:/study-agent-validation/studyctl-recorded-research-20261021，固定自身目录片#273 440e8705425c939ac68b6a2b57965d392cf1c90b。按用户“找找git”检查main历史路径清单后未见数据库快照，但找到B5真实smoke JSON；实际producer创建run b5_active_searxng_smoke、完成后从同一run投影ui_progress并删除临时SQLite。因此新增--artifact仅接受既有v2 schema，和--database二选一；2MiB、重复key/非有限数/坏计数/跨run拒绝，不导入live producer、不重建数据库或伪造事件。仅回显既有run/门状态、停止码和数值摘要；身份字段仅关联、UI不是Evidence Gate；问题/答案摘要不输出，缺计数null而非0，缺完整trace/支持事件固定PARTIAL/3。真实已提交样本得到partial/evidence_budget_exhausted、7候选/0读取/0 eligible，events=[]；不是重新研究或新模型质量验收。自身16项通过，五工具mypy、Ruff/format通过，联合命名门收口后补记；src/历史产物保持不变，无L3/费用。用户要求不等CI，后续push不查CI。下一动作：记录最终候选的实际CLI多类结果回执，再继续有界事件分页或其他仓库局部G0。
**2026-10-22 CLI parent-fix binding.** Frozen parent 3741298283b2b8c4421f857eb168a1cfe3b461cf; previous candidate 440e8705425c939ac68b6a2b57965d392cf1c90b. Only handoff and the verified execution-test repair changed; all other src/tools/tests/gate trees are unchanged. Executor and complete execution-test blobs match 96047bfb (208 PASS impact set plus final 32 PASS); reuse the previous candidate's unchanged-layer gates. No local L3 or workflow/model calls. New exact-head CI/review is required; old green is not reused. Next: merge only after this candidate qualifies.

**2026-10-21 CLI-04B最终验证。** 命名studyctl **270 PASS/1 SKIP/115.92s**，新增目录16项、四工具mypy、Ruff/新增模块format/diff-check PASS，src未变、无L3或模型调用。提交与PR以本段所属Git提交恢复；CI遵从用户“不等CI，先做后续”暂不查询。用户答复“找找git”后，已对main跟踪文件和main历史object路径建有界清单（D:/study-agent-validation/studyctl-{git-evidence-files,main-object-paths}-20261021.txt），未找到跟踪的SQLite快照；找到已提交B5_ACTIVE_SEARXNG_SMOKE.json（blob e8b43a243b01051d90e4945d07709790d121638d，归档提交cbb6ba0a0ddceb0ac4eb314ab3119b505ab9e099），实际run为partial/evidence_budget_exhausted且仅含诊断摘要。下一片优先支持此既有JSON的只读兼容解释，保留缺时间线/支持事件的PARTIAL；事件分页后续另片，不把汇总伪造为完整trace或SQLite。

**2026-10-21 CLI-04B离线运行目录。** branch codex/studyctl-research-catalog-20261021 / worktree D:/study-agent-validation/studyctl-research-catalog-20261021，基于自身已提交#270 1c2291155eb6fb76c0fdaa75eacf4768a54c3408，不依赖其他开发WIP。新增research list，显式离线快照，复用原只读内存连接/64MiB/2秒预算；只列run ID/status/stage/stop_reason，二进制顺序、1～100条分页，游标绑定文件SHA256，变化阻断。空目录PASS仅代表读取成功，不代表研究验收；坏metadata不静默跳过，未知/过期游标分参数错与快照前提不足。自身16项通过，最终联合门/静态检查以收口结果补记。没有修改src、数据库schema、真实用户设置或调用模型；CI按用户要求留后查。

实际样本发现仅做有界路径检索：r1c-audit、async-r1c-isolated、r1c-test-hardening历史logs/runtime/study_agent.db均544768B、最后写入2026-10-17且无旁文件；新CLI只读内存目录三份均PASS/runs=[]，不依赖其WIP源码、不将这些空库说成真实研究质量通过。原始文件未执行SQLite连接、迁移/恢复/写入。真实run快照样本仍缺，已异步询问路径且不阻断独立开发；资格回执区分构造记录和真实任务。下一片：有界事件分页，复用此冻结目录片与既有研究状态校验，不新增研究调度器。
**2026-10-22 CLI parent-fix binding.** Frozen parent dd70dc0474c134d9e1c7a025188d2f261f4de8fe; previous candidate 1c2291155eb6fb76c0fdaa75eacf4768a54c3408. Only handoff and the verified execution-test repair changed; all other src/tools/tests/gate trees are unchanged. Executor and complete execution-test blobs match 96047bfb (208 PASS impact set plus final 32 PASS); reuse the previous candidate's unchanged-layer gates. No local L3 or workflow/model calls. New exact-head CI/review is required; old green is not reused. Next: merge only after this candidate qualifies.

**2026-10-21 八条审阅意见最终收口。** #267四个修复冻结eb68ad1bb68af5ceb4f543dc2454db857dcecfbb，L1 176 PASS/57.90s；#269执行修复4a440f386e48e7a9882cd3309f731e8b8ada4820吸收父片后代码merge c12a0ea9fef017ef58391dc8dfd0b0af85968ba7，L1 207 PASS/73.73s，最终文档收口9dfae10c16dd2c20d2e175b704ac988bedcb8510。#270自身SHA归属修复8a06d49324872ce858fb9a4bcafbac54ff80b999，吸收c12后merge29af0040c62178a8e608bc9e6f6bef4303eebeec，最终联合命名studyctl **254 PASS/1 SKIP/99.31s**（Windows symlink权限限制）；再吸收9df仅docs变化，已核对src/tools/tests树相对29af无变化，不重跑同树门。冲突仅handoff保留双方、parser保留research子命令并使用新显式L3预算，未重开合同。四个CLI/stage工具mypy、Ruff、新改模块format、diff-check PASS，src未动，secret扫描以本次外部报告恢复；无L3/真实模型/费用。BallWar #7折叠修复1f8d19bd412afe069a3b7e5ab551b7470931c85a，12runner/40设置断言通过且旧实现负控FAIL。所有修复推送后解决原八线程并仅查一次新head CI，未把旧绿灯授予新head；当前PR/CI快照另存D:/study-agent-validation/cli-review-fixes-closeout-20261021.json。最终本分支SHA由本段所属提交恢复，下一片既有离线研究快照的可用性验收，待成熟小片按新HEAD证据依序合main，保留原混合工作树。

**2026-10-21 CLI-04审阅修复（#270来源SHA）。** 固定自身5c59eb8c775cc37d77e1b8d3a5f9b5c27bc11566初始clean；--repo仍可指向其他checkout，但research inspect的外层head_sha改用实际CLI ROOT提交，指定repo的SHA独立保存requested_repo_head_sha并列inspection_root，不和输入snapshot_sha256混用。新增两个不同真实Git checkout的回归验证归属；自身 **24 PASS/1 SKIP/17.63s**（既有Windows symlink权限跳过），初次新测试漏import引发NameError，仅补测试导入后通过，非产品异常。无真实研究/数据库写入。下一动作：吸收#267/#269冻结修复后跑联合命名门、静态检查并推送，最终SHA以本段提交恢复，不借旧CI或其他工作树WIP。

**2026-10-21 CLI-04：只读research inspect候选。** branch codex/studyctl-research-inspect-20261021 / worktree D:/study-agent-validation/studyctl-research-inspect-20261021，固定自身#269提交807fdea6a0969c7889bd7fbafbc3aac0a9d3a122，不取其他开发工作树WIP。显式--run与--database，读取一致离线SQLite快照到内存，仅SELECT指定run，不调用RuntimeDatabase初始化/迁移/恢复；64MiB文件预算、JSON列2Mi字符预算、SQLite查询2秒预算，拒绝WAL/SHM/journal旁文件。复用known_research_evidence_ids/load_claim_engine_state，不新建EvidenceRuntime或质量门，不扫描答案或更改停止码。只投影记录事件，跨run timeline拒绝归属，搜索/读取/引用支持/停止四类缺失证据为PARTIAL/3，坏快照/JSON/缺列/缺run为BLOCKED/3；PASS只指检查记录完备，不授予答案或发布权威。输入快照SHA256和CLI head分开，在线/大库读取后续独立处理。

前置CLI-03现为#269 head807fdea6；干净源码真实CLI执行conversation_decision_admission **114 PASS/32.29s**，回执D:/study-agent-validation/studyctl-run-venv-clean-e2e-20261021.json记录同SHA、前后tracked/untracked均0、uncommitted_source=false。曾误用系统Python3.14导致缺pytest，CLI正确返回FAIL/4并保留child_exit_code=1；改用项目既有venv后通过，未安装依赖或更改全局环境。本轮用户明确“CI回头查，先做后面的”：后续push不查询/等待CI，PR继续独立发布；不宣称REMOTE GO或main已合并。BallWar设置已修、迁移候选#7 head ecd582d1128b1dc5192b444ba66dc70d054c8e79，12原生runner/34设置断言通过，#8已合入该候选分支，尚未合main；本轮未追加CI轮询。原混合工作树保留。

CLI-04联合命名studyctl **246 PASS/141.45s**，含CLI全栈、直接state/trace/memory与CI门合同；最终增加路径规范化/目录拒绝后仅重跑直接影响集，自身 **23 PASS/1 SKIP/26.87s**（Windows无symlink权限，真实软链接负控跳过），不重复未变更的下层合同门。三个CLI模块mypy PASS，src相对807f无变化，复用src122/128 NEW0；Ruff/新增模块format/diff-check PASS，无本地L3、真实模型或付费调用。最终SHA由本段提交恢复，远端CI待后查。下一执行片：基于既有离线研究快照做诊断可用性验收；CI与合并在后续统一核对，不建立新调度器、SDK或真实研究调用。
**2026-10-21 #269主线重绑与CI观察竞态修复。** #266与#267分别在20766b28/CI39459399448、eb68ad1b/CI39554111731 SUCCESS且完整review无阻断后expected-head合main，当前main9de6b4aea45c2624f4e2b9ec07ed1cf1182ad5fe / push39611131236最后in_progress。此分支从9dfae10c吸收该main（无树冲突/生产变化），显式取自身独立96047bfb测试修复：killpg之后最多2秒观察停止、保留全部清理断言、活进程负控和/proc删除竞态处理。Linux20次实际执行8次立即仍活但20次均停止，原#278 run39593484878仅此时序断言失败，非确认生产逃逸。源修复直接影响集208 PASS，最终窄增量32 PASS；本分支同生产/测试树复用该证据，Ruff/diff-check另验。新SHA以本段提交恢复，改PR base main并推送绑定新CI；旧9df或子片旧绿灯不得借用。无src/workflow改动、本地L3或模型调用；后续自身CLI候选继续显式吸收本片冻结修复。

**2026-10-21 #269最终父片合流。** 自身修复4a440f386e48e7a9882cd3309f731e8b8ada4820显式吸收已提交父片#267 eb68ad1bb68af5ceb4f543dc2454db857dcecfbb，merge c12a0ea9fef017ef58391dc8dfd0b0af85968ba7；仅Current Handoff冲突，保留双方，源码自动合并。最终联合命名studyctl **207 PASS/73.73s**，CLI/stage resolver三模块mypy、Ruff/format/diff-check PASS，src未变。旧实现的四个计划负控均实际FAIL；旧L3默认300秒在新增测试中错误启动执行器，负控实际FAIL。后续仅文档收口，不重复同树测试；最终推送SHA由本段提交恢复。下一片#270只吸收此冻结候选与自身来源SHA修复，不接其他窗口WIP。CI推送后一次记录，不等待才推进；无L3或真实模型调用。

**2026-10-21 CLI-03审阅修复（#269两项）。** 基于自身807fdea6a0969c7889bd7fbafbc3aac0a9d3a122初始clean。L3必须显式预算，L1/L2保留300秒默认；预算缺失/非法先拒绝且不启动全量。修复wait超时与父进程退出竞争后的post-loop判定：同样调用树清理。Windows新增本执行器私有Job Object，bootstrap阻塞私有pipe→入Job→放行真实argv，关闭/终止Job且查询活动成员后确认清理，不能用已退出PID推断后代；分配失败不放行、正常结束同样回收后台遗留后代。原始argv/子退出码与JSON不变，无shell/新依赖。新增实际父先退出而后代sleep的受控时序回归，在Windows原生通过，不只mock cleanup flag。自身31 PASS/13.85s；联合命名studyctl **203 PASS/74.70s**，两CLI模块mypy/Ruff/format/diff-check PASS。无L3/真实模型，下一动作显式吸收#267已提交修复后跑联合门并推送，不借旧CI。

**2026-10-21 CLI-03：受控test run候选。** branch codex/studyctl-test-run-20261021，固定自身#267 head8cc3594af474c2e65f1e1ae0614ebad7226bd126，不依赖其他窗口WIP。复用原stage runner/manifest resolver；显式L1/L2选择登记非空且tests内的文件，显式L3才预检→全pytest，预检失败或deadline耗尽不启动后续。dry-run无进程/日志写入，禁止任意repo脚本及参数透传。子环境白名单、独立HOME/APPDATA、屏蔽凭据与PYTEST_ADDOPTS，检测根及祖先.env则不读内容而阻断；不是网络沙箱，测试仍须遵守原隔离合同。超时/取消终止自有进程树，失败原码保留、无重试；1MiB日志阈值与诊断转发上限、清理不确定性显式记录。执行前拒绝已有output，执行前后源码tracked/untracked状态写入结果，不用dirty测试冒充HEAD资格。

最终命名L1 studyctl **201 PASS/85.27s**（自身执行29项、基础14、计划16及直接CI/门合同），两CLI模块mypy PASS，src相对8cc无改动，复用122/128 NEW0；Ruff/format/diff-check及secret以发布收口恢复。真实CLI调原conversation_decision_admission **114 PASS/30.96s**，退出0、child日志仅stderr；该开发中E2E来自旧HEAD上的本分支WIP，最终候选提交后再记干净源码回执，不借SHA。无全量L3、真实模型/费用/生产权威变化。下一CLI片：只读research inspect，先锁现有trace读取器和证据缺口；不新增研究调度器。

BallWar并行修复已关设置错误：#8 headf1d9bf6独立审阅后merge afb5901进4.7候选；发现main已更新7c0a426（运行/文档迁移/新增CI），重绑517a98a，最新候选ecd582d1128b1dc5192b444ba66dc70d054c8e79。重绑后12/12原生runner无错误、设置34断言与1120×720原生开关截图通过；CI同步4.7.1官方资产、12runner、独立XDG_DATA_HOME，先拒绝SCRIPT ERROR/ERROR再认PASS，候选#7须其最新CI，不再沿用旧“无CI”状态。原混合WIP/真实玩家数据保留，当前只关闭源码设置/迁移测试阻塞，Android/发版/长程性能未验收。

**2026-10-21 CLI-02审阅修复（#267四项）。** 固定旧head8cc3594af474c2e65f1e1ae0614ebad7226bd126，当前branch/worktree不变且初始clean。要求计划head等于目标HEAD；原resolve新增可选root参数并保留默认兼容，由plan显式传target root；L0 Ruff目标绝对路径、提交base/head diff-check、显式WIP diff-check与tracked status空输出判据；拒绝Git字面反斜杠。新负控覆盖历史head、仅目标checkout存在的测试、已提交空白/dirty范围和异常路径。初版新fixture把新测试路径也放进变更范围，触发正确的保守scope_review；改为基线先包含目标专属测试后再只改CLI，从而隔离验证root问题，非放宽分类器。最终命名L1 studyctl **176 PASS/57.90s**、两工具mypy、Ruff/format/diff-check PASS，src未变。无L3/模型调用；修复SHA由本段所属提交恢复，旧CI不授予新head。下一动作：冻结推送本片，后继#269/#270只吸收此已提交修复并按增量验收。

**2026-10-21 三片收口：CLI-02最终候选。** 初始自身832cbcc2的计划实现4c4b9e8f，显式吸收父片#266修复20766b2880a41fdce6f4abbbb505b76d0e4d45de得到merge cd13c192；仅Current Handoff冲突保留双方，代码自动合并，不取其他窗口WIP。最终命名L1 studyctl **172 PASS/66.75s**（基础14项＋plan16项＋直接CI/门合同），此前171为吸收父片前证据，不借给新候选。CLI独立mypy PASS、src122/128 NEW0，Ruff/format/diff-check PASS，密钥检查以发布结果恢复；相对20766b28仍7文件独立增量。未提交门配置/空影响集/异常路径/未知和混合范围均不允许静默缩小或启动全量。所有plan都不执行测试/模型，带L0命令、登记L1 argv与scope_review理由。无L3/生产发布或付费调用。

#266最终head20766b28 / exact-head PR CI39459399448后台，Ctrl-C thread已resolve，旧832绿灯不授予修复头。BallWar Draft #7 head3b602f90为4.7目标，11/12隔离测试、已记录首次未隔离user://与设置旧接口阻塞，不合并。两Study CLI工作树及BallWar候选均显式提交，root4个ZIP与BallWar原6项WIP保留。当前命名L1与风险证据已冻结，文档不重跑联合门。唯一下一CLI片：显式白名单test run，复用stage runner和L3 preflight，覆盖子进程失败/超时/取消/无误启动重型门；BallWar设置能力缺口另列独立片，不扩大本CLI合同。

**2026-10-21 CLI-02：test plan独立开发片。** branch codex/studyctl-test-plan-20261021，初始自身CLI-01冻结832cbcc2，后续显式吸收#266 Ctrl-C审阅修复；未取其他工作树WIP。只调用本CLI信任的classify/load_manifest/resolve，不从任意repo执行Python。解析精确base/head并校验祖先关系，rename按两端，默认排除working tree并明示，include才纳入；未提交门配置不允许暗中影响排除WIP的计划。仅已登记非空影响集输出runner argv，原路径存在性双检；未知/混合无唯一登记集为PARTIAL/3并scope_review，不发起测试/网络/模型，不把full_scope/l3_eligible变为自动L3。异常空白/换行路径阻断而不修剪成已登记路径。初次169 PASS后补门配置脏状态/路径负控，当前新候选复验中；最终结果以本段后续收口恢复。standalone CLI mypy PASS、src122/128 NEW0。无生产权威/持久schema变化，无本地L3。下一片是显式白名单test run，沿用原stage runner/L3 preflight，不新增调度器。

并行BallWar已按用户更正目标4.7，独立候选3b602f90c5f6525e0973ded2268f3a0ca7bcc9ba / Draft PR 2002yy/BallWar#7。实际4.7.1导入成功、10个核心runner与EndToEndContinueMain通过，SettingsAndResult扩展测试虽exit0/PASS却有2条缺失Main.player_settings脚本错误；整体11/12，未合并。首次兼容测试未隔离user://，旧玩家设置无法核实；后续独立APPDATA/LOCALAPPDATA+引擎探针证明隔离后复验同结果，已如实记录BallWar交接，不掩盖错误。496项仅CRLF导入元数据恢复，原6项混合工作树改动未动。此迁移阻塞单独修复，不趁CLI片改玩法。
**2026-10-21 CLI-01审阅收口。** #266旧head832cbcc2 / PR CI39458046112后台，finding PRRT_kwDOSYWoX86ubDa_有效：Ctrl-C未转JSON/5。新增负控在旧代码实际FAIL（studyctl-cancel-negative.log），现在main边界捕获KeyboardInterrupt，给cancelled脱敏结果，退出5且无traceback。最终命名L1 studyctl **156 PASS/52.72s**，自身14项；CLI独立mypy PASS、src122/128 NEW0复用未改src同树证据，Ruff/format/diff-check PASS；secret另记发布结果。本段提交恢复候选，修复后推送绑定新CI，旧头绿灯不能授予新head。CLI-02基于自身冻结832开发，发布前显式吸收此修复；BallWar4.7独立Draft #7整体11/12，设置旧接口脚本错误未解决，未合并。

**2026-10-21 CLI-01：studyctl基础查询独立片。** branch codex/studyctl-foundation-20261021，固定已合main069fc126；无其他窗口WIP，root4个ZIP保留。tools/studyctl.py为标准库本地入口，status/doctor/help读取Git和权威文件，不导入产品/模型/凭据、不联网或启动测试；Git禁optional locks及fsmonitor，日志脱敏，stdout一份JSON，明确0/2/3/4/5退出码。显式output以同目录临时文件+hard link拒绝覆盖，dry-run不落盘。注册仅两个精确CLI路径，未知路径仍扩大，未将整个tools或CI类别映射到小门。命名L1 studyctl **155 PASS/50.47s**（自身13项真实Git/子进程），src mypy122/128 NEW0；CLI独立mypy最初发现argparse.error返回注解不匹配，现改NoReturn，复验另记；Ruff/format/diff-check与密钥检查以发布结果恢复。无生产行为/权威/schema变更，无本地L3。CLI使用见docs/STUDYCTL.md。下一自身小片：test plan直接复用classify/load_manifest/resolve，仅计划不执行；不把full_scope/l3_eligible当作自动执行L3的许可。

**2026-10-20 #248重绑已合main。** #247在3bfefb2c / CI39383248671 SUCCESS / 无finding后expected-head合main8a66eccf（完整SHA以Git恢复）。本片吸收该main，merge6914c74c，冲突仅旧loop默认路径与自身可选answer_handler、其测试、docs/manifest；保留自身已审阅实现，输入模块与main相同，不混入后续generator或SDK。main增量仍5文件。命名L1 conversation_loop_answer **299 PASS/101.92s**，mypy122/128 NEW0、Ruff/diff-check PASS，候选SHA以本段提交恢复。先将PR base改main，再推候选触发synchronize，避免上一片retarget期间缺失CI；旧39e38bd3绿灯不授予新head。无本地L3，当前新owned绑定/可选API独立开发。

**2026-10-19 CL-1E-2：loop可选回答接线（本轮第二片）。** branch codex/conversation-loop-answer-20261019，固定base自身#247 3390fafd3ee9d1e3de0c028a6c10d1ed94d7db68。run_conversation_loop新增可选answer_handler，经过原dispatch准入、freshness、超时和取消后，收到当前提议对应的AnswerInput；阶段回复在执行完成后才入trail，最终回答收到此前全部阶段及工具观察。原ActionInvocation和默认handler路径兼容，不改生产聊天入口。实际生成预算、权限、输出与证据校验由可信适配器负责；输入拒绝统一经原handler失败通道，不启动后续tool。新增8个用例覆盖前后阶段衔接、两工具累计、旧handler覆盖、新意图拒绝、阶段后关闭、失败/空/超长输出停止和调用者取消传播。无真实模型/SDK/付费调用/生产聊天或发布权威切换，无本地L3。命名L1 conversation_loop_answer **299 PASS/69.10s**，mypy122/128 NEW0、Ruff/format/diff-check PASS、secret findings0。候选SHA以本段提交恢复。

#247 head3390fafd / pull_request CI39262160573后台执行，review暂无finding；#240已合main cf70e688 / push CI39261429543后台，旧main969fb53a CI39255920427 SUCCESS。#242已重绑main并推送91af16b5，命名联合278 PASS，等待新head自身CI；不借旧绿灯。下一执行片：可信回答生成适配器的独立准入合同与有界调用（继续保留生成费用和正式证据验收门）。
**2026-10-20 #247缺失exact-head CI恢复。** head2c681ed66fc3b2f360992a0f00c2b8ed1c4cff81已推送且PR base为main/mergeable CLEAN，但statusCheckRollup与该commit check-runs均为空，branch run列表只有旧3390fafd绿灯；不能借旧CI合并。当前追加本段交接产生新synchronize事件，保留完全相同生产/测试树与已验413 PASS/126.44s、mypy122/128 NEW0；仅docs不重跑全量或L1，仍要求新head自身CI。当前main b6aee2b72e8904e0a382bd9a93469168f48bf71b / push CI39381453432 SUCCESS。

**2026-10-20 #247重绑累计loop主线。** #246在heade663d9a654b4dca3b139aa6da704de632ca2e212 / CI39377648481 SUCCESS / 无finding后expected-head合入main b6aee2b7（完整SHA以Git恢复）。本片吸收已合main（merge f189deca），冲突仅docs/manifest与精确CI路径，保留answer_input模块登记与消费门及双方交接。main增量仍7文件，未取其他窗口WIP。重绑后命名L1 conversation_answer_input **413 PASS/126.44s**，mypy122/128 NEW0、Ruff/diff-check PASS；src中的输入模块与已审阅3390fafd一致，无本地L3。旧head CI不授予新候选，新head以本段提交恢复，推送后base main单独CI。用户已明确仅DeepSeek，旧待答记录失效，本轮新服务和进度片另行独立开发。

**2026-10-19 CL-1E-1：有界回答输入（本轮第一片）。** branch codex/conversation-answer-input-20261019，固定base自身#246 5e6e26623ad216690274d0edbc18660bd00d376a，未读其他窗口WIP。AnswerInput把当前上下文、精确提议、阶段和完整累计观察作为独立数据交给可信回答适配器；验证初始/后续身份与额度、拒绝未完成answer/tool配对，序列化数据上限64000字符，超限拒绝不截断。保留历史、证据摘要及unverified标记，决策理由不冒充研究发现。注册两个精确CI路径与消费者门，无前缀通配。#240已在head c9d73977 / CI39256503247 SUCCESS / finding已解决后合main cf70e688c91fe93cd259c10c6dc7d00a1b2e4586。输入模块尚不生成回答；下一片将其接入受控loop的可选回答处理器。未接生产聊天/SDK/付费调用/发布权威，无本地L3。命名L1 conversation_answer_input **413 PASS/117.09s**，mypy122/128 NEW0，Ruff/format/diff-check PASS，候选secret findings0；候选SHA由本段提交恢复。

**2026-10-19 CL-1D-6 最终父片绑定。** 已吸收自身#245冻结修复ad0b2e32f235fb7739ba6a05729193a3b61566bf（逐次额度与精确路由两个已解决finding）；冲突仅交接，保留双方。新模块/CI路径来自已提交自身父片，非WIP。最终命名L1 conversation_loop_trail **277 PASS/103.24s**，mypy122/128 NEW0、Ruff/format/diff-check PASS；候选SHA由本段所属提交恢复；#245两个finding4313958266/4313958272均已修并解决，修复后CI39255166237后台执行；父片CI继续后台执行，不借旧7b6fb566绿灯。
**2026-10-20 #246重绑已合main / 最新选择覆盖下方待答状态。** 用户已明确仅DeepSeek，先前凭据选择不再阻塞；新功能#252及独立session分支已继续，未调用真实服务。#245在head226c0d3182f9e597870179f39aaa5379ee3d17a9 / CI39376484599 SUCCESS / 两finding已解决后expected-head合入main9ae37d4c（完整SHA见Git）。本片吸收此main，仅docs/manifest冲突，保留双方交接与loop_trail命名门；生产与测试树须核验和已验证d7102e3a相同，因此复用该同树L1 277 PASS/94.49s、mypy122/128 NEW0，不机械重跑相同门。当前新head只以本段提交恢复，旧CI39376553152不授予新SHA；推送后base main且CI单独绑定。无本地L3。

**2026-10-20 #246主线整合候选。** 本轮完成两个已有功能分支的主线收口，未新增SDK接线代码。#246已吸收自身#245最新冻结226c0d3182f9e597870179f39aaa5379ee3d17a9（其main为已合#244的5cd917ad）；第二次吸收仅交接冲突，保留双方，不改变生产代码。最终命名L1 conversation_loop_trail **277 PASS/94.49s**，mypy122/128 NEW0、Ruff/diff-check PASS，密钥扫描见本段发布命令；src相对已审阅5e6e2662的差异仅来自已合main context和已冻结父片，loop自身行为未变。本片相对#245增量5文件，候选SHA以本段提交恢复，base维持自身#245。旧5e6e2662绿灯不授予新head；推送后绑定新CI，不等待CI才推进。#245首次推送遇TLS EOF，使用命令级HTTP参数重试已成功，无全局Git配置修改。

SDK接线所需的现有凭据复用选择已通过异步问题提交，尚无答复；本轮原拟新工作树conversation-model-transport-20261020留在9f0c1f14，tracked clean，无SDK/真实调用或配置修改。该选择仅限制后续API接线，不阻断已有合并/聚焦验证。下一执行动作：凭据选择后继续网关接线；选择前仅推进自身成熟片的main整合，不把问题未答当授权，不重复等待CI。

**2026-10-19 CL-1D-6 最终父片绑定。** 已吸收自身#245冻结修复ad0b2e32f235fb7739ba6a05729193a3b61566bf（逐次额度与精确路由两个已解决finding）；冲突仅交接，保留双方。新模块/CI路径来自已提交自身父片，非WIP。最终命名L1 conversation_loop_trail **277 PASS/103.24s**，mypy122/128 NEW0、Ruff/format/diff-check PASS；候选SHA由本段所属提交恢复；#245两个finding4313958266/4313958272均已修并解决，修复后CI39255166237后台执行；父片CI继续后台执行，不借旧7b6fb566绿灯。
**2026-10-20 #245主线重绑收口。** #244在head0f9142442e0a15bee84a32a7d88a9112b7d88e96 / pull_request CI39296775208 SUCCESS / 无未解决finding后expected-head合入main 5cd917ad1c03fb520ce512605aa49bfd82f09216。本片吸收已合main（merge049831e4）；main中followup的内联稳定ID与本片提取helper冲突，显式保留本片已审阅helper与相同JSON/hash算法，CI仅保留trail两个精确路径及完整消费者，文档保留双方，context模块/测试来自已合main。main增量8文件，未导入其他窗口WIP。命名L1 conversation_observation_trail **394 PASS/126.89s**，mypy122/128 NEW0、Ruff/diff-check PASS；无本地L3，无新SDK/API或付费调用。新候选SHA以本段提交恢复，旧ad0b2e32绿灯不授予新head；推送后base main及新CI单独绑定。#246同步吸收本片冻结结果并在独立工作树跑联合门。下一功能接线的凭据复用选择仍待用户回答：按已读取openai-platform-api-key技能暂停SDK接线，现存配置不修改；空新工作树conversation-model-transport-20261020固定9f0c1f14且无代码更改。



**2026-10-19 CL-1D-6：多步流消费累计记录（本轮第二小片）。** branch `codex/conversation-loop-trail-20261019` / worktree `D:/study-agent-validation/conversation-loop-trail-20261019`，初始固定base自身#245提交7b6fb5668f9eb91334430f0b9f4d4dc7575a752d，发布前还需吸收本轮#245逐次额度/精确CI修复。未导入其他窗口WIP。

run_conversation_loop改为收集answer_then_research的阶段回复及每次成功确定工具观察，后续模型输入使用完整ObservationTrail；派生当前身份先加入frame再请求模型，仍还原真实研究版本以验证STEER回执。原history/evidence摘要不改写，最多8次决策/16记录/16000个序列化字符，额外输入精确计入共享DecisionAdmission。容量耗尽给observation_limit并关闭内层流：已完成的原文观察仍交付、不截断；若阶段回复已超容量，其后已预留但未执行的tool不会启动，不退款或自动重试。完整八步验证了输入记录数2/4/6/8/10/12/14，边界停止仍有结构化session回执。

本地新增5个执行器用例（含容量分支参数），执行器38 PASS；初步命名L1 conversation_loop_trail 274 PASS/101.70s，mypy122/128 NEW0、Ruff/format PASS；吸收父片审阅修复后的最终结果另记。当前先本地提交以保护独立片，再合入父片已冻结修复，尚未推送此旧候选。无真实模型/付费调用/生产聊天/UI/业务schema/发布权威切换，无本地L3；测试仅证明数据与执行顺序，非真实模型回答质量。唯一下一动作：最终联合门、独立PR与一次exact-head CI；继续按主线成熟度逐片合并。
**2026-10-20 #245主线重绑收口。** #244在head0f9142442e0a15bee84a32a7d88a9112b7d88e96 / pull_request CI39296775208 SUCCESS / 无未解决finding后expected-head合入main 5cd917ad1c03fb520ce512605aa49bfd82f09216。本片吸收已合main（merge049831e4）；main中followup的内联稳定ID与本片提取helper冲突，显式保留本片已审阅helper与相同JSON/hash算法，CI仅保留trail两个精确路径及完整消费者，文档保留双方，context模块/测试来自已合main。main增量8文件，未导入其他窗口WIP。命名L1 conversation_observation_trail **394 PASS/126.89s**，mypy122/128 NEW0、Ruff/diff-check PASS；无本地L3，无新SDK/API或付费调用。新候选SHA以本段提交恢复，旧ad0b2e32绿灯不授予新head；推送后base main及新CI单独绑定。#246同步吸收本片冻结结果并在独立工作树跑联合门。下一功能接线的凭据复用选择仍待用户回答：按已读取openai-platform-api-key技能暂停SDK接线，现存配置不修改；空新工作树conversation-model-transport-20261020固定9f0c1f14且无代码更改。


**2026-10-19 #245 审阅修复 / 逐次额度与精确路由。** finding4313958266有效：只比较root减工具次数会恢复并发额外消耗的额度。现每个tool frame后将下一帧额度上限收紧为该帧before.remaining_tool_calls-1，新增3组并发大幅扣减→非法恢复负控，合法后续零额度上下文仍可回答。finding4313958272也有效：新增trail模块/测试未登记会让普通后续修改回退全量。现仅登记这两个精确路径，连同原14个共16路径；同前缀新路径仍回退，admission/context/共享/CI/资格/未知范围不缩小。联合影响集conversation_observation_trail加入ci_scope/ci_workflow_routing/ci_outcomes，最终394 PASS/131.04s；Ruff/format、mypy122/128 NEW0、diff-check PASS。当前candidate SHA由本段提交恢复，旧7b6fb566 CI39254094559不授予修复后head；推送后解决已修finding并绑定一次CI。新scope为8文件（原6+CI分类与测试），不是单方面跳过CI或发布资格。


**2026-10-19 CL-1D-5：累计观察与阶段回复输入（本轮第一小片）。** branch `codex/conversation-observation-trail-20261019` / worktree `D:/study-agent-validation/conversation-observation-trail-20261019`，固定base为自身已提交#244 `e05e39e16307af47a2933df8164c5860b1f598d2`；未取其他窗口WIP。#236在headbbcef47d / CI39221498204 SUCCESS / 无未解决finding后已expected-head合入main9684aa829c6b5cc4e8d70ff4754ecb4302557043；旧mainafa54501 CI39221117547 SUCCESS。#239旧2bcb4e4c已有绿灯与已解决review，正单独重绑新main再绑定新CI；#240/#242/#244原冻结head的CI本轮起始均SUCCESS，无未解决finding，仍按依赖顺序逐片调整主线，不能借旧绿灯。

新增ObservationFrame/ObservationTrail与decide_with_observation_trail：不可变地保留本轮阶段回复和全部工具结果，配对ANSWER_THEN_RESEARCH的answer→tool并验证连续派生请求、原意图/历史/研究及累计额度；最多16个阶段和16000个实际序列化字符（含转义），超限拒绝而非隐式截断。阶段回复和工具结果作为标记unverified的独立JSON数据，原chat history与evidence_summary不被改写；阶段回复要求模型衔接而非重复，工具输出不成为权限或正式证据。额外消息准确计入原DecisionAdmission，沿用超时/取消/迟到/当前快照校验。稳定工具后续身份提取为tool_observation_request_id供记录验证共用，JSON算法与旧持久身份逐字一致，不迁移账本、不重置去重。

新增32项自身测试PASS，mypy122/128 NEW0、Ruff/format PASS；命名L1 conversation_observation_trail（自身+followup/loop/session/step/dispatch/runner/admission/decision/阶段策略）最终 **269 PASS/134.39s**。新模块尚未被多步loop消费，由本轮第二片CL-1D-6接线；无生产聊天/SDK/付费调用/业务schema/UI或发布权威变更，无本地L3。候选SHA以本段所属提交恢复。下一动作提交独立PR并后台CI，继续实现loop累计输入与真实限额停止负控，不能把脚本模型控制流当真实智能验收。
**2026-10-20 #244主线重绑。** #242在91af16b5 / CI39262262003 SUCCESS / finding已解决后合main ab1e5ab4；本片吸收此已合主线，merge d6578988，仅docs与manifest冲突，保留双方。main增量仅两份docs、CI分类/测试及manifest，src与main逐字相同。命名L1 conversation_loop_ci_scope **132 PASS/46.05s**，Ruff/diff-check PASS；非生产改动，未重复全量/mypy。候选SHA以本段提交恢复，旧e05e39e1绿灯不授予新head；推送后绑定新CI并改base main。下一功能片在独立工作树继续受控回答生成和loop适配。


**2026-10-19 CI-CL-2：精确CI路径与新消费者（本轮第三小片）。** branch `codex/conversation-loop-ci-scope-20261019` / worktree `D:/study-agent-validation/conversation-loop-ci-scope-20261019`，初始base自身150ae5ec，最终显式吸收自身#242冻结修复 `827b81adfc6562c6403bc68c90c9431cda68768c`；该parent已经包含#239重放身份与#240工具后STEER两项review修复，未取其他窗口WIP。新增范围仅tools/ci_scope.py、tests/test_ci_scope.py、manifest与两份交接/合同文档。

精确登记dispatch/step/followup/bounded_loop/loop_session五个模块及各自测试；与原decision/runner共14路径映射共享conversation_decision_1b。没有conversation_*通配跳过，也不登记admission/context；持久/共享domain/SQLite、生产路由、CI工具、资格协议、未知路径混入仍扩大范围。补全命名开发门的新直接消费者清单，详情见CONVERSATION_AGENT_LOOP_PLAN的CI-CL-2；路由测试核对真实文件、manifest消费者集合和25组未登记/持久路径混入负控。CI自身改动不套用本片新增快速分类，workflow/权限/预算/强制L3/发布门不变。首次manifest误写test_workflow_routing.py被预检阻止（尚未跑pytest），已改为真实test_ci_workflow_routing.py；未绕过校验。

当前验证：CI影响集conversation_loop_ci_scope **132 PASS/34.88s**；Ruff/diff-check PASS。src及功能测试与parent827b81ad逐字一致，沿用其mypy122/128 NEW0及session影响集223 PASS/65.38s范围证据，不冒称新SHA重新跑过产品全量；前两片loop最终215 PASS/67.23s，session最终223 PASS。无本地L3/SDK/付费调用/生产切换/UI。#233已合main5ead630fd902360ddff0f5694fbf4f3ddad74140，exact-main CI39217839722 SUCCESS，根main已ff同步并保留4个外部ZIP；#235新5566aa4d / CI39219048419，#239新2bcb4e4c / CI39219767478，#240新778d0003 / CI39220080887，#242新827b81ad均需各自最新CI；已修finding4311370434/4311446891/4311507599已解决，旧head绿灯不能授予新head。本轮新增#240/#242与本片独立PR，候选SHA以本段所属Git提交恢复。唯一下一功能片：有界累计工具观察与阶段回复输入，避免模型只看到最近一次结果；合并仍按最新head审阅+CI逐片完成，不等待后台CI才开发。
**2026-10-19 #242 主线重绑。** 已吸收自身#240合并main cf70e688c91fe93cd259c10c6dc7d00a1b2e4586，merge bcc4d3f1；冲突仅两份文档与manifest，保留双方记录及context测试。session生产代码与原827b81ad相同；当前main增量5文件。命名conversation_decision_1b **278 PASS/91.45s**，Ruff/diff-check PASS，mypy122/128 NEW0；无本地L3。旧CI39220756792不授予新候选，推送后重绑PR base main并记录一次exact-head CI。下一功能片为累计回答输入与loop可选接线，未接其他窗口WIP。

**2026-10-19 #242 审阅修复 / 终态后的close_error。** finding4311507599有效：有效LoopStopped后清理异常先记close_error，又被_next通用异常覆盖成stream_error。新增内部专用关闭异常分流，保留failed/close_error、unknown与脱敏错误，不把终态观察提升为清理成功。新增精确负控；最终命名L1 conversation_loop_session 223 PASS/65.38s，mypy122/128 NEW0、Ruff/format/diff-check PASS。候选head由本段所属提交恢复，旧a88a4f42不授予新head；推送后绑定一次CI并解决已修finding。

**2026-10-19 #242 父片修复整合。** 吸收自身冻结#240 head778d0003，含#239不可变观察身份与#240工具后STEER派生身份两项有效review修复；文档冲突保留双方。session生产代码不变，联合影响集conversation_loop_session 222 PASS/61.01s、mypy122/128 NEW0、Ruff/diff-check PASS后推送，新head独立绑定CI，旧150ae5ec结果不授予新head。CI-CL-2为本轮第三小片，继续基于本分支冻结结果登记精确路径与完整消费者集合。


**2026-10-19 CL-1D-4：单次消费与运行回执（本轮第二小片）。** branch `codex/conversation-loop-session-20261019` / worktree `D:/study-agent-validation/conversation-loop-session-20261019`，固定base为自身#240 `672fd1228eaeb1fc688eae424a6fe6160fd0ae66`，其PR CI39218240337后台执行。新main为已发布#233的5ead630f（CI39217839722后台），#235旧f4209544 CI39216114150已绿但需整合新main交接再绑定新head；未借旧绿灯合并。

新增ConversationLoopSession与不可变LoopReceipt：events()同步claim唯一消费句柄，不开始模型；关闭未读句柄也可靠关闭source。主动关闭、外部取消、正常终态、无终态流与异常明确分开，回执只含身份/步数/观察计数/状态，不存提示或工具正文；同实例不能再开消费句柄，新实例也仍受原共享准入去重。活动pull被取消时保留unknown，已发生的工具动作不声称回滚；暂停或断开后能查看本进程回执，不自动重放，不提供跨进程持久恢复。并发读取拒绝、active close取消内部pull、关闭失败脱敏且标记failed，关闭中的调用者取消仍传播。

新增21项自身测试；命名L1 conversation_loop_session **212 PASS/73.64s**（自身+loop/followup/dispatch/runner/admission/decision/阶段策略）；Ruff/format与mypy122/128 NEW0 PASS，diff-check/候选扫描随提交完成。无生产聊天/SDK/付费调用/持久业务schema/UI或发布权威变更，无本地L3。候选SHA由本段所属提交恢复。下一片CI-CL-2：为这些明确可追踪的新消费者登记精确CI路径与共享影响集，避免普通局部修改因未登记路径反复全量；未知路径/共享权威仍保守扩大。
**2026-10-19 #240 审阅修复 / 工具后STEER身份。** finding4311446891有效：frame投影因研究版本更新退回raw root request_id，成功STEER回执无法匹配。现只在原请求/用户/历史仍一致时重建派生身份；研究快照用于身份重建后立即恢复为真实fresh快照，执行前与完成时的版本/typed receipt校验均保留，绝不允许任意新版本。新增工具→STEER成功、并发版本、换题、handler启动前版本变化及工具→QUEUE五项回归。显式吸收自身#239的不可变source身份修复2bcb4e4c；原672fd122 CI不授予新head。候选SHA由本段所属提交恢复；命名L1 conversation_bounded_loop 215 PASS/67.23s，mypy122/128 NEW0、Ruff/format/diff-check PASS。修复将带入#242和CI-CL-2，不等待CI才开发。

**2026-10-19 本轮两片收口 / #240重绑main。** #236在bbcef47d / CI39221498204 SUCCESS后合main9684aa82，其exact-main CI39252662563 SUCCESS；#239在09283d0f0625c95520772ec92a7e3c4b119525b8 / CI39253778617 SUCCESS / 无未解决finding后expected-head合main `969fb53abb4f4f42999e48713543db6006c91c2f`，根main已ff同步，4个外部ZIP保留，新main push CI39255920427后台in_progress。#240原778d0003 / CI39220080887 SUCCESS且STEER身份finding已解决，现吸收发布main，仅交接/impact冲突，保留双方，loop生产树不变；共享影响集conversation_decision_1b 256 PASS/98.16s，mypy122/128 NEW0、Ruff/diff-check PASS，base改main，新head独立CI，不借旧绿灯。

本轮新增两片均已推送：#245累计观察/阶段回复输入，headad0b2e32f235fb7739ba6a05729193a3b61566bf / CI39255166237后台in_progress，L1联合CI 394 PASS/131.04s、35项自身测试；#246执行流消费累计记录，head5e6e26623ad216690274d0edbc18660bd00d376a / CI39255727257后台in_progress，L1 277 PASS/103.24s、执行器38项通过。两片mypy122/128 NEW0、Ruff/format/diff-check与密钥扫描0 finding，工作树干净。#245的逐次额度finding4313958266与精确路径finding4313958272已修并解决，完整进入#246；未知路径和发布/强制门未缩小，#246实际差异选择conversation_decision_1b、full_scope/frontend/browser=false。没有本地L3、SDK/付费调用、生产聊天或UI切换；测试仅证数据/控制流，非真实模型回答质量。唯一下一功能片：提供给可信回答handler的有界累计输入，同时按最新head CI/审阅继续把自身成熟片移入main，不等CI才开发。候选SHA由本段所属提交恢复。


**2026-10-19 #240 审阅修复 / 工具后STEER身份。** finding4311446891有效：frame投影因研究版本更新退回raw root request_id，成功STEER回执无法匹配。现只在原请求/用户/历史仍一致时重建派生身份；研究快照用于身份重建后立即恢复为真实fresh快照，执行前与完成时的版本/typed receipt校验均保留，绝不允许任意新版本。新增工具→STEER成功、并发版本、换题、handler启动前版本变化及工具→QUEUE五项回归。显式吸收自身#239的不可变source身份修复2bcb4e4c；原672fd122 CI不授予新head。候选SHA由本段所属提交恢复；命名L1 conversation_bounded_loop 215 PASS/67.23s，mypy122/128 NEW0、Ruff/format/diff-check PASS。修复将带入#242和CI-CL-2，不等待CI才开发。
**2026-10-19 #239 重绑发布main。** #236在bbcef47d81150cca08f29e0bfdd84f052a3f0bea / CI39221498204 SUCCESS / 无未解决finding后expected-head合入main9684aa829c6b5cc4e8d70ff4754ecb4302557043；前mainafa54501 CI39221117547 SUCCESS。本#239旧2bcb4e4c / CI39219767478 SUCCESS且重放身份finding已解决，现吸收发布main，交接与impact冲突保留双方、followup生产逻辑不变；整合共享影响集conversation_decision_1b 223 PASS/118.69s，mypy122/128 NEW0、Ruff/diff-check PASS后推送并将base改main，旧绿灯不授予新head。本轮累计观察/阶段回复另在独立分支推进。

**2026-10-19 #239 审阅修复 / 观察重放身份。** finding4311370434有效：原hash包含整个previous，调用方重建旧上下文可使同一工具事件重新取得模型准入。现仅以不可变source request_id + USE_TOOL阶段派生后续身份（一个已准入提议最多一次工具阶段），不纳入证据/额度/能力、提议措辞或结果正文。新增5项SQLite重开负控覆盖这些重建变化，命名L1 conversation_observation_followup 182 PASS/49.08s。旧head756a6e22 / CI39217176655 SUCCESS不授予修复后head；推送后一次绑定CI并解决已修finding。修复将显式带入自身#240/#242及第三片CI路由，不依赖其他窗口WIP。


**2026-10-19 CL-1D-3：有界多步事件流（本轮第一小片）。** branch `codex/conversation-bounded-loop-20261019` / worktree `D:/study-agent-validation/conversation-bounded-loop-20261019`，固定base为自身#239 `756a6e22a8c6021248270f4366bfa9c094391ed7`。#233在head224cae06 / CI39215954538 SUCCESS / finding已解决后expected-head合入main `5ead630fd902360ddff0f5694fbf4f3ddad74140`；上一个main9e36b935 CI39215516784 SUCCESS。其他窗口WIP未导入。

新增 `run_conversation_loop`、LoopLimits、LoopStopped：串联决策→分发→成功工具观察→回填→下一决策；直接回答/澄清/转向/排队收束本轮，仅成功确定的工具结果能继续。1–8步硬上限、共享DecisionAdmission/ActionBudget及含消费者暂停的总时限，单次模型/动作还受原限额约束。公开事件流保留DecisionResult/ActionEvent，不吞初步答案；正常结束给一个结构化停止原因与步数/观察数，取消/关闭传播至内层，不能将其解释为外部执行已回滚。新意图或研究变化停止，工具消耗未由服务端记录则拒绝继续。后续只回填最近一条工具观察，完整多观察累积/实际模型质量另验；不把控制顺序测试当产品智能验收。

新增28项测试覆盖三次工具后回答、先答再查的可见顺序、步数/双预算、关闭/取消、换题/研究变化、未记额度、总时限和脱敏。命名L1 conversation_bounded_loop（自身+followup/step/dispatch/runner/admission/decision/阶段策略）最终205 PASS/56.49s；Ruff/format、mypy122/128 NEW0与diff-check PASS；候选SHA由本段所属提交恢复。无SDK/付费调用、生产路由/持久业务schema/UI/答案权威变更，无本地L3。下一片CL-1D-4：单次消费的运行回执与中断边界；本轮继续开发，不因本片推送而结束。


**2026-10-19 CL-1D-2：有界工具观察回填（当前独立小片）。** branch `codex/conversation-observation-followup-20261019` / worktree `D:/study-agent-validation/conversation-observation-followup-20261019`，显式固定base为自身#236冻结head `2ce7dbe7c0cdd7e8a3d07422464727a0bd9cb179`；未取其他窗口WIP。#232已expected-head合入main `9e36b9359f4224735c30d163ff9e105932bc1eea`，根main已ff同步，4个外部IA-1A未跟踪ZIP完整保留；其main CI39215516784在后台。#233整合main后head224cae0664b35a40f1e115e3f44d7ecb1239e0be / CI39215954538；#235修复版本回执finding并整合main后headf42095445331b1666e0f2087153629e9b1a44e02 / CI39216114150；#236吸收修复后head2ce7dbe7 / CI39216194104；上述最新CI快照in_progress，均不借旧绿灯合并。#235 finding4307918994已解决，本地共享影响集164 PASS；#236影响集134 PASS。

新增 `decide_after_tool_observation` 与纯投影 `tool_followup_context`：仅接受同一请求、成功且确定的USE_TOOL观察及经校验的原提议；服务端必须已记录至少一次工具消耗，换题/改历史/改研究快照拒绝。观察以单独JSON消息标记unverified，原证据摘要/用户意图保持原样；固定系统说明不插入观察内容。序列化观察包上限8000字符，超限拒绝而不悄悄截断。额外两条消息的准确字符数先经过原DecisionAdmission准入，再提交注入式模型；沿用原超时/取消/迟到/提议校验与no-retry。观察身份稳定派生为新request_id，证据或预算刷新不能给同一观察换身份重试；兼容进程预算和已合并SQLite账本，不存工具正文。宿主可用公开投影执行下一提议，本函数不自动执行或发布。

验证：新增22项自身测试PASS，包括scripted模型→本地实际加法→观察回填→下一决策→宿主执行回答，及SQLite重开去重/完整提示计费、原证据保留、提示数据与指令分离、转义后包体超限、旧身份/未消费额度/换题拒绝、取消与超时；只证明控制流和消息边界，不证明真实模型智能或抗注入质量。命名L1 conversation_observation_followup含step/dispatch/runner/admission/decision/阶段策略，最终 **177 PASS / 47.97s**。Ruff/format、mypy122/128 NEW0、diff-check PASS；无SDK/付费模型、无生产路由、无业务schema或前端变更，无本地L3。候选SHA由本段所属Git提交恢复；下一动作独立stacked PR并一次绑定exact-head CI。唯一后续片CL-1D-3：有界多步事件流与终止原因，继续由总决策/动作预算约束，不引入生产发布权威。

**2026-10-19 本轮三片与main整合收口（#236当前候选）。** #233已在224cae06 / CI39215954538 SUCCESS后合main5ead630f，其exact-main CI39217839722 SUCCESS；#235已在5566aa4d7c2c1968b9f82bd57cbc277d7a6a1d7b / CI39219048419 SUCCESS / 版本回执finding已解决后expected-head合main `afa5450143ca8a569d621487d2d3b00d415a9565`，push CI39221117547后台in_progress，根main已ff同步、4个外部ZIP保留。当前#236已吸收该发布main，add/add冲突实质仅AsyncIterator→AsyncGenerator两个注解，保留正确可关闭类型；交接/impact冲突保留双方。对main差异仍仅原单步编排6文件，未引入其他窗口WIP；整合后conversation_decision_1b 196 PASS/51.22s、mypy122/128 NEW0、Ruff/format/diff-check PASS；候选SHA由本段所属提交恢复，需绑定新exact-head CI，旧2ce7dbe7绿灯不授予新head。PR base改main。

本轮新增三片均已推送：#240有界多步流，最终head778d0003174c8cde39e8f130455831505386d399 / CI39220080887，命名L1 215 PASS/67.23s；#242单次消费/运行回执，最终head827b81adfc6562c6403bc68c90c9431cda68768c / CI39220756792，L1 223 PASS/65.38s；#244精确CI路径/完整消费者，heade05e39e16307af47a2933df8164c5860b1f598d2 / CI39221109190，L1 132 PASS/34.88s。三项CI最后快照in_progress，未合并或上线。#239重放身份finding4311370434已修且解决，head2bcb4e4c13128c8090403240c9370fcd944a00c5 / CI39219767478 / L1 182 PASS；#240工具后STEER finding4311446891和#242终态close_error finding4311507599也已修并解决，修复完整进入后续片。各review修复只复验对应影响集，没有机械跑本地L3。完整真实模型/累计观察/生产聊天/付费工具联动仍未验收。唯一下一功能片：基于自身#244冻结结果做有界累计工具观察与阶段回复输入；同步按新head CI/审阅逐片合并，不等后台CI才开发。

**2026-10-19 #236 修复集成。** 原head0f715a27 / CI39148846133 SUCCESS；因父片#235 finding4307918994已修，现显式吸收自身冻结修复5186abb9与已发布main9e36b935。冲突仅交接与impact列表，保留step和admission两项测试；step生产逻辑不变。单步/分发/决策/runner影响集134 PASS/36.92s；最终吸收f4209544仅同步父片文档，生产树与受测8a04a571一致，未重复测试。最新head需独立CI；旧绿灯不授予新head。本分支仍基于自身#235，不依赖其他窗口WIP。下一片有界观察回填独立推进。


**2026-10-19 CL-1D-1：受控单步编排（当前独立小片）。** branch `codex/conversation-action-step-20261019` / worktree `D:/study-agent-validation/conversation-action-step-20261019`，显式固定 base 为自身 #235 head `bcdaa4b77933551702849ab383cd3cbe15b76993`；未依赖其他窗口 WIP。新增 `run_conversation_step`，一次受控决策 → 提议事件 → 动作观察流，共用总时限；消费者暂停计入时限，关闭外层流会关闭分发流，决策失败不调用动作、换题拒绝旧动作、取消传播到正在执行的适配器。观察保留原 attempted/outcome_unknown，不自动重试、开启下一决策或授予证据/答案权威。无生产聊天/SDK/付费调用接线。

命名 L1 `conversation_action_step` **127 PASS / 33.91s**（新增14项 + 分发/决策/runner/阶段策略）；Ruff/format PASS，mypy122/128 NEW0。类型门先发现 aclosing 不接受仅声明 AsyncIterator 的分发 API，已将其注解收紧为真实 AsyncGenerator，明确可关闭协议，运行行为不变；未放宽 baseline。共享 legacy1b 添加此消费者。无本地 L3、无 UI 变更。最终候选 SHA 由本段所属 Git 提交恢复；待独立 stacked PR/一次 exact-head CI，#235 合并后调整 base main。当前仅验证 scripted 模型和本地工具的控制流，不宣称真实模型质量或产品上线。唯一下一片 CL-1D-2：有界观察回填到后续决策，区分未验证工具输出与已验证证据，并保留提示预算和新决策身份。
**2026-10-19 #235 main集成更新。** #233在exact head224cae06 / CI39215954538 SUCCESS后合入main5ead630fd902360ddff0f5694fbf4f3ddad74140；#235自己的f4209544 / CI39216114150 SUCCESS且版本回执finding已解决，但当前main交接冲突。保留双方交接后吸收已发布context投影，dispatch生产树不变，共享影响集conversation_decision_1b 182 PASS/62.04s覆盖新main消费者后再推送；新head绑定一次CI，不借旧绿灯。自身后续#236/#239/#240与session切片继续独立后台开发，不将其他窗口WIP混入。


**2026-10-19 #235 审阅修复 / 自身版本回执。** finding4307918994 指出成功STEER更新研究版本后被误判过期；新增仅可信handler返回的 SteeringObservation(observation,research_after)，要求同一run且版本前进，并与执行完成时精确研究快照匹配，用户消息/历史/请求仍不得变化。无回执、并发再次推进版本、换题、跨run、旧版本和非steer携回执均拒绝；不是直接允许任意研究版本变化。handler必须在自身事务中取得回执，不能事后读取其他写入者的最新版本冒充。观察仍没有生产applied/证据权威。

本片修复命名L1 conversation_action_dispatch 120 PASS/28.29s，mypy122/128 NEW0；随后合入已发布main9e36b935（#232），保留交接冲突双方，重跑共享影响集conversation_decision_1b 164 PASS/49.02s，覆盖runner/持久准入消费者。候选head由本段所在提交恢复；旧bcdaa4b7 CI39148186998 SUCCESS不授予新head，提交后绑定一次CI并解决已修finding。#236原0f715a27 CI39148846133 SUCCESS，需吸收本修复再更新head；不借旧CI、不等后台CI才开发。下一功能片仍为有界观察回填，独立分支。

**2026-10-19 CL-1D：独立动作分发与观察（本分支当前片）。** #231 已在 head04371329 / CI `39146013970 SUCCESS` / 无未解决 finding 后 expected-head 合并，main `5d4da728162bc974d62d3def40718c78211d5483`。#232 已通过旧05993443 CI，但新 main 仅本交接冲突，保留双方后整合并补 legacy 快速门的 admission 测试，最新 head `58a2f4ae` 已推送，本地命名门137 PASS；#233 已接受 partial-reply finding4307851812，v1 对当前非空 assistant_message 明确拒绝，保留既有 ChatService 续答路径；整合新main并补共享快速门context测试，最新本地候选 `2e44f344`，命名门151 PASS。新 head 均需各自 CI，不借旧绿灯。没有为这些切片/修复再跑本地全量。

当前 branch `codex/conversation-action-dispatch-20261019` / worktree `D:/study-agent-validation/conversation-action-dispatch-20261019`，独立 base 为上述 main，不依赖 #232/#233 或其他窗口 WIP。新增 async generator `dispatch_conversation_action`：仅调用注册的服务端 handler，answer_then_research 先发 answer 观察，再运行 use_tool；每阶段启动前校验当前上下文/研究版本/能力，原子进程内 claim 防重复并限制工具槽。关闭流/取消/期限已过不继续下一阶段；异常脱敏、attempted/outcome_unknown 真实分开，迟到观察丢弃，预算/证据因自身工具变化不误作换题。观察没有 Evidence Gate/正式答案/转向 applied 权威；真实工具权限、参数、费用、持久租约仍由 handler/后续接线负责。

命名 L1 `conversation_action_dispatch` **113 PASS / 34.66s**（自身 + decision + runner + stage policy）；包含 fixture 决策→先答→本地实际求和→观察回传→fixture 决策再回答、单路由、并发重复、预算/能力、调度竞态、用户换题/关闭流、外部与适配器取消、超时吞取消/迟到、无效观察等负控。共享 `conversation_decision_1b` 也登记本新消费者，避免将来共享代码快速门漏测；manifest 键放在独立锚点减少并行 JSON 冲突。Ruff/format、mypy122/128 NEW0、diff-check PASS。无 SDK/付费调用、生产入口/工具权威切换、业务 schema 或前端改动，无本地 L3。候选 SHA 以本段所属 Git 提交恢复。下一动作：提交独立 PR/绑定一次 CI，然后 CL-1D-1 受控单步编排与观察回填；不等待后台 CI 才开发，不以本片称完整 Agent 已上线。

**2026-10-19 #233 集成更新。** #232 在 exact head58a2f4ae / CI39147888463 SUCCESS / finding已解决后 expected-head 合并，main9e36b9359f4224735c30d163ff9e105932bc1eea；main CI39215516784已后台启动。#233 原head2e44f344 / CI39147924617 SUCCESS，但新main交接文档冲突；本片保留双方交接并合入已发布的持久准入实现，生产context投影不变。整合后共享影响集conversation_decision_1b 155 PASS/45.58s、Ruff/diff-check PASS，随后推送；新head需独立CI，不借旧绿灯。没有为文档整合机械跑L3。

**2026-10-19 #233 续答边界修复与 main 集成（覆盖旧可接受 streaming 的无条件表述）。** 接受审阅 finding `4307851812`：ChatService 的 continuation 会复用当前 turn 并保留部分 assistant_message，而 v1 DecisionContext 没有独立的当前 partial-reply 槽。当前投影对非空当前 assistant_message 明确拒绝，不把部分回复静默丢弃或伪装成已完成历史；pending/streaming 两项负控通过。只限制尚未接生产的决策投影，不修改现有 ChatService 的重试/继续功能。支持完整续答的上下文合同仍待独立设计，不冒称已实现。

同步 #231 已合并 main `5d4da728162bc974d62d3def40718c78211d5483`，仅冲突本交接，保留双方记录；共享 `conversation_decision_1b` 补当前 context 测试，防止未来共享模型变更漏掉该消费者。最终命名 L1 `conversation_decision_context`（含相邻 router/task）**151 PASS / 80.41s**，Ruff/format、mypy122/128 NEW0、diff-check PASS；无本地全量。旧 head `2ad75cec` 的 CI 不授予新候选。新 head 由本段所属提交恢复；修复后推送并 resolve finding，绑定一次新 CI。动作分发在独立 main 基线工作树推进，不依赖本片未合并成果。

**2026-10-19 CL-1C-2a：服务端对话快照 → 决策输入（本片覆盖旧 NEXT）。** #230 已在 exact head f706、CI `39143921500 SUCCESS`、审阅 finding 解决后 expected-head 合并，main `0236160e378c0272d7dd9e582e08c12d3ac65fda`；主目录 ff-only 同步且 tracked clean，三个未跟踪 IA-1A 审阅 ZIP 原样保留。exact-main CI `39145457669` 已绑定 0236160e，最后快照运行中，未称 main CI 通过。#231 已重绑 main / ready，head `04371329d94a71bb36160170334888d8f89f1aaf`，同树本地 102 PASS；#232 修复既有空库被接管的问题后重绑 main，head `059934433a755e37770aaf156b46e8b59aa90fdf`，114 PASS，finding `4307789596` 已 resolve。两次 retarget 后无新 head CI，经确认无 run 后各 close/reopen 一次，仅触发缺失的当前候选验证：#231 `39146013970`、#232 `39146011883`（pull_request），已绑定各自新 SHA；不借用旧绿灯、不轮询等候。

当前 branch `codex/conversation-decision-context-20261019` / worktree `D:/study-agent-validation/conversation-decision-context-20261019`，独立 base 为上述 main，不依赖 #231/#232 或其他窗口 WIP。新增 `context_from_chat_snapshots`：会话/turn/operation 所有权、活动/取消状态、当前 turn 的一致快照、跨会话历史与研究归属校验；历史只含前六个 completed 轮次，request_id 稳定绑定服务端身份。该模块只读、无 I/O，不改变业务 schema、聊天入口、外部数据披露、工具执行或证据权威；它不负责多次 DB 读取的原子性，生产调用者仍需一致快照和执行前复核。

本片 L1 `conversation_decision_context` **126 PASS / 37.15s**（自身 + decision + runner + chat_service + stage policy），含真实 SQLite 的落库/reload/不写回、跨会话、过期/取消、重复/不一致当前轮次、历史上限、重试身份隔离等负控。Ruff/format PASS，mypy122/128 NEW0，diff-check PASS；无 L3、无付费调用。候选 SHA 以本段所属提交恢复。下一动作：提交独立候选并开 PR/绑定一次 CI；随后 CL-1C-2b 先定义货币费用与原子读取/提供商适配的边界，后台 CI 不阻塞开发。整个 GPT-like 对话循环与真实模型选择质量尚未验收。
**2026-10-19 #232 合入新 main 的集成候选。** #231 在 head `04371329` / pull_request CI `39146013970 SUCCESS` / 当前审阅无未解决 finding 后 expected-head 合并，main 为 `5d4da728162bc974d62d3def40718c78211d5483`。#232 旧 head `05993443` 的 CI `39146011883 SUCCESS` 与所有权 finding 已解决；与新 main 的唯一合并冲突为本文件，已保留双方交接。本次未改生产源文件，补齐 legacy `conversation_decision_1b` 对新 admission 调用方测试的覆盖，避免以后共享 runner 快速 CI 漏测。该命名集 **137 PASS / 71.06s**；此前自身影响集114的证据保留为同源证据。无本地全量。合并提交 SHA 由本段所属提交恢复，需新 exact-head CI，不将旧 05993443 绿灯授予新 head。#233 正处理续答 partial reply 的审阅边界；独立动作分发分支已开始，后台 CI 不阻塞开发。

**2026-10-19 合并与增量审阅收口（覆盖下方 #230 待合并及空库所有权记录）。** [#230](https://github.com/2002yy/study-agent/pull/230) 已于精确 head `f706db8ce072027d72764f387329599711647d52`、pull_request CI `39143921500 SUCCESS`、无未解决审阅 finding 后 expected-head squash 合并，main 为 `0236160e378c0272d7dd9e582e08c12d3ac65fda`；本地主目录已 ff-only 同步，保留三个未跟踪 IA-1A 审阅 ZIP，tracked clean。exact-main push CI `39145457669` 已绑定 0236160e，快照 in_progress；未借 PR 绿灯称 main CI 已通过。#231 已重绑 main，head `04371329d94a71bb36160170334888d8f89f1aaf`，3 文件，ready for review；与旧 4ba7b6ad 整树相同，保留 102 PASS 的同树本地证据，旧远端 CI 不授予新 head。

#232 审阅 finding `4307789596` 接受并修复：原实现会初始化预先存在的空 SQLite 文件；现在只允许本调用通过 O_EXCL 独占新建的文件初始化，已有文件先以 read-only URI 核验完整所有权/额度，拿写锁后再核对一次；零字节空文件与合法空 SQLite 均负控证明原字节不变。初始化中断遗留无所有权文件只会 fail closed，不自动删除/接管。修复后的命名 L1 **114 PASS / 34.14s**，Ruff/format、mypy122/128 NEW0、diff-check PASS；无本地全量、无真实付费调用。当前候选应将本片单独重绑上述 main 后推送，完成该 finding 的解决记录；提交 SHA 以本段所属提交恢复，不把旧 #232 head 59b62753 的 CI 借给新 head。下一执行片：CL-1C-2 的持久货币费用/请求身份合同与可注入边界，保持生产路由不变；后台 CI 不阻塞下一片开发。

**2026-10-19 CL-1C-1：不等待 CI 的独立调用准入片（覆盖本分支旧 NEXT）。** 用户明确“不等 CI，接着做后续小分支拆分或功能分支开发”，并要求写入 Codex 记忆；已新增记忆更新 note，未改动既有 MEMORY.md。#230 保持冻结 head `f706db8ce072027d72764f387329599711647d52` / run `39143921500` 后台执行；CI 四精确路径路由已独立开为 draft [#231](https://github.com/2002yy/study-agent/pull/231)，head `4ba7b6ad`，本地 102 PASS。当前新 branch `codex/conversation-decision-admission-20261019`，worktree `D:/study-agent-validation/conversation-decision-admission-20261019`，base f706，不依赖 #231 或其他工作树 WIP。

本片新增 `conversation_decision_admission.py`：独立自有 SQLite 文件、固定额度合同、BEGIN IMMEDIATE 原子预留、request 幂等、跨实例/进程重启保留预留、并发限额、拒绝业务数据库（负控核验原库 SHA256/行不变）；不保存提示正文/模型响应/凭据，不退款、不自动重置。runner 改为可注入准入协议，存储异常/未知返回统一 admission_unavailable，模型不执行。现有进程内 DecisionBudget 保持兼容。此为次数/字符/token 台账，不冒称货币费用，未改变业务 SQLite schema/cursor，未接 SDK/真实付费模型或切换生产路由。

验证：命名 L1 `conversation_decision_admission`（自身 + runner + decision + stage policy）**112 PASS / 28.93s**；含真实 SQLite、独立 Python 进程重启、并发/锁失败、非法准入、provider 失败后重启仍不重复请求。Ruff/format、mypy122/128 NEW0、diff-check PASS；完整候选 detect-secrets **0 finding**。候选 SHA 由本片提交恢复。无本地 L3，未等待/轮询 CI。下一动作：提交此独立候选，绑定 draft PR 的 f706 基线；#230 通过门后 expected-head 合并并将后续片重绑 main；CL-1C-2 另行定义持久货币费用与生产接线。
**2026-10-19 CI-CL：敏捷开发的精确影响集路由（独立后续片，本地候选）。** #230 修复 head `f706db8ce072027d72764f387329599711647d52` 已推送，pull_request CI `39143921500` 已绑定该 SHA，快照仍 in_progress；本片不修改该 PR head。新 branch `codex/conversation-decision-ci-scope-20261019`，worktree `D:/study-agent-validation/conversation-decision-ci-scope-20261019`，base f706；仅 `tools/ci_scope.py` 与 `tests/test_ci_scope.py` 新增对两个 conversation_decision 模块及各自测试四个精确路径的分类，映射既有 `conversation_decision_1b`。其他同前缀新路径、混入 CI 工具/共享模型/SQLite/Standard/前端/资格门/未知路径时仍回退，未把整个 application 或 learning-backend 粗略缩小。manifest/docs 随片注册仍沿用既有规则，资格门要求不被删除。聚焦影响集（ci_scope/workflow_routing/ci_outcomes/stage_gates_policy）**102 PASS / 24.49s**，Ruff/diff-check PASS；本片不跑 L3、不修改 workflow 或执行器。增量本地审阅无新增阻断 finding。下一动作：等 #230 按 expected-head 合并，再将本片移植到新 main，以独立范围开 PR/绑定 CI，不把尚未合并的功能算成本片新改动。

**2026-10-19 敏捷交付裁定 / #230 审阅修复（覆盖旧“再跑最终 L3”要求）。** 用户明确要求“不要每一次都全量，一边把功能分支合入 main，一边敏捷开发”。本分支后续 bounded slice / 小范围审阅修复默认 L0+命名 L1，子阶段 L2；不因每次提交或准备合并机械重跑本地 L3，真正生产权威切换/共享持久合同等强制触发仍按 AGENTS.md。原本地 L3 已停止且未重新启动；未声称本地全量通过。#230 的 head `8fd5c227bc8785213c1efa49667417a89f9bb919` 已获 pull_request CI **39141623936 SUCCESS**（pytest/secrets/mypy/required outcomes 均 PASS），但审阅 finding `4307618012` 指出 transport 自行 CancelledError 会冒充调用者取消。现已区分 `asyncio.current_task().cancelling()`：调用者取消仍传播，适配器自取消返回受控 provider_error/unknown，预留不退且不自动重试；新增负控证明当前调用者未被取消与重复请求不重发。新候选命名 L1 **116 PASS**，mypy122/128 NEW0、Ruff/format/diff-check PASS；只复验影响集，未跑全量。新 head 由本段所属提交恢复，旧 CI 不授予新 head。唯一下一动作：绑定新 exact-head CI，解决该已修 finding 后 expected-head 合并 #230；整条产品线仍按成熟度报告 NO-GO。随后独立补对话决策四个精确路径的 CI 命名影响集映射，避免既有 classifier 未注册而自动回退全量；不把全 learning-backend 笼统缩成小集。

**2026-10-18 CL-1B 最终审阅修复 / PR #230（覆盖下方候选证据）。** 完整候选审阅发现：当前上下文读取或事件循环排队耗尽时限后仍可能进入 transport。现于准入前与 transport 启动前检查同一截止时间，传给 transport 的 timeout 缩为剩余时限；两项负控证明截止已过不提交模型。命名 L1 最终 **115 PASS / 29.66s**；Ruff/format/mypy122/128 NEW0 PASS；按 CI 同配置的完整候选 detect-secrets 扫描 **0 finding**（只认既有精确证据身份白名单，未放宽规则）。此前 `0d14e34d8c23ab47777cf593ee4b272ab20467fe` 的本地 L3 在约 3% 主动停止，不借给修复后候选；保留旧部分日志，不称通过。PR [#230](https://github.com/2002yy/study-agent/pull/230) 的旧 head CI `39140892253`（pull_request）同样不得用于新候选。新的 head 以本段所属 Git 提交恢复，提交后需重新 preflight 与一次最终 L3，并绑定新 exact-head CI。完整增量审阅覆盖两个新模块、测试、manifest 与 docs；上述截止问题已修，未见其他阻断 finding（本次为本地自审，不冒称外部批准）。产品线 98 文件仍 NO-GO；当前合并范围仅 8 文件。

**2026-10-18 CL-1B：受控模型决策调用，独立 main 合并候选（覆盖本分支旧 NEXT）。** 用户授权“本分支内实现受控模型决策调用，成功实现即合并 main”，并要求评估整条产品线能否一起合入。已评估冻结产品 head `0c818515` 的 98 文件：真实验收 A 仍 FAIL、最终 head 无 PR/CI，旧 L3 不覆盖后续生产变更，故整线 NO-GO，详见 [PRODUCT_LINE_MATURITY_20261018.md](PRODUCT_LINE_MATURITY_20261018.md)。保留原线于 `codex/conversation-agent-loop-product-base-20261018`；当前 branch `codex/conversation-agent-loop-20261018` 已将自身提交移植到 exact main base `335fc9b7875b848f202122362f2e0f8b5a9db0ee`，不带入产品线 schema/UI/工具/费用代码，也不依赖其他窗口 WIP。候选 head 以本段所在 Git 提交恢复。

新增 `conversation_decision_runner.py`：单次异步可注入模型调用、调用/提示字符/输出 token 原子准入、request 去重、有限等待、取消保留预留、迟到结果丢弃、严格响应解析与最新上下文校验、异常脱敏。上下文容器限制为不可变快照。仅返回动作提议；不执行工具、不切换生产聊天路由、不新增 SDK 或真实付费调用。进程内 budget 不冒充持久人民币费用台账；真实提供商接线与持久费用/重启幂等另属 CL-1C。用户授权的合并范围为本独立候选，非整个产品线。

本地 L1 `conversation_decision_1b` **113 PASS / 30.44s**（含真实 loopback HTTP 传输，以及超时吞取消、迟到、外部取消、并发限额、重复请求、无效 JSON/重复键、过期上下文、上下文读取失败）。全仓 Ruff、新文件 format-check PASS；mypy **122/128 NEW0**。验证日志 `D:/study-agent-validation/conversation-agent-loop-1b-mypy.log`。初始 Git fetch 的 schannel 连接异常，改为命令级 openssl 后成功，未更改 Git 全局配置。合并前需干净候选 preflight、完整回归、最终增量审阅与 exact-head CI；尚未宣称合并。下一动作：提交本候选，检查完整 diff 范围，跑所需最终门并 expected-head 合并。CL-1C 在合并完成后另开片。

**2026-10-18 CL-1A：对话行动合同独立推进（覆盖下方 CL-0/IA-1A 依赖与旧 NEXT）。** 用户要求“新工作树不要直接依赖其余开发中的工作树的结果，另选方向推进”；本分支只依赖固定已提交产品 base `0c8185151f694926941d3e5801f65f1df72fc65c` 与自身提交，不导入其他窗口 WIP、不等待其输出。branch `codex/conversation-agent-loop-20261018`，worktree `D:/study-agent-validation/conversation-agent-loop-20261018`，本片 base `494f13f10d12c3a1230834de2d85b7907ec4913d`；候选 head 由本段所属 Git 提交恢复。调整后的任务合同见 [CONVERSATION_AGENT_LOOP_PLAN.md](CONVERSATION_AGENT_LOOP_PLAN.md)。新增 `src/application/conversation_decision.py`：有界上下文/模型输入、六类行动提议、精确 envelope 校验、请求与研究版本绑定、工具能力及剩余调用预算检查。新话题可回答或用工具且保留原研究；不支持转向、非法排队、跨 run/陈旧版本、未知工具和额外执行字段被明确拒绝。仅合同/校验器，无 I/O，无生产路由切换、模型/工具执行、预算预留、状态落盘或答案权威；不是实际意图识别质量或完整对话循环验收。

**CL-1A 验证：** 命名 L1 `conversation_decision_1a`（自身 + router + task_contract + research_interaction + stage_gates_policy）**99 PASS / 29.80s**；全仓 Ruff PASS、新文件 format-check PASS、mypy baseline **122/128 NEW0**、diff-check PASS。首轮 97 PASS/2 FAIL：无 active run 的两项负控仍携带 `keep`，先触发 disposition 拒绝而非预期的 run 拒绝；仅修测试输入为 `none` 后影响集通过，无旧测试未知失败。mypy 日志 `D:/study-agent-validation/conversation-agent-loop-20261018-mypy.log`，生成缓存移至工作树外保留；本片按显式路径提交后应干净。无 L3：新增隔离合同尚未成为共享生产权威；无 UI 改动，未启动浏览器/构建。无付费调用、推送、PR、新 CI、合并或部署。**唯一下一片 CL-1B：** 在本分支接可注入、受预算/超时控制的模型决策调用，验证响应 → 提议校验与失败语义；生产接线另设门，不等待其他分支的计时或增量回复成果。

**2026-10-18 对话 Agent 循环：独立工作树与开发计划（本分支覆盖下方旧 NEXT）。** 用户确认六项通用核心能力的产品分支状态，并要求按“端到端基线 → 模型决策 → 阶段性答案 → 补充闭环 → 消息归属 → 真实联动验收”推进。任务合同见 [CONVERSATION_AGENT_LOOP_PLAN.md](CONVERSATION_AGENT_LOOP_PLAN.md)，能力表明确标注“产品开发分支、尚未合并主线”，不将已有实现等同真实验收。新 branch `codex/conversation-agent-loop-20261018`，worktree `D:/study-agent-validation/conversation-agent-loop-20261018`，产品 base `0c8185151f694926941d3e5801f65f1df72fc65c`（`codex/research-interim-analysis-20261018`），共同 main base `335fc9b7875b848f202122362f2e0f8b5a9db0ee`；当前文档提交 SHA 由本段所属 Git 提交恢复。仅新增计划与本段交接，生产代码不变。原 `chat-steer-attachments` 工作树存在未提交 IA-1A 回复/终态冻结/计时等成果，原样保留且未复制，本分支不冒称包含它们。**唯一下一片 CL-0：** 定向核对并复用 IA-1A，使用 Photoshop/开源替代品 + Agent 自动编辑补充的可控 30 秒场景建立端到端时间线，区分生成、传输、渲染和终态问题。3～5 秒为有用初步分析目标，不以回执或模板代替。当前仅文档范围与 diff-check 验证；未运行生产测试/L3，未新增付费调用，无新 CI/推送/PR/合并/部署。
**2026-10-19 CI 失败归因与 secrets 白名单修复（集成分支，本地提交）** #234/#238 的 exact-head CI 在门禁步失败，失败项为 `secrets` 与 `browser_e2e`（main 的两次 push 运行均 success，故属本分支内容）。归因结论：**两项都不是 IA-1A 的两个提交引入的**。

**`secrets`（detect-secrets）**：命中 `docs/evidence/real-acceptance-2026/scenarios.json` 第 6 行 `"candidate_head": "06e96286d98d76c38018ff972460f42528479723"`（Hex High Entropy String，熵 3.59 > 阈值 3.0）。该值经 `git cat-file -t` 验证为**本仓库真实存在的 commit 对象**（`chore(git): treat the acceptance evidence pack as binary fixtures`），且报告里的 `hashed_secret` 正是该值的 SHA-1。该文件在 `0c818515`（IA-1A 基线）与 `370e9026`（候选）**逐字节相同**（`git diff --quiet` 退出码 0），且由前置提交 `a80c1659` 引入 → **不是 IA-1A 新引入**。修复：在 CI 的 `--exclude-lines` 里**按字段名**补 `candidate_head`（与既有 `head_sha`/`base_sha` 同一约定），并新增负控断言任意 40-hex 字段（`head`/`target_commit`/`api_key`/`token`）与大写十六进制**仍被拦**（`tests/test_ci_detect_secrets_allowlist.py`）。

**`browser_e2e`**：`frontend/e2e/chat-role-settings.spec.ts` 的布局断言 `panelBox.y + panelBox.height <= inputBox.y` 在 desktop-chromium 上 4 条全失败。**两个 HEAD 本地重跑（同一 CI 配置 `playwright.config.ts`，`--project=desktop-chromium`）都失败同样 4 条** → 按既定判据「两边失败 ⇒ 共同祖先问题」。结合 main 的 CI 通过，可定位为**本分支 40 个前置提交中的某个**（基线 `0c818515` 已含这 40 个、不含 IA-1A 的 2 个）。该 spec 在两个 HEAD 上内容一致，`ChatPanel.tsx`(+119)/`answerUi.css`(+10) 才是 IA-1A 的差异 → 但 IA-1A 的 2 个提交**不在失败区间内**。**未修复**：需在 40 个前置提交上做二分定位（下一步）。

**诚实边界**：本地无法复现 CI 的 secrets 命中（本地扫描在两个 HEAD 上 residual 均为 0，插件直查该文件也不报），因此 secrets 的归因依据是**文件内容逐字节相同 + 值经验证为真实 commit**，不是本地复现；CI 报告（artifact `ci-diagnostics/detect-secrets-report.json`）是命中的直接证据。

**2026-10-18 IA-1A 终态诚实报告（最后一刻接受的补充必须被明确告知，本地未提交，覆盖下方所有 IA-1A 记录数字）** 复审认可前一轮三项修复，但指出一个产品一致性问题：P1 测试证明补充记录与回复没丢，却没证明**最终答案是否明确告知该要求没有执行**；“未生成模型分析”与“未纳入最终研究结果”不是一回事。本轮只做这一件事，另附一项非阻断一致性收口。**未提交、未推送、未开 PR、未触发 CI、未运行 L3、未跑付费样本、未做费用账本。**

**修复（全部发生在终态写入内部，基于合并后的上下文）**：仓储新增 `_unexecuted_supplements(context)`（判定条件与既有语义一致：`executed_in_round is None`）与常量 `UNEXECUTED_SUPPLEMENT_WARNING = "本轮研究结果未包含部分追加要求（已接受但未执行）；请排队下一轮继续。"`。`complete()` 每次 CAS 尝试都基于**合并后的**上下文判定：存在未执行补充时，状态由 `completed` 降为 `partial`（诚实状态），并把该警告写入 run 的 `warnings`（去重）；`_freeze_replies_for_terminal()` 同时给这些补充的回复打上 `result_state="not_included"`（新增 `mark_result_not_included()`，走 `advance_content` 递增版本）。服务端原先基于执行器**旧快照**的 `unapplied` 判断与重复告警已删除，判定与文案只有一处来源（仓储），避免旧快照漏报。

**前端（数据库 → 界面）**：`ChatResearchReply` 新增 `result_state?: "not_included"`；`replyStatusNote()` 优先返回更强、更可执行的说明“本轮研究结果未包含此要求（已接受，未执行）；可排队下一轮继续”（优先于“本轮未生成模型分析”）；`ChatResearchRecovery` 新增渲染 run 的 `warnings`（原样展示、不做摘要），与任何 API 消费方看到的是同一句话。

**非阻断一致性收口**：后端此前允许 `superseded` 回复继续更新正文，前端却冻结整条回复。现统一为“失效后正文不可变”：durable `superseded` 时，incoming 非 `superseded` 记 `superseded_reopen`，incoming 也是 `superseded` 但内容不同则记 `superseded_immutable`，两种情况都保留 durable，两层规则一致。

**负控（数据库 → 用户界面）**：`test_a_supplement_accepted_before_completion_survives_it` 现同时断言 `status == "partial"`、`UNEXECUTED_SUPPLEMENT_WARNING in completed.warnings`、每条回复 `result_state == "not_included"`，以及 SSE 投影同样携带该字段；`test_a_steer_accepted_before_the_terminal_write_is_frozen_by_it` 断言 `closed_run_status == "partial"` 与警告存在；前端 `researchReplies.test.ts`、`ChatPanel.test.tsx`（回复块渲染该说明）、`ChatResearchRecovery.test.tsx`（渲染持久化警告行）各一条。另为 `ChatResearchRecovery.test.tsx` 补 `afterEach(cleanup)`，修掉测试间 DOM 泄漏（新断言暴露的既有测试卫生问题）。

**验证（本轮重跑，最终候选）**：L1 `incremental_answer_1`（11 文件）**106 PASS / 39.57s**；前端 `npm test` **115 files / 553 tests PASS**；`tsc -b` 0 错、`vite build` PASS；浏览器四视口 **4 PASS / 16.2s**；Ruff PASS；mypy **current=122 / baseline=128 / resolved=6（NEW0）**；`git diff --check` PASS。

**仍未做**：真实模型样本与延迟分布、持久化费用账本、L3/CI。**已知相邻问题（仅记录）**：前端全量单测存在负载敏感 flake（`ReadingWorkspace.test.tsx` 的 scrollTop 断言），单独运行 6/6 通过，不在本候选范围。**下一刀**：本轮通过后先做独立实验 ID 的持久化预算账本，再跑三条真实样本。

**2026-10-18 IA-1A 复审三点收口（superseded 单向 / 终态补充历史 / 跨轮次计时，本地未提交，覆盖下方所有 IA-1A 记录数字）** 复审 NO-GO 后只做三项：防止 `superseded → open`、验证终态补充记录不丢失、过滤跨轮次计时事件。**未提交、未推送、未开 PR、未触发 CI、未运行 L3、未跑付费样本、未做费用账本**。

**P0 `superseded` 被旧执行器重新打开（已复现→已修）**：复审给出的最小复现（durable `superseded` v3 / 新状态 incoming `open` v3）在本工作树得到同样结果 `open` v4（走 `same_version_race` 分支重新编号放行），违反 `open → superseded` 不可逆。修法：`merge_steering_replies()` 在**任何研究状态/版本比较之前**先保护 durable 的 `superseded`——incoming 不是 `superseded` 即拒绝，并记录 `last_conflict.reason="superseded_reopen"`（可审计），生命周期权威不再被更新的研究轮次覆盖。修复后同一复现输出 `superseded` v3 + `superseded_reopen`。负控：`tests/test_reply_persistence_consistency.py::test_a_superseded_reply_is_never_reopened_by_a_stale_executor`（先持久化纠正，再让持旧快照的执行器 `checkpoint`，回读数据库与 SSE 投影都必须仍是 `superseded`）。

**P1 终态写入可能丢掉最后一刻接受的补充历史（已证实→已修）**：复审指出 `complete()` 只合并 `conversation_queue` 与 `steering_replies`，未合并 `deep["steering"]`。**已用真实数据库路径证实**：先做一次 checkpoint 并捕获执行器旧快照 → `service.steer` 接受第二个补充 → 用旧快照 `complete()`，修复前数据库中 `deep["steering"]` 只剩 1 条（补充历史被旧副本覆盖），修复后为 2 条。修法：`complete()` 与 `fail()` 都改用与 `checkpoint` 相同的合并链（`merge_active_steering_context` → `merge_deep_steering_context` → `merge_queued_followups` → `merge_steering_replies`），并保留有界 CAS 重试（`fail()` 同样加上重试）。负控三条（完成/失败/取消）：新 id 必须同时存在于 `deep["steering"]` 与 `steering_replies`，回复一律 `closed` + `run_terminal`，`closed_run_status` 分别为 `completed`/`failed`/`cancelled`，未覆盖的补充标 `not_generated`。

**P2 新计时窗口仍接收旧轮次回复事件（已修）**：`researchTiming.ts` 新增 `inWindow()`，`replies`、`reply_visible`、`answer_visible` 三类事件统一按 `target_turn_id` 过滤；`target_turn_id === null`（本会话尚未 send，例如恢复的会话）不过滤，且此口径已写入注释。负控：新 send 后旧 run 的 `replies`/`reply_visible` 迟到事件被拒（`marks`/`visible` 保持为空），当前 run 事件正常进入；恢复会话（target 为 null）三类事件仍被观测。

**审查包说明修正**：上一版 `ia1a-FIXES-b1b5.md` 的“先应用全量补丁再应用窄补丁”是错的（全量补丁已包含窄补丁内容）。正确用法：**从 base `0c818515` 起只应用全量补丁**；或**从 B1–B7 修复前的候选起只应用对应窄补丁**。本版说明已按此改正。

**验证（本轮重跑，最终候选）**：L1 `incremental_answer_1`（11 文件）**106 PASS / 41.92s**；前端 `npm test` **115 files / 550 tests PASS**；`tsc -b` 0 错、`vite build` PASS；浏览器四视口 **4 PASS / 11.0s**；Ruff PASS；mypy **current=122 / baseline=128 / resolved=6（NEW0）**；`git diff --check` PASS。窄范围差异见 `D:/study-agent-validation/ia1a-fixes-superseded-terminal-timing.patch`。

**已知相邻问题（未修，超出本轮范围）**：前端全量单测存在**负载敏感 flake**——`src/features/reading/ReadingWorkspace.test.tsx > notebook reading navigation > locates only headings in the loaded window without another read` 在整套并行运行时偶发失败（`body.scrollTop` 期望 77 实得 0），单独运行该文件 6/6 通过；该文件不在本候选改动范围内，按范围纪律仅记录不修。

**仍未做**：真实模型样本与延迟分布、持久化费用账本、L3/CI。**下一刀**：本轮三点通过后，先做独立实验 ID 的持久化预算账本（原子累计、重启不清零、并发不超额），再跑三条真实样本。

**2026-10-18 IA-1A 审查阻断修复（B1–B5，本地未提交，覆盖下方所有 IA-1A 记录的数字）** 审查裁定 NO-GO 后按 B1–B5 收口。branch `codex/research-interim-analysis-20261018`，worktree `D:/study-agent-validation/chat-steer-attachments`，base/HEAD `0c8185151f694926941d3e5801f65f1df72fc65c`（**仍无新 commit**）；**未推送、未开 PR、未触发 CI、未运行 L3、未跑付费样本**。

**B1（P0）失效标记被合并器丢弃**：`mark_additions_stale`/`supersede_affected` 只增 `content_version` 而不更新 `based_on_version`，研究状态不变时合并器判 `stale_base` 并拒绝，导致“旧判断已过时”的更新落不了盘。新增 `advance_content(reply, now=...)`：任何**状态变更**都同时写入 `content_version+1` 与 `based_on_version=原版本`，使合法失效写入通过 CAS 校验，而陈旧写入方仍会被拒（`based_on < durable.content_version`）。`mark_analysis_not_covered`/`close_replies` 同样走该路径。**仓储级负控**（`tests/test_reply_persistence_consistency.py`，新）：走真实 `checkpoint` 合并链与 `_deep_update_steering_replies`，回读数据库断言 `stale is True` / `lifecycle == superseded` 且无 `last_conflict`，并断言 SSE 投影同样可见。

**B2（P0）终态冻结不在同一次原子转移内**：原先执行器先 `_close_steering_replies(...)` + `persist()`，再 `complete()`/`fail()`，存在“回复已宣称结束、run 行仍是 running”的窗口。现冻结移入终态写入本身：仓储新增 `_freeze_replies_for_terminal(context, run_id=..., run_status=...)`，在 `complete()`/`fail()`/`finish_cancel()` 的**同一次 UPDATE** 内完成（含“本轮未生成模型分析”的标记），`run_status` 取**实际写入的终态**（`completed`/`partial`/`failed`/`cancelled`，不再是仍为 running 的旧行）；`complete()` 改为有界重试：每次重新读行、合并 durable 的 `steering_replies`、冻结、再按版本 CAS 提交，因此终态写入既不会丢弃并发追加的回复，也不会在 CAS 失败时留下冻结。服务端 `_close_steering_replies` 与其 logger 已删除（`close_replies`/`mark_analysis_not_covered` 导入一并清理）。负控：终态前 checkpoint 后回复仍为 `open`、完成后才 `closed`+`run_terminal`+`closed_run_status=completed`；CAS 持续失败时不落冻结且 run 仍 `running`；失败路径 `closed_run_status=failed`。

**B3（P1）对 durable `closed` 无条件信任**：`prior_closed` 现要求 `lifecycle_closed_by == "run_terminal"`；无来源的 `closed` 可被合法更新覆盖，权威冻结仍然优先。负控：非法 `executor` 关闭被合法更新取代、权威关闭仍胜出（`test_reply_terminal_freeze.py::test_an_illegitimate_durable_close_is_not_kept`）。

**B4（P1）可见计时被上一轮污染**：`ResearchTimingState` 增加 `target_turn_id`；新增 `run_start` 事件（每次 send 开新观测窗并清空旧标记）；`answer_visible` 只在 turnId 与目标轮次一致时生效；`ChatPanel` 的 `AnswerVisibilityProbe` 仅对**当前观测轮次**的已完成答案挂载（新增 `answerTurnId` 由 controller 透传）。负控：旧轮次答案上报被拒、`run_start` 清空历史标记、非目标轮次不挂探针。

**B5（P1）G1 后到会擦除 G2 证据来源**：`apply_analysis` 在已有 G2 时不再改写 `content_state`（证据 provenance），改为把 G1 的 `{round,notes,revision}` 存入独立的 `analysis_provenance`；`content_fingerprint` 纳入该字段。负控：G2 的 `content_state`/`citations`/`text` 在 G1 后到后保持不变。

**B6（P2）投影与前端对无来源关闭不一致**：`reply_projection(active=False)` 现显式写入 `lifecycle_closed_by="run_terminal"`（来源是权威 run 行）；前端 `mergeResearchReplies` 统一规则——首次恢复遇到无来源 `closed` 显示为 `open`（内容不丢、不误标冻结），合并路径仍完全忽略裸关闭声明。负控双向覆盖。

**B7（P2）“可见”语义**：发布态新增 `visibility_source: "rendered_after_frame"`，明确该指标是“提交后第一帧”的渲染观测，**不等于**读者在滚动区域内真正读到；浏览器断言同步校验该字段。

**验证（本轮重跑，最终候选）**：L1 `incremental_answer_1`（现 11 文件，已登记新负控）**102 PASS / 35.44s**；前端 `npm test` **115 files / 548 tests PASS**；`tsc -b` 0 错、`vite build` PASS；浏览器四视口 **4 PASS / 10.9s**；Ruff PASS；mypy **current=122 / baseline=128 / resolved=6（NEW0）**；`git diff --check` PASS。窄范围修复差异 `D:/study-agent-validation/ia1a-fixes-b1b5.patch`（16 文件，+643/−129），已在冻结候选的干净工作树上 `git apply --check` 通过。

**仍未做**：真实模型样本与延迟分布（未批准）、持久化费用账本（审查通过后再做）、L3/CI。**下一刀**：审查通过后做独立实验 ID 的持久化预算账本（原子累计、重启不清零、并发不超额），再跑三条真实样本。

**2026-10-18 IA-1A 审阅后修复轮（本地未提交，覆盖下方两条 IA-1A 记录的验证数字）** branch `codex/research-interim-analysis-20261018`，worktree `D:/study-agent-validation/chat-steer-attachments`，base `0c818515`；本轮**未提交、未推送、未开 PR、未触发 CI、未运行 L3、未新增付费模型调用**，改动全部留在工作区待审阅。审阅给出的 6 项必须修复已全部落地。

**① 显示计时改为“按内容态”上报（原缺陷：回执渲染被当成模型分析）**：`frontend/src/features/web-lookup/researchTiming.ts` 重写为 `visible: ReplyVisibleMark[]`，键为 `reply_id@content_version:stage`（`visibleKey`/`visibleStageAt`/`firstVisibleAt`），首次观测为准、重放事件不得前移或后移；`leadBeforeAnswer`（对 `answer_done_ms`）与 `analysisLeadBeforeAnswer`（G1，仅 `stage="analysis"`）/`evidenceLeadBeforeAnswer`（G2）分离，**没有 G1 就是 `null`，绝不用 G2 顶替**。`chatController.ts` 的 `onReplyRendered` 删除，改为 `onReplyVisible(reply, at)` + `onAnswerVisible(turnId)`；**答案可见时间不再由 `done` 事件后下一帧推断**，改由真正渲染答案的组件上报。`ChatPanel.tsx` 抽出 `ResearchReplyBlock`（挂载即按当前内容态上报）与 `AnswerVisibilityProbe`（仅在“已完成且有正文”的助手气泡内挂载）。

**② 研究级回复按精确轮次绑定（原缺陷：绑到“最后一条助手消息”）**：删除 `lastAssistantIndex`，改为 `message.turnId === reply.turn_id` 定位归属；无归属（该轮尚无消息）时进入尾部兜底区块，不冒充其他轮次。`frontend/src/features/web-lookup/researchReplies.ts` 客户端合并修正：**接受后端驱动的 `open → superseded`**（版本 `>=` 即生效，这是失效而非“更新内容”）、权威冻结（`lifecycle_closed_by === "run_terminal"`）在同版本也生效、**无 provenance 的 `closed` 声明继续被忽略**、已冻结不被重开。

**③ 终态权威写入（后端）**：`src/application/web_lookup_service.py` 的 `_close_steering_replies` 改为**显式传入即将写入的终态**（`run_status="partial"|"completed"`、失败路径 `"failed"`）；此前它读 `self.get(run_id).status`，而该行此刻仍是 `running`，导致 `closed_run_status` 记录错误——属真实 provenance 缺陷，已修。冻结失败不再静默 `return`，改为 `_LOGGER.warning(..., exc_info=True)`（新增模块级 `_LOGGER`）。

**验证（本轮全部重跑，最终候选）**：L1 `incremental_answer_1`（10 文件）**94 PASS / 35.03s**；`tests/test_reply_terminal_freeze.py` **7 PASS**（新增不变量：取消/失败/完成三条终态路径都写入 `lifecycle_closed_by="run_terminal"` 且 `closed_run_status` 分别等于 `cancelled`/`failed`/`completed`；无 provenance 或 `lifecycle_closed_by="executor"` 的 `closed` 声明完全无效；`close_replies` 会升版本且不重复盖章）；前端 `npm test`（= `vitest run src`）**115 files / 544 tests PASS**；`tsc -b` 0 错误、`vite build` PASS；浏览器 `playwright.conversation.config.ts` 桌面/手机/窄屏/平板 **4 PASS / 12.0s**（断言已改为新模型：回执与 G1 是不同内容态、`receipt < analysis < answer_visible`、G1/G2 lead 分别 > 0）；Ruff PASS；mypy 基线 **current=122 / baseline=128 / resolved=6（NEW0）**；`git diff --check` PASS。

**本轮失败样本与根因（均为测试侧或已修）**：⑴ e2e 断言仍读旧形状 `mark.analysis_ms`，属测试未随生产 API 更新，已改为新模型断言；⑵ 出现 React “unique key” 警告——`key` 原先在 `replyBlock` 内部的 `<article>` 上，抽成组件后需落在组件调用处，已修；⑶ 我新加的绑定测试断言 `closest("article")` 命中的是回复块自身的 `<article>`（假失败），改为以 `.message` 为轮次容器，产品行为本身正确。**注意**：裸 `npx vitest run` 会把 `e2e/*.spec.ts` 当作 24 个失败套件，正确命令是 `npm test`（`vitest run src`），此前记录的前端数字差异源于此。

**边界与风险（不因本轮修复而改变）**：G1 仍来自既有 `revise` 调用（本轮结束才产出），**不承诺 3–5 秒内出现模型分析**，也不得把“回执很快出现”宣传为“已实现快速智能分析”；G2 只证明“引用来自已读材料”，不等于论证成立；`AnswerVisibilityProbe` 仍是“下一帧”近似，不是 paint 保证。费用裁定未执行：`src/llm_spend_guard.py` 的 `_reserved_cny` 是**模块级全局**，进程重启即清零，因此“三个样本共 ¥10 硬上限”必须在同一进程内完成（或先把账本持久化），实际样本运行仍待批准。**下一刀**：按批准方案在同进程内跑三条可追踪样本，采集四项延迟与“G1/G2 是否早于 G4”，样本不足只报原始值。

**2026-10-18 IA-1A 验收：三项风险修复 + 浏览器单时钟计时（本地未提交，覆盖下方 IA-1A 段）。** 用户裁定「保留未提交、批准设计测量方案、允许有限本地修复」，本轮**未提交、未推送、未触发 CI、未运行 L3、未新增付费模型调用**。三项风险检查结果：①**同版本冲突语义已修正**——原先“冲突后把写入方内容改到下一版本”会让陈旧执行器仅凭版本号覆盖更新内容；现改为**以研究状态为准**（`content_state = {round, notes, revision}`，即该内容由哪一轮、多少条笔记、哪个 interim revision 派生），旧状态永远不得覆盖，同状态同版本冲突保留**首次成功原子写**，只有更新的研究状态才以不冲突版本发布（`steering_replies.merge_steering_replies` + `state_key`）。②**终态冻结落盘**——`finish_cancel`（取消）与深研失败路径现在在同一原子写内 `close_replies`；成功/部分完成路径在最终 persist 前关闭；`checkpoint` 只接受 `status='running'`，取消/失败/完成后旧执行器根本无法写入；`pending`（已接受未启动）仍为活跃态、**不会**被误判终态（负控已覆盖）。③**G1/G2 是否早于 G4 已可测量**——新增浏览器单时钟标记（`researchTiming.ts`：submit/receipt/analysis/evidence/answer 全部取 `performance.now()`，首次观测为准），并给出 `leadBeforeAnswer`/`analysisLeadBeforeAnswer`，迟到即为 null、不伪造“边研究边回答”。

验证（本轮重跑）：L1 `incremental_answer_1` **82 PASS / 32.49s**（新增 `tests/test_reply_terminal_freeze.py` 5 PASS：pending 非终态、取消落盘冻结且拒绝迟到 checkpoint、失败冻结、完成冻结、迟到 open 快照不得重开）；`test_steering_replies.py` + `test_steering_reply_merge.py` **19 PASS**（含“陈旧写入方不得靠高版本提升旧分析”“同状态同版本保留首次写”“更新状态以不冲突版本发布”）；前端 **170 PASS / 23 files**（含 `researchTiming.test.ts` 4 PASS：单时钟记录、重复事件不移动更早观测、迟到即 null）；浏览器四视口 **4 PASS / 13.6s**，新增断言用 `window.__studyAgentTimings` 证明「回执 < 模型分析 < 最终答案」的顺序（fixture 时间线，非真实模型证据）；Ruff PASS、mypy 基线门 **122/128 resolved=6（NEW0）**、`git diff --check` PASS、`tsc -b && vite build` PASS。

**交付物**：审阅用补丁 `D:/study-agent-validation/ia1a-20261018.patch`（24 文件，2269 insertions / 15 deletions，含 9 个新增文件；`git apply --stat` 校验通过）。**未做**：真实模型样本与延迟分布（需另行批准费用）、IA-1B 快速分析调用、active claim-engine 接入。**下一刀**：按已批准方案跑三个领域各一条可追踪样本（Photoshop 自动化编辑、游戏攻略补充、编程问题补充），采集四项延迟与“G1/G2 是否早于 G4”，样本不足只报原始值。

**2026-10-18 IA-1A：阶段性助手回复（本地未提交，覆盖下方旧 NEXT）。** branch `codex/research-interim-analysis-20261018`，worktree `D:/study-agent-validation/chat-steer-attachments`，base `0c818515`。用户裁定 Rev.2「有条件 GO，批准 IA-1A 最小实现」，并给出四项强制实现合同 A–D；本轮**未提交、未推送、未开 PR、未启动 L3、未新增付费模型调用**。改动 6 个新文件 + 14 个修改文件：`src/web/research/steering_replies.py`（新）、`tests/test_steering_replies.py`（新）、`tests/test_steering_reply_merge.py`（新）、`tests/test_incremental_answer.py`（新）、`frontend/src/features/web-lookup/researchReplies.ts`（新）、`researchReplies.test.ts`（新）；改 `deep_planner.py`、`interim_analysis.py`、`web_lookup_service.py`、`web_lookup_repository.py`、`chat_routes.py`、`types.ts`、`chatController.ts`、`ChatPanel.tsx`、`ChatPanel.test.tsx`、`WorkspaceView.tsx`、`answerUi.css`、`conversation-continuous.spec.ts`、`test_deep_planner_production.py`、`stage_gates.json`。

**实现（对应合同 A–D）**：A 失效规则——`interim_revision` 变化不再等于整条回复失效：新增条件只把旧判断标 `stale`（“尚未覆盖后续新增的条件”）且保持 `open`，只有 `corrections` 里被替换的旧术语命中、或引用材料失效才 `superseded`；研究终态由权威 run 状态决定 `closed`（投影派生 + 落盘冻结双保险）。B 并发一致性——回复存 `context["steering_replies"]`，`checkpoint` 合并链新增 `merge_steering_replies`（同 `reply_id`：版本大者胜；**同版本不同内容判为冲突**，durable 保版本、写入方改到下一版本，绝不用 `updated_at` 静默决胜；终态冻结优先于版本）；`append_steering` 与回执回复在**同一次原子写**内完成，CAS 耗尽改为明确可重试的并发冲突错误，不再冒充“研究已停止”。C G1 模型合同——`revise` 新增结构化 `steering_understandings`（`steering_id/changed_focus/reason_to_check/questions_to_verify`），服务端校验字段、长度、真实补充 ID 并拒绝“已验证/已确认/verified”等断言口吻；上下文改为优先喂入**尚未被理解**的补充（上限 4），未被覆盖的补充在终态显式标 `not_generated`（“本轮未生成模型分析”），不静默丢弃。D G2 来源归属——`attribute_analysis` 要求**每一条**引用都来自该补充创建的任务、且读取轮次 ≥ 该补充进入计划的轮次；不满足则归入研究级回复（`<run_id>:research`，`scope=research`）。前端：补充级回复绑定到对应补充消息，研究级回复绑定 run（原助手气泡只留简洁状态）；引用沿用 `safeLinkUrl` 校验，`content_version` 严格递增、终态冻结。

**验证**：命名 L1 `incremental_answer_1`（写入 `tests/stage_gates.json`）**75 PASS / 27.61s**；并发与不丢写负控 `test_steering_reply_merge.py` **5 PASS**（同一次写内落盘回执、陈旧执行器 checkpoint 不得擦除新回复、同 `request_id` 幂等、非运行态与冲突区分、同版本冲突改号）；投影与失效 `test_steering_replies.py` **12 PASS**；端到端 `test_incremental_answer.py` **2 PASS**（4 条补充全部有回复且无静默丢弃、补充前材料只能进研究级回复、补充后材料才可归属、回复文本不进入 `source_block`）；前端 **166 PASS / 22 files**（含回复渲染、`javascript:` 来源不成链接、同版本终态冻结、晚到事件不覆盖新内容）；浏览器 `playwright.conversation.config.ts` 桌面/手机/窄屏/平板 **4 PASS / 10.5s**，截图 `frontend/test-results/conversation-continuous/*/continuous-research.png`（补充消息下出现“初步分析/已收到补充”）与 `interim-analysis.png`（研究级“阶段性判断 · 有来源，尚非结论”＋引用）；Ruff PASS、`git diff --check` PASS、mypy 基线门 **current=122 / baseline=128 / resolved=6（NEW0）**，日志 `D:/study-agent-validation/ia1a-mypy.log`；`tsc -b && vite build` PASS。

**边界与风险**：G1 仍来自既有 `revise`（本轮结束才产出），**不承诺 3–5 秒内出现模型分析**，也**不得**把“首条回执很快出现”宣传为“已实现快速智能分析”；本轮**未做延迟测量**（首条可见回执/首次模型分析/首次有来源分析/最终答案的中位数与 P95 仍待补，样本不足须注明）。G2 仍只证明“引用来自已读材料”，不等于论证成立。active claim-engine 未接入（`steering_replies` 仅在 Deep 路径产生，字段形状两条路径一致，便于后续接入）；取消路径依赖投影派生 `closed`，未落盘冻结。**下一刀 IA-1B**：先补真实延迟测量（含 Photoshop 自动化编辑、游戏攻略补充、编程问题补充三类样本），再据结果决定是否引入可取消、有预算、与研究并行的受控快速分析调用；普通新问题的直接回答/边答边查/深入研究分流仍属后续阶段。

**2026-10-18 最新片：补充要求显示“它实际改了什么”（本地 commit，未合并/未推送；覆盖下方旧 NEXT）。** branch `codex/research-interim-analysis-20261018`，worktree `D:/study-agent-validation/chat-steer-attachments`，base `4b8fd6ad`，本片代码提交 **`873315d4`** `feat(research): expose durable steering effects in chat progress`（11 个文件：`src/web/research/research_interaction.py`、`tests/test_research_interaction.py`、`tests/stage_gates.json`、`frontend/src/types.ts`、`frontend/src/features/single-chat/ChatPanel.tsx`、`frontend/src/features/single-chat/ChatPanel.test.tsx`、`frontend/src/features/chat/chatController.ts`、`frontend/src/features/answer-ui/answerUiProtocol.ts`、`frontend/src/features/answer-ui/answerUi.css`、`frontend/e2e/conversation-continuous.spec.ts`，另含本状态文档）。用户反馈：截图里“再考虑 Agent 自动编辑”下面只有一行回执、其余留白，看不出第二句话是否被当成决策依据。本片把补充回执从“状态标签”扩成“状态 + 实际效果”，**纯展示投影，无新模型/工具调用，不写计划、不授予证据或答案权威，不改 schema/预算/Gate**。

实现（含审阅后的事实边界修正）：`src/web/research/research_interaction.py` 新增 `_steering_effects()`——只从 durable 事实投影。`questions` 为 plan 任务中 `steering_ids` 命中该补充 id 的项（≤2、去重、各 ≤160 字），且**只有创建者（`steering_ids[0] == entry_id`）才标记 `created=true`**；仅被追加 id 的既有核查恒为 `created=false`，绝不冒充“新增”。`created=true` 时显示文本用 `_steering_question_text()` 去掉 planner 的“；新增研究目标：”拼接前缀，只显示该补充真正加的目标（不再复述原问题）；`created=false` 时原样显示完整核查问题。`sources` 为已读摘录中 `question` 与这些核查完全相等者（≤2，仅 title/url），只表示关联材料，不表示支持。未进计划的补充**不产生 effects 字段**（空投影即诚实答案）；`superseded/cancelled` 任务与旧术语修正过的问题不计入；沿用既有 `deep_steering_status()`，`executing` 仍只在 run 活跃时出现。前端：`types.ts` 两处类型补 `effects`；`answerUiProtocol.ts` 新增 `safeLinkUrl()`（仅 http/https、无凭据、无控制字符，否则回落纯文本，不生成可点击链接）；`ChatPanel.tsx` 按 `created` 渲染“新增核查：/本次补充涉及的核查：”，来源行为“关联已读材料（尚非结论）：”；`answerUi.css` 用 `.message-body .research-steering-*`（提高特异性，覆盖既有 `.message-body span{display:inline-flex}`）保证三行竖排、非加粗；`chatController.ts` 三处（乐观追加 / SSE 合并 / 恢复）透传 `effects`。

验证：命名 L1 `research_steering_effects`（写入 `tests/stage_gates.json`）**94 PASS / 1 SKIP / 39.18s**；`test_research_interaction.py` 自身 **17 PASS**（含：未进计划无 effects、`created` 只认创建者、correction 追加到既有任务不称新增、去重与 160 字/2 条上限、effects 只含 text/created 与 title/url 无权威字段）；前端 `ChatPanel.test.tsx` + answer-ui 组 **61 PASS / 26 in ChatPanel**（含既有核查不得称新增、`javascript:` 来源不生成链接）；`tsc -b && vite build` PASS；浏览器 `playwright.conversation.config.ts` 桌面/手机/窄屏/平板 **4 PASS / 10.4s**（截图 `frontend/test-results/conversation-continuous/*/continuous-research.png`：三行竖排、只显示补充自己的目标）；Ruff PASS、`git diff --check` PASS、mypy 基线门 **current=122 / baseline=128 / resolved=6（NEW0）**，日志 `D:/study-agent-validation/steering-effects-mypy.log`。零 L3、无新 CI、未推送/未创建 PR/未合并。

**边界**：effects 是“服务端从计划与已读材料投影出的展示事实”，不等于论证成立或推荐正确；引用存在性检查仍不是 entailment 判定。当前只覆盖 Deep（active claim-engine 补充仍只有状态，不虚构 effects）。**下一刀（用户已调整优先级，不再是补 active 展示）**：补充要求 → 助手自己的**增量回复** → 后台研究继续 → 新发现逐步更新。要分清两层：进度信息（本 commit 的成果）与分析内容（为什么这项补充改变了原问题、目前能判断什么、还需验证什么）。补充消息继续作为用户消息存在，但助手需要一条**独立且可持续更新**的回复，而不是把研究状态都挂在原助手气泡下。3～5 秒可作为初步交互目标，但不得为赶时间生成无依据结论。真实付费验收仍按既有预算授权边界。

**2026-10-18 最新片：有出处的阶段性判断 + UI 留白（本地，未合并；覆盖下方旧 NEXT）。** branch `codex/research-interim-analysis-20261018`，worktree `D:/study-agent-validation/chat-steer-attachments`，base **`15302f84b2a774c37d51c34e406f91bc0b8a5a0e`**；本段所在 Git 提交即实现 head，审阅仅 base 后增量。复用 Deep 原有 revise 调用生成可选归纳，不新增调用/预算/执行器。要求先给具体发现、差别或有条件建议，说明对用户的意义；不能形成有用判断时返回 null，不用“继续核对”凑分析。服务端限制正文400字、1–3条引用，引用必须匹配已读材料 ID 与原文；checkpoint 在最终综合前保存。展示重新核对成功读取/资格/重定向及当前 steering revision；新补充、失效正文会撤回过时判断。保持原文段落，无独立持久化 schema 改动，不改变正式答案/Gate 权威。

用户指出“毫无结论、AI味、仍然堆积”后，本片改为直接展示判断正文：有判断即收起开场计划/查询计数/重复标题，原文和过程合为一个默认折叠入口，阶段性边界说明移入其中；段间留白，无新增卡框。头像仍桌面96px、手机80px。脚本浏览器场景移除每次 steer 无条件发送的过程套话和未请求计算，计算覆盖移到明确请求数字比较的排队问题；这些是 mock 修正，不冒称生产模型已执行。

验证：命名 L1 `research_interim_analysis` **99 PASS / 1 SKIP / 35.40s**；最后补段落保留后，自身+生产 planner+已读来源模块 **34 PASS / 10.88s**，未重复全量。前端上一版影响集62 PASS，本次反馈修复最终直接影响集 **32 PASS**，TypeScript/Vite build PASS；最终320/390/768/1440px浏览器 **4 PASS / 10.5s**（同SSE连续追加/排队失败重试、附件身份、出处折叠、查询行撤下、计算按需、原头像尺寸），人工查看390px截图判断正文与来源入口留白通过。Ruff PASS、mypy **122/128 NEW0**、diff-check PASS。Ruff首次误从frontend目录运行导致tests/tools路径不存在，已改repo根目录通过，非代码失败。日志 `D:/study-agent-validation/interim-analysis-{impact,final-focused,frontend,build,browser,mypy}.log`；截图 `frontend/test-results/conversation-continuous/*/interim-analysis.png`。本片零 L3；无新 CI/推送/PR/合并/部署，提交后预期干净，主目录不改。

**边界与下一刀：** 引用存在性检查不等于论证成立/推荐正确；全部离线 fake 模型/工具与真实 SQLite/HTTP/SSE，不授予真实研究质量 GO。当前只覆盖 Deep；Standard 的增量判断仍未接通。下一执行片：用用户问题与阶段性判断组成小型内容验收集，核查“具体结论/证据适配/有用后果/无套话”，再决定是否扩展 Standard；真实付费验收沿用既有预算授权边界。

**2026-10-18 最新片：已读资料按真实研究问题分组（本地，未合并；覆盖下方旧NEXT）。** branch `codex/research-question-groups-20261018`，worktree `D:/study-agent-validation/chat-steer-attachments`，base **`e167c6657306f3986f4ca96210f14443bb6ce231`**；本段所在Git提交即修复head，审阅仅base后的增量。改善六项能力中的搜索分析/边研究边交互：从既有Deep plan/notes/成功读取正文只读投影问题归属，最多3条摘录优先覆盖不同问题，避免比较题被单侧较多来源淹没；同网页可服务不同问题、身份不冲突。按全部合格读取材料计算`reading_gaps`，不把展示上限误作缺资料；done状态不能制造已读材料，纠正/取消的旧问题不再当作来源或缺口。UI沿用无外框分组与一条低强调的“暂无正文”提示，第二侧资料到达后撤掉对应提示、保留第一侧且不重复。旧事件可省略新增字段，显式空快照清除过期项，低版本/跨run隔离保持。

验证：命名L1 `research_question_groups` **76 PASS / 1 SKIP / 30.35s**；新增展示上限负控后仅自身模块复验 **18 PASS / 4.60s**（未声称整个命名集重跑）；前端影响集 **60 PASS**；320/390/768/1440px focused浏览器 **4 PASS / 10.9s**，覆盖单侧缺资料→双侧出现/缺口消失/原资料不重复及附件补充/排队链路；build/Ruff/diff-check PASS，mypy122/128 NEW0。日志 `D:/study-agent-validation/question-groups-{backend,cap-check,frontend,browser,build,mypy}.log`，截图仍在既有conversation目录。只新增展示字段与投影，不写研究计划/证据资格/答案token，不新增模型或工具调用、不改schema/cursor/预算；未动头像与上一片布局，桌面96px/手机80px约束保持。无L3、新CI、推送/PR/合并/部署；提交后工作树干净。

**唯一下一片：有来源的阶段性归纳。** 本片仍是组织原文材料，不等于模型已生成阶段性综合答案。下一片先复用已有模型综合/复核输出，接通研究中可阅读的归纳与其出处；不以更多过程标签替代内容，不增建独立研究状态机，不提前授予正式答案/研究质量GO。学习与教学仍为六项通用能力之上的专业场景。

**2026-10-18 当前片：保持大头像比例的聊天UI收简（本地，未合并）。** 分支 `codex/chat-ui-restraint-20261018`，工作树 `D:/study-agent-validation/chat-steer-attachments`，base **`a9efb72212c40b84a86bdc4a4165d98ef3ba2140`**；提交由本段所在Git提交恢复，审阅只看该base之后。**用户明确约束：角色头像不能缩成小消息图标；桌面保持既有96px，手机保持既有80px及相对视觉比例。不得为了留白而缩小头像。** 原截图灰头像来自 `frontend/e2e/api-fixture.ts` 返回灰圆SVG，真实资源 `assets/avatars/nahida.png` 正常；测试改用真实512px图片，浏览器断言图片加载与原有外框尺寸。

本片去掉助手正文气泡框和装饰尖角，用户消息仅留轻底色；研究状态合并一行、原文/结论边界文案收短；输入区改为上方文字、下方附件/方式/操作，同一入口保留研究调整与排队（原双按钮改为原生选择控件）。空输入不展示无用的追加按钮；通常说明保留给读屏，非冗余常驻标签。修复附件选择按钮被通用20px宽度覆盖而挤没文件名的问题。320px失败重试暴露底部错误提示遮挡发送按钮，已将操作错误提示移到顶部并修正窄屏宽度，未绕过错误或取消重试检查。

验证：前端相关组件/聊天控制器 **56 PASS**，全局提示 **3 PASS**；最终focused浏览器 **4 PASS / 10.0s**（320/390/768/1440px、真实头像80/96px、附件名可见、输入区<170px、键盘Tab、附加/排队失败重试/恢复选择/原SSE不中断/手动发送）；TypeScript/Vite build、Ruff、diff-check PASS。头像尺寸首次断言误测图片内框（78/94px），已改为检查原80/96px外框，未更改头像尺寸或放宽容差。未改后端/预算/Gate，不重跑上一片后端影响集及mypy；本轮零L3，无新CI、未推送/PR/合并/部署。日志 `D:/study-agent-validation/chat-ui-restraint-{unit,notices,final-browser,build}.log`；截图在 `frontend/test-results/conversation-continuous/*/research-opening.png`。提交后工作树干净。

**唯一下一片：阶段性资料按问题维度组织。** 保持当前UI与头像约束，在现有已读摘录上区分比较题的两侧/已知与缺口，让用户先获得有用内容；模型综合的阶段性答案仍未完成，不把摘录冒称已验证答案。不扩张学习系统，不重复全量回归。

**2026-10-18 最新切片：研究未结束先显示已读资料摘录（本地，未合并）。** 分支 `codex/research-early-findings-20261018`，worktree `D:/study-agent-validation/chat-steer-attachments`，base `facb8f37062029df95276a52f29d2abf5e28281a`；提交由本段所在Git提交恢复。只读投影当前Deep笔记与成功读取正文：候选摘要、失败/不可用正文、私网/非法URL、无正文依据的笔记与已失效笔记均不展示。最多3条/每条280字、稳定身份、原文出处；SSE `findings` 快照在转向时清除失效项，低版本拒绝/跨run隔离，旧事件省略字段兼容。聊天中直接可读，标注仍在核对；不进入答案token/复制文本/证据权威，不新增模型或工具请求。Deep已读数量改用既有read_summary，Active计数优先不变。**这是阶段性来源摘录，不是完成了模型阶段性综合答案。**

本片L1 `research_early_findings` **164 PASS / 1 SKIP / 152.83s**，前端影响集 **59 PASS**，桌面/移动浏览器 **2 PASS / 6.1s**（最终答案前可见出处和正文、原研究可继续插话），build/Ruff/diff-check PASS，mypy122/128 NEW0。真实SQLite checkpoint观察到运行中已有摘录；附件文本未混入网页摘录；无L3、无新CI/推送/PR/合并/部署。日志 `D:/study-agent-validation/early-findings-{backend,frontend,browser,build,mypy}.log`。本机/项目配置只读检查未发现 Guardian旧字段，未改用户配置。

**最新用户反馈与唯一下一片（覆盖下方旧NEXT）：UI需要克制、疏朗；纳西妲头像不能是灰占位。** 检查真实头像/fixture差异，收敛消息头、研究状态和输入区的边框、体积与重复说明，保持已有选附件、追加/排队、停止、过程展开行为；用桌面/移动截图复核。这是六项通用能力中的智能UI与连续交互改进，非学习系统扩张。

**2026-10-18 当前执行片：下一轮问题的附件保存/恢复/发送（本地，未合并）。** 分支 `codex/chat-queue-attachments-20261018`，工作树 `D:/study-agent-validation/chat-steer-attachments`，base 为上一片 **`1ecf7b47ce6352c6ebb11dda4d4fff3270126378`**；提交由本段所在 Git 提交恢复，审阅仅 `1ecf7b47..HEAD`。原 `codex/chat-steer-attachments-20261018` 分支停留在1ecf，保留独立切片。队列现在保存服务端附件身份（ID/hash/filename），不把附件放入当前研究；恢复后手动发送仅带该条选择，并重走本会话/ready检查。无效或绑定期间消失的附件拒绝整个入队；同请求ID改选附件拒绝；文本相同但附件ID/hash不同的已完成turn不能隐藏或完成队列。UI显示附件数量；失败保留选择、成功清除本次选择，网络重试保持身份。兼容旧无附件队列，无数据库迁移/新执行权威，未扩展当前研究的工具权限。验证与最新下一片见下方。

**当前片证据：** 命名后端L1 `chat_queue_attachments` **72 PASS / 31.30s**（含真实SQLite重载/旧checkpoint合并、旧纯文字队列、同ID改附件拒绝、跨会话/未就绪/删除/绑定时消失负控、错误文件/同ID不同内容hash不能冒充已交付）；前端影响集 **75 PASS**（API载荷、失败重试身份、更改选择新身份、队列恢复与后续turn附件）；桌面+移动focused浏览器 **2 PASS / 7.3s**（入队503保留选择、重试同身份、只在后续turn发送该附件）；TypeScript/Vite build、全范围Ruff、diff-check PASS，mypy **122/128 NEW=0**。仅队列接线的有界L1，无L3；JSON已有队列条目增加可选refs，旧条目按空附件处理，未变schema/cursor/研究权威。运行日志 `D:/study-agent-validation/chat-queue-{impact,backend,browser,build,mypy}.log`；源码与交接在本提交后保持干净。无新远端CI、未推送/PR/合并/部署，不授予真实模型/研究质量GO。

**上一片：完整聊天能力盘点 + 运行中附件补充修复（已本地提交，未合并）。** 分支 `codex/chat-steer-attachments-20261018`，base 为原产品线末端 `4ffa44521cb5ef2c1a50e73c6d03b0ce42710beb`，提交 `1ecf7b47ce6352c6ebb11dda4d4fff3270126378`。main 仍为 `335fc9b7875b848f202122362f2e0f8b5a9db0ee`，本片不是 main 已交付能力。独立 Async 候选 `2c58eb0eecc37ba004a7deb601e991091248bf1a`、原审计 `4a549f7d` 与测试修复线保持不变；本片不重新混入 Async 接线。用户要求以 GPT-6 式聊天、搜索分析、UI 为最终目的，按有界功能和影响集推进；本轮未运行 L3。

| 用户要求 | 当前实现情况（原产品线，不等于 main/真实验收） | 尚未闭环 |
| --- | --- | --- |
| 自然智能聊天 | 已有多轮上下文、角色/模式、历史会话、重试/继续与答案流 | 未完成类 GPT-6 的综合体验验收；研究中插话目前按补充处理，仍需明确改变话题与继续研究的产品语义 |
| 智能聊天 UI | Rev 3 同一对话承载答案、过程、补充回执、计算/图表卡片；有桌面/移动离线证据 | 模型通用选择地图/按钮/滑块/棋盘等富交互内容尚未闭环；移动附件 chip 显示空间偏窄，记为相邻 UI 债务 |
| 搜索分析、边研究边讲 | 已有搜索/阅读/补查过程事件、来源与答案链路，Deep 过程入聊天 | 真实读取、来源复用、比较覆盖、答案引用质量仍需资格验收；A/B/C 整体未放行 |
| 边研究边回答、连续交互 | 已有计划开场、过程播报/去重恢复，Deep安全边界、持久补充与回执；两片补齐运行中/下一轮的附件链路 | 过程播报不等于已有有用的阶段性答案；实质增量答案尚需补齐/验证，Lookup/Standard无同等转向能力，真实模型延迟及方向准确性待验收 |
| 文件/多模态 | 已有消息级绑定、研究消费、补充附件后端与隔离校验；G1/G2 实现已完成，旧待办过期 | 真实视觉模型和研究联动复验、长期资料转正端到端验收 |
| 工具、计算、图表 | 已有有界计算协议、结构化结果/图表、隔离 Python，历史容器负控证据保留 | 真实模型自主工具选择和完整任务质量未验收 |

**本片修复与证据：** 原运行中补充丢弃 `attachmentIds`，失败返回也会清空输入区附件选择；现在文字/附件共用同一 steer 请求，失败保留选择，成功仅清除本次提交的附件。同内容/同附件集合重试复用 request ID；换附件则换 ID。3 项新增检查在旧代码上失败；修复后前端 L1 影响集 **72 PASS**，后端绑定/多模态联动/生产 policy 影响集 **36 PASS / 18.74s**，桌面+移动 focused 浏览器 **2 PASS / 5.7s**（含一次503失败、保留选择、同身份重试、空附件后续补充、不中断原 SSE），TypeScript/Vite build PASS，Ruff/diff-check PASS。浏览器首次使用全旅程配置及开发者诊断文本定位失败；已改用既有 `playwright.conversation.config.ts` 与用户可见错误提示，不更改全旅程门槛。日志 `D:/study-agent-validation/chat-steer-{negative,impact,backend,build,browser-focused}.log`；当前仅前端及交接变更，未改后端/迁移/预算/Gate。无新远端 CI、未推送/PR/合并/部署；真实供应商验收未重跑，原资格门保持关闭。

**唯一下一slice：让研究中更早出现有用内容。** 对照已有过程播报与答案生产点，补齐有来源依据的阶段性发现展示并逐步补全，区分“正在搜索”与“已取得什么发现”；复用既有证据资格与来源身份，不将未验证的临时内容升级成正式答案/完成状态。继续独立小片和影响集；最终候选仍遵守 AGENTS.md 的发布/审阅门。

**产品优先级（用户2026-10-18明确）：** P0可靠聊天/长期研究（Async-R1c）；P1自主搜索分析引用（M4-C5/RP-1/Arm C）；P2边查边讲/插话/增量答案；P3模型选用Python/计算/绘图；P4富交互UI；P5统一多模态/跨会话；P6学习和专业场景。P2–P5可以在安全底座稳定后独立推进，不以全部研究质量达标为界面开发前提。每项工程必须指出改善哪项可感知能力；优先快速出现有用内容、持续更新、不中断插话、保留已有成果、统一入口。租约/CI/证据系统是实现手段，不是产品定位。

**2026-10-11 研究开场 + 过程播报（Research Approach）Slice A 后端合同（独立分支，未合并）：** 新分支 `codex/research-approach`，worktree `D:/study-agent-validation/research-approach`，基线 main `7a8b6d55`。新增展示合同 `ResearchApproach`（`schema=research-approach-v1`），**无证据权威**：不写 Evidence Gate、不使目标变 `supported`、不作答案引用、不喂回核验器；**不改动严格计划合同** `standard-research-plan-v1`（四键 envelope 原样）。落盘于 `research_context["approach"]`（SQLite `web_lookup_runs.research_context`，刷新不丢），经既有 `research` SSE 事件的可选 `approach` 字段发出，旧客户端忽略即可。起源优先级 `model_plan` > `model_generated` > `direction_update` > `fallback`；`status∈{pending,ready,failed}`，创建期 `pending` 种子（暂无开场时显示既有确定性工具进度）。保证：**开场失败不阻断研究**（`generate_approach_or_fallback` 吞掉超时/空/非法负载降级 fallback）、**不突破预算**（单次有界调用并回报是否计费）、**不走答案 token 流**（走 `research` 进度通道）、确定性校验（模式长度上限、空/超长、空泛过渡语、未验证完成宣称、与上一条重复）。接线：`WebLookupService.create()` 落种子；`chat_routes._research_progress()` 绑定 run 身份发出 `approach`。证据：`tests/test_research_approach.py` 18 PASS；L1 影响集 91 PASS（web_lookup_run / research_contract / dispatch / run_owner / answer_streaming / standard_research / pedagogy）；ruff、mypy 122/128 NEW0。文档 [RESEARCH_APPROACH.md](RESEARCH_APPROACH.md)。**下一刀（Slice B）**：把 Standard 规划保存后投影为 `model_plan` 开场、接线有界模型生成（含预算计费）、前端 `ChatResearchProgress.approach` 类型 + 控制器按 `(run,turn,sequence)` 去重/恢复 + `AnswerProgress`/`ChatPanel` 呈现 + 复制仅答案/取消显示已停止/会话隔离，以及真实 DeepSeek 延迟校准。**边界冻结**：不拥有 L/S/D 研究质量与完成率门、M4-C5 Evidence Gate/核验器/来源资格、模型调用上限与研究预算与计费口径、自动升档、学习状态/记忆/正式答案与引用权威、既有对话角色切换；生产 B OFF、RP-1/M5 NO-GO 不变。

**2026-10-11 多窗口整合 / 当前执行权（覆盖下方旧 NEXT）：** 主目录干净，原混合改动、26份图片及旧工作树继续保留；64工作树最终复核：12 dirty（保留混合工作树 + 11本地MCP覆盖），11配置另做逐文件SHA256备份于 `D:/study-agent-validation/consolidation-20261011-final-audit/local-config-backups.json`，见 [工作区索引](WORKSPACE_INDEX.md)。#205/#208已合并；#207/#214在各自exact-head CI成功、当前范围审阅无未解决finding后expected-head合并，当前main为 `5155f107fae23fb19ce7d857745075b5b6a21bc2`。本地隔离组合head `be03002084fd9d6ce6a130dc9d79489bc391036c` 全量 **4294 passed / 6 skipped / 1433.69s**；main与该候选的src/tests/tools/frontend/依赖/config/CI/infra树完全一致，属于同树回归证据，不称新main独立跑过L3。frontend457、browser77、真实栈14、平台46、导航51、build/Ruff/diff-check/mypy NEW0均PASS。专用L3预检脚本在全量启动后补核PASS，未冒称启动前调用。远端 exact-main push CI `38117936966` 对 `5155f107fae23fb19ce7d857745075b5b6a21bc2` 已 SUCCESS；当前已合并主线可以称 REMOTE GO，新待合并 PR 仍分别等待新 head CI。

| 项目 | 完整候选 SHA / branch / worktree | 当前证据与结果 |
| --- | --- | --- |
| #207 | `3d457835abfa61ed596f26e6a6a12f803f451017` / `codex/ui-heading-focused-port-20261009` / `D:/study-agent-validation/ui-heading-review-fix-20261011` | pull_request CI `38115979560` SUCCESS；merge `5bc175389f54cf088ac794441b04c3c36d2f0bff` |
| #214 | `1e5b89260ffdd16d14be09cdc0fa95d0a301b6a0` / `feat/m4c2-navigation-diversity` / `D:/study-agent-validation/m4c1-eval` | pull_request CI `38115047192` SUCCESS；merge `5155f107fae23fb19ce7d857745075b5b6a21bc2`；展示层回归不授予研究质量GO |
| #215 | `codex/workspace-index-20261011` / `D:/study-agent-validation/workspace-index-20261011` | 旧head `962fce09cdfa53a6acc16459b258c5ce4a7f5e3b` 的CI `38116155805` SUCCESS；两条新增P1在本刀修复，新head由Git恢复，旧CI不授予新head |

| #203 | `b0590c4ce62b14cad6335738d7747ee7f85fa23a` / PR branch `codex/learning-state-1-closeout` / 修复 worktree `D:/study-agent-validation/learning-isolation-review-fix-20261011`（本地 branch `codex/learning-isolation-review-fix-20261011`） | 两条 P1 已补证并 resolve；真实研究/HTTP populated SQLite 快照与落库负控，影响集299 + 相邻12 PASS，合入5155后边界回归124 PASS；Ruff PASS、mypy122/128 NEW0；新提交CI尚待，不沿用旧绿灯 |
| #204 | `cf906e2c86135d329611f133050a40ced38f89ef` / PR branch `codex/rp1-ab-evidence-archive` / 修复 worktree `D:/study-agent-validation/rp1-archive-review-fix-20261011`（本地 branch `codex/rp1-archive-review-fix-20261011`） | 原失败CI实际133项告警均为固定Git/校验值，逐项精确登记；Linux原报告133、本地37均无剩余；18负控 + 41 CI enforcement PASS；实际scanner合成AWS格式负控保留告警，409原文件及Git blob校验不变，新head CI尚待 |

**唯一下一slice：现有改动合并收口。** #215修复后记录一次新exact-head CI和最终审阅；#203/#204修复已推送，门前读取PR当前完整head；表中SHA为本次快照，若head移动须重新绑定新SHA的CI与增量审阅，不可沿用旧绿灯；下一轮查询精确head CI与新增审阅；精确head绿灯且最终审阅无未解决finding后expected-head逐个合并。不得重复触发已运行的CI，不降低门槛。当前Learning State-1 L1 CLOSED、L2–L6仍NOT CLOSED；RP-1/Deep-4B及B-Search资格裁定不变。禁止从历史设计文档启动新UI开发；合并后新main必须另核对exact-main CI，不能继承当前5155的远端绿灯。

**2026-10-09 本地MCP固定配置单独交付：** 用户授权提交远端尚无的本地完成成果。branch `codex/playwright-mcp-pin-delivery`、base origin/main `f35b13b7`，只迁移既有已验证本地playwright server配置至当前main，固定 `@playwright/mcp@0.0.83 --browser chrome --isolated`，其他server逐项未变；JSON/版本/差异核验通过。复用2026-10-05原真实JSON-RPC MCP smoke记录 `D:/study-agent-validation/mcp-migration-20261005/RESULT.md`，不宣称本次新增smoke；用户级配置与现有备份不动，不复制旧frontend锁文件（远端已有1.62.1）。仅开发工具配置与交接，无研究预算/Gate/UI实现/另一窗口代码改动，无生产部署；推送refs与一次CI观察由local-delivery-closeout恢复。A/B归档与B线生产接线在独立分支，RP-1仍NO-GO。

**阶段状态（本段旧NEXT由上方2026-10-11整合门覆盖）：A线 Learning State-1 L1 CLOSED，L2–L6 NOT CLOSED。** Deep-4A implementation 已合并并 CLOSED；**Deep 阶段除 Deep-4B 外全部 CLOSED**。Deep-4B（automatic publication）= **NO-GO**（无 qualified semantic judge）。A 线：**Learning State-1 / L1 已 CLOSED**（authority `0de80751`），学习信息来源权威已封板；**L2–L6 仍未 CLOSED**，下一门 = **Learning State-1 L2–L6 验收收尾**（整理 T07–T18 的直接/间接证据，满足合同即关闭，不为制造增量而改实现）。B 线：**Intelligent UI × Lookup/Standard/Deep** —— UI 工作台 **#201 已合并**；**Research Presentation-1（RP-1）仍在 B 线施工**（原 `reading-notebook-ui` 分支，R6 未 CLOSED），只读 `learning_view` 接口**未启动**；A / B 两线各自独立 PR，不得混入同一 PR。

**2026-10-08 B 线：UI 工作台已接入（#201 MERGED）：** [UI 接入 PR #201](https://github.com/2002yy/study-agent/pull/201) 已合并，merge commit `5f4e81e22ab85c0a27c3ad82214c0f1dc62b79eb`。独立 worktree `D:/study-agent-validation/ui-main-integration`、branch `codex/ui-main-integration`；包含阅读并排/对话居中、纸白蓝灰及设备字体偏好、四角色最新版头像、内部角色设置、框内紧凑自增高输入框、右上资料开关、可记忆拖动宽度、只读正文/PDF 与引用定位，以及已完成的教学交互组件。**Learning State-1 与 Research Presentation-1 均不混入此 PR**；研究协议 / 真实三层 R6 继续由原 `reading-notebook-ui` 分支负责（**RP-1 未 CLOSED**）。

**2026-10-08 PR #201 合并前本地证据（后端范围证据，不声称新 SHA 独立跑过 L3）：** 生产精修 head `e1a24697f1fad1546614fd81123bc56db90cdca4`；`f60c27e576a8c2d2460d7747f1fee7f4d504b5d4` 后端全量 4142 PASS / 6 SKIP / 1500.96s；f60 到 e1 只改前端/浏览器测试/docs，后端树及后端测试完全相同。最终前端 453 / 浏览器 77 / 真实 React+FastAPI+SQLite 交互 14 / tsc+Vite build 均 PASS；mypy 无新增错误（122/128）。QA 证据索引：`D:/study-agent-validation/reading-notebook-ui-evidence/ui-integration-qa.json`。

**失败与恢复证据（#201 内）：** 首次 real-stack 11/14（旧“更多开始方式”定位与手机未开导航的整理入口过期）；第二次 13/14（测试把完整可见 token 误当 durable commit，改为等待真实 turn-end 状态后 14/14）；精修后浏览器首轮 75/77（底部字号旧 13px 断言过期），统一为 12px 后 77/77，提示条新增高度/折叠/键盘展开断言。日志及 1440/390 截图留在 `D:/study-agent-validation/reading-notebook-ui-evidence/ui-integration-*` 与 `ui-refined-final-*`。

**Current Action：**
```text
Deep-4A is merged and CLOSED (authority ea73b855).
Deep-4B automatic publication is NO-GO until a qualified semantic judge exists.
Learning State-1 L1 is CLOSED (authority 0de80751); L2-L6 remain NOT CLOSED.
Next gate = existing PR integration closeout (2026-10-11 handoff above).
B line = Intelligent UI x Lookup/Standard/Deep: UI workbench #201 MERGED (5f4e81e2); Research Presentation-1 still in progress; read-only learning_view not started.
```

**Deep 阶段合同（已冻结）：**

```text
Deep-1  docs/DEEP_1_CONTRACT.md           CLOSED
Deep-2  docs/DEEP_2_CONTRACT.md           CLOSED
Deep-3T docs/DEEP_3T_TRIGGER_CONTRACT.md CLOSED
Deep-3  docs/DEEP_3_CONTRACT.md           CLOSED
Deep-4A docs/DEEP_4A_CONTRACT.md          CLOSED (87 sections)
Deep-4B automatic publication             NO-GO until qualified semantic judge
```

**Learning State-1 / L1 CLOSED ✅（A 线第一刀）**

**2026-10-11 #203 L2–L6 本地补证 / 待远端收口：** [验收矩阵](LEARNING_STATE_1_ACCEPTANCE.md) 已补齐真实Lookup/Standard/Deep生产服务及普通UI HTTP动作的已填充SQLite durable全表快照；四个真实落库变异负控均检出，显式授权closure正控仍能写入。原两条P1已修复并resolve；299影响集+12相邻回归、Ruff和mypy122/128 NEW0通过。重新合入main `5155f107fae23fb19ce7d857745075b5b6a21bc2` 只解决交接文档冲突，不改变生产语义；等待新head CI与最终语义审阅后收口。L1权威仍`0de80751`，**L2–L6目前NOT CLOSED**；外部模型/recorded Deep terminal fixture不冒称自然研究或浏览器验收。**唯一下一slice为现有PR合并收口**，历史NEXT不授权新开发。

```text
authority   squash merge **0de807513e758bac3ab6d10a35be3e1320772552**
            PR #200
exact head  **f96cdab9aa243da6dc0c223a885d355e9ea0edf3**
exact-head CI **37763976833 SUCCESS**（含 Enforce required CI outcomes）
contract    docs/LEARNING_STATE_1_CONTRACT.md（A+ 细化版；L1–L6 / T01–T18 / M1–M6）

closed scope
            read-only authority 分类（learning_authority_projection.py）
            user_goal / user_self_report / system_inferred / verified /
            legacy_unverified；仅 verified 是 mastery evidence
            消除 confirmed_points → expected_concepts 隐式回退
            （chat_service.py + policy_chat_service.py，两处消费点）
            navigation / resume 只读来源标签（legacy 标 legacy_unverified）
            durable authority 的 source_id = 真实 UnderstandingEvidence id
            （lineage 解析后仍指向实际验证记录；无记录则空）

validation  本地 impact set **280 passed**（含 policy / standard /
            external-data-policy 生产路径）
            M1（基类消费点）与 M1b（policy 生产路径）负控均单独验证
            ruff PASS | git diff --check PASS
            mypy baseline PASS（122/128）
            package helper OK

known boundary
            L2–L6 **未 CLOSED**（下一门 = L2–L6 验收收尾）
            未改动 Socratic / durable 写入语义 / §164 仪器
            未新增自动 closure / 自动 Goal / 新存储
```

> Learning State-1 L1 authority 永久为 merge commit `0de80751` / exact-head CI `37763976833`。此后 main 上的 docs-only 记录提交只是该记录的载体，**不表示新 SHA 跑过验证**。

**Deep-3T authority（合同冻结基线）：**
```text
exact-main  **1514bbf76031dfeca2cb03e9c52adf5d149cd724**
            （Deep-2 CLOSED 的 exact-main；Deep-3T / Deep-3 合同已基于它核对接口）
```

**Deep-3 implementation MERGED（CLOSED 待 exact-main CI）**

```text
merge commit   **e5382659b0aa1deca9954702b108aa51ef745e93**
PR             #194（expected head f6f1ab8e）
exact-head CI  37654811749 SUCCESS
exact-main CI  37656689912 **cancelled**
              reason = superseded by a later docs-only main push
              NOT a product/test failure
              （取消时代码门已全过：pytest / ruff / mypy / mypy baseline /
               frontend deps / frontend test+build）

CLOSED authority （方案 A）
              **caa3e307 / 37658465809**
              iff 37658465809 completes SUCCESS
              caa3e307 differs from e5382659 only by docs
              (Deep-4A contract / PROJECT_STATUS);
              **Deep-3 production bytes are unchanged**

closed scope
            background continuation + parent finalization
            chat wrapper only wakes (never blocks on Deep)
            terminal child never re-executes
            honest research terminal -> parent completed
            transactional finalize revalidation
            durable blocked + recorded-terminal integrity + first terminal wins
            singleton reuse + runner cache reset

known boundary
            publication_authority = false
            assistant_message / pedagogy / learning untouched
```

> Deep-3 authority 以 exact-main CI 通过后的 merge commit 为准。Deep-3 CLOSED authority = `caa3e307` / CI `37658465809`（SUCCESS）。

**Deep-4A CLOSED ✅**

```text
authority   merge commit **ea73b8555b56e7f8c65000a9908fb20c9c7e216f**（squash）
            PR #197（expected head 08a27510）
exact-head CI  **37751620983** SUCCESS（G4A-51 门）
exact-main push CI 37753888528（push @ ea73b855；写入本状态时 in progress，
            与既有模式一致，可能被本 docs-only status push 取代）

head note   原候选 head 03f344f4；因 GitHub 对 pull_request 使用 head 分支的
            workflow 文件，旧 CI 一直用 /dev/null 打包命令而失败；
            将 origin/main（含 #198 ci.yml 修复）merge 进分支 → 08a27510。
            08a27510 与 03f344f4 产品树逐字节相同，仅 .github/workflows/ci.yml +1/−1。
            原语义审计 PASS 与 13/13 mutation 证据继续适用于未变化的产品代码；
            用户裁定不需要为新 SHA 重跑 L3。

closed scope
            audited publication candidate（audited-but-not-approved）
            publication_authority = false
            0 model / 0 network calls；不修改 answer
            PUBLICATION 第三 trigger stage
            unit-safe synthesis（EvidencePayloadUnit / effective_units / per-unit locator）
            layered validator（blocked 只需 bounded reason + 无 result；
            audited 绑定 owner.child_run_id == result.child_run_id + source/result digest 相等）
            真实多线程 C5/C6/C7 竞态
            runtime 0-model / 0-socket gate
            G4A-1…G4A-51 | mutation authority 13/13 PASS

known boundary
            仅“审计通过的发布候选”，未获发布批准
            assistant_message / pedagogy / learning_state 不变
```

> Deep-4A authority 永久为 merge commit `ea73b855` / exact-head CI `37751620983`。此后 main 上的 docs-only closeout 提交只是该记录的载体，**不表示新 SHA 跑过验证**；按 `AGENTS.md` §4.5 / §10.4，docs-only 变更不需要重跑 L3 或 full suite。

**Deep-3T CLOSED ✅**

```text
authority   **823265ae113c0f488e0e8d2d0a448c6079b80884**

validation  exact-main push CI **37642664449** SUCCESS
            ordinary full pytest PASS | ruff PASS | expanded mypy PASS
            mypy baseline PASS | frontend test/build PASS
            browser Golden Journeys PASS | real-stack browser gates PASS
            required outcomes PASS

closed scope
            durable-state-backed Deep trigger (no new queue table)
            ARM crash window recoverable
            pending Deep recoverable
            keyset paging so the whole durable queue stays reachable
            absent != malformed (deep_terminal null is not absent)
            immediate startup scan | 15s periodic rescan | non-blocking wake
            single worker | bounded shutdown | callback exception isolation
            G3T-1…G3T-23 | mutation authority PASS

known boundary
            production inert (worker not started, callbacks not wired)
            Deep still not activated

known limitation (not a closure blocker)
            no starvation-freedom guarantee when front-of-order work items
            never change durable state; revisit with a scheduler/fairness
            contract if a real backlog appears
```

> Deep-3T authority 永久为 `823265ae` / CI `37642664449`。此后 main 上的 docs-only closeout 提交只是该记录的载体，**不表示新 SHA 跑过验证**。

**Deep-2 CLOSED ✅**

```text
authority   **1514bbf76031dfeca2cb03e9c52adf5d149cd724**

validation  exact-main push CI **37628909373** SUCCESS
            ordinary full pytest PASS
            ruff PASS | expanded mypy PASS | mypy baseline PASS
            browser Golden Journeys PASS | real-stack browser gates PASS
            required outcomes PASS

closed scope
            Deep-1 child → existing ActiveResearchRuntimeExecutor
            atomic execution + active Claim Engine attach
            S6 fail-closed / no legacy downgrade
            Deep absolute wall clock + crash resume
            Standard seed → normal assessment / ranking
            LOCAL MATERIALIZE
            0 network / 0 reads_used for seed reuse
            char-budget accounting
            content_available reread suppression
            B1–B7 + exception taxonomy
            G2-1…G2-42

known boundary
            parent deep_terminal remains pending
            publication_authority = false
            no automatic ChatService continuation
            no parent finalization
            no synthesis / publication cutover
```

> Deep-2 authority 永久为 `1514bbf7` / CI `37628909373`。此后 main 上的 docs-only closeout 提交只是该记录的载体，**不表示新 SHA 跑过验证**；按 `AGENTS.md` §4.5 / §10.4，docs-only 变更不需要重跑 L3 或 full suite。

**Deep-2 seam authority（合同冻结基线）：**
```text
exact-main  **41e2d6f9132b0e72b3cf058d913c304f9c066ea0**
            （Deep-1 closeout 的 docs-only 后继；合同已基于该 exact-main 重新核对实际接口）
```

**Deep-1 authority（永久不变）：**
```text
e5c63c03c9ac77b273f2bfc158111ac676e9bc42 / CI 37599443309
```

**Standard authority（永久不变）：**
```text
c48a1ac313e59ab0104364db519340f1460e84dc / L3 37514856913
```

**Deep-1 CLOSED ✅**

```text
authority   main / e5c63c03c9ac77b273f2bfc158111ac676e9bc42

merge       PR #187
            expected implementation head  2cba839e46073efabd04ba127b3559a142efc6ee
            merge commit                 e5c63c03c9ac77b273f2bfc158111ac676e9bc42

validation  exact-main push CI 37599443309 SUCCESS
            ordinary full pytest PASS
            ruff PASS | expanded mypy PASS | mypy baseline PASS
            browser Golden Journeys PASS | real-stack browser gates PASS

closed scope
            Standard → Deep handoff
            durable seed
            deterministic child
            retry / integrity addendum
            G1–G15 PASS；G14a–G14g PASS

known boundary
            publication_authority = false
            Deep child remains pending / inert
            no active runtime execution
            no Deep-2 activation

next single slice (COMPLETED)
            Deep-2 exact-main implementation-seam audit (done)
            → detailed Deep-2 contract frozen in docs/DEEP_2_CONTRACT.md
```

> Deep-1 authority 永久为 `e5c63c03` / CI `37599443309`。此后 main 上的 docs-only closeout 提交只是该记录的载体，**不表示新 SHA 跑过验证**；按 `AGENTS.md` §4.5 / §10.4，docs-only 变更不需要重跑 L3 或 full suite。

**Deep 路线（冻结）：** Deep **不重新实现深度研究引擎**。仓库现有 `ActiveResearchRuntimeExecutor`（含多波次 gap research、Evidence Gain、per-claim/per-gap saturation、8-wave ceiling、Evidence Gate、预算尾保留、持久化 cursor、attempt marker、崩溃恢复、stop gate）就是 Deep 的执行核心。Deep 的工作量是**把 Standard 的成果可信地送进已有研究引擎**，因此拆为 Deep-1（handoff + seed + 生产 inert，**已 CLOSED**）→ Deep-2（激活 active runtime + budget + resume）→ Deep-3（自动 continuation + fail-safe）→ Deep-4（synthesis projection + cutover + Deep phase L3）。

**Standard closure authority（唯一权威）：**

```text
authority SHA     c48a1ac313e59ab0104364db519340f1460e84dc   ← exact main
L3 authority run  37514856913（ci-l3, workflow_dispatch）
L3 result         3866 passed / 6 skipped in 385.94s
L3 前置           l3_preflight PASS @ 同一 exact-main；duplicate-skip guard success
exact-main push CI 37512787764 success
```

**权威表述（不得改写）：** Standard phase CLOSED **at `c48a1ac3`**。此后 main 上的 docs-only closure record 提交**只是该记录的载体**，不表示新 SHA 跑过 L3；按 `AGENTS.md` §4.5 / §10.4，docs-only 变更不需要新的 L3。

**已 CLOSED 的三个 slice：**

| Slice | PR | merge commit | 范围 |
| --- | --- | --- | --- |
| Standard-2 | #180 | `62f0e7bf` | 持久化研究计划 + 可恢复执行循环；输出 artifact |
| Standard-3 | #182 | `964a848f` | 逐事实机械绑定、来源身份、冲突裁决；publication_authority 恒 false |
| Standard-4 implementation | #184 | `cee6aefb` | Lookup → Standard 自动 continuation（未接线生产） |
| Standard activation | #185 | `c48a1ac3` | production composition OFF → ON（本刀即最终 candidate） |

**生产形态（已生效）：** `get_chat_service()` → `StandardContinuationChatService`；Lookup 的 `resolve_web_tools` 与 Standard 的 `gateway` 是**同一个 web agent 对象**，共享同一 RuntimeRepository；无第二 gateway、无第二层 cache、无 feature flag。Standard 语义（admission / deadline / lease / exactly-once / binding / fail-safe）未因接线改动。

**Standard 边界（冻结，不再调整）：** `usable/read_backed/relevant` ≠ claim support ≠ publication authority；自动 continuation 只产出内部证据状态，**不修改 assistant_message、pedagogy、learning_state**；continuation 崩溃时已完成的 Lookup 答案照常返回。

**CI 纪律（已冻结并实测）：** `AGENTS.md` §14 分层验证；`tools/ci_scope.py` 是 browser/frontend/impact-set 路由的**唯一权威**（workflow 不得按 event 类型重新推导）。standard 类别 → `standard_research_loop` fast path；`learning-backend`（如 `runtime_repository.py`）无 mapping → 普通 full pytest，**普通 full pytest 不是 L3**。正式 L3 只能由 `ci-l3.yml` 显式触发一次，且跑在 exact-main。

**本机主 worktree：** `C:/Users/Zhang/Desktop/study agent` 位于 main，但 `.mcp.json`、`docs/PROJECT_STATUS.md`、`frontend/package.json`、`frontend/package-lock.json` 有既存修改，保留原样，不用远端 main 覆盖。施工 worktree 位于 `D:/study-agent-validation/`。

**冻结路线：**

1. ~~Standard-2~~、~~Standard-3~~、~~Standard-4 implementation~~、~~activation~~：**全部 CLOSED**。
2. **Deep（Deep-1 / Deep-2 / Deep-3T / Deep-3 / Deep-4A 全部 CLOSED；Deep-4B NO-GO；当前 = Learning State-1 L2–L6 验收收尾）**：多轮重写、Evidence Gain、saturation、长预算与 interruption/resume；UI 继续独立后置。合同见 [`DEEP_1_CONTRACT.md`](DEEP_1_CONTRACT.md)，已冻结四件事：Standard → Deep 升级条件、Deep 独立预算（`DEEP_V1_BUDGET`）、如何复用 Standard 已有 evidence 而不重读（durable seed + 二次 hash 校验）、stop / saturation / interruption-resume 定义（全部复用现有 authority）。

**状态口径：** `Standard = CLOSED ✅`；`Lookup` 保持其既有已验收状态；`Deep-1 / Deep-2 / Deep-3T / Deep-3 / Deep-4A = CLOSED ✅`；`Deep-4B = NO-GO`；`Learning State-1 L1 = CLOSED ✅`（authority `0de80751`）；`Learning State-1 L2–L6 = 未 CLOSED`（下一门 = 验收收尾）；`UI = 后置`（独立交互合同另开一 PR）。

## 0A. 冻结研究路线

```text
Lookup
  → VERIFIED / SAFE_ABSTAIN / pending ESCALATE_STANDARD
Standard（CLOSED）
  → 多源补全 / 双方比较 / 冲突处理；已由 production runtime 自动消费
Deep（Deep-1 / Deep-2 / Deep-3T / Deep-3 / Deep-4A CLOSED；Deep-4B NO-GO）
  → plan / gap / Evidence Gain / saturation / interruption-resume
  → 复用现有 ActiveResearchRuntimeExecutor；不新建第二套研究引擎
```

共享原则：**模型决定“去哪找、找什么”；程序决定“你到底找到了什么”。** `usable/read_backed/relevant` 不等于 claim support；claim support 不等于 publication authority。

## 0B. 仓库与施工纪律

- 一个 feature slice 尽量整块完成、一次验证、少提交；只在阶段门需要权威 exact-head 证据时触发 CI。
- push/PR 之后只认当前 exact head；旧 HEAD 绿灯不能替代新 HEAD。
- 生产候选只有在 CI、最终审查与 expected-head 一致时才允许合并；merge 与 CLOSED 是不同门。
- UI、研究与其他项目保持独立 bounded slice，禁止为赶门把无关改动混入。

## 2026-10-11 RP-1 证据归档安全验收（#204）

**2026-10-11 #204 归档与安全修复候选：** 归档 [原A/B与UI证据](evidence/rp1/2026-10-09/README.md) 的409原文件/4,842,111字节保持原始SHA；96规划、原6回答+续18回答、合并24答卷/映射/封存评分和22张UI截图仅作证据保存。133个固定Git/校验值逐条精确登记，原Linux报告与本地扫描无剩余，18负控/41 CI outcome测试PASS，扫描插件/排除规则/强制门未放宽。当前重新合入main `5155f107fae23fb19ce7d857745075b5b6a21bc2`，只解决交接docs冲突；须新head CI与最终安全审阅，RP-1/Deep-4B/B-Search资格不变。**唯一下一slice为现有PR合并收口**，下方历史NEXT不构成新功能授权。
