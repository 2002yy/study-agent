# Lookup L5：恢复正文与事实支持

本 slice 从 #174 merge `7ff7451da608775324383968b4c7ed23c5687832` 独立分支开始，不修改其16案例、生产解析器、预算或发布权限。进度唯一入口仍为 `docs/PROJECT_STATUS.md`。

## 执行门与证据等级

#174 exact-head PR CI37312220879 SUCCESS、final review PASS、expected-head合并完成。2026-10-05核对exact-main push CI37314347931 completed/success，head7ff7451d，正式执行门已通过。下方开发记录保留当时的时间语义；最终结论见来源重放结果。

`tests/test_lookup_rescue_support.py` 的四例使用明确标为synthetic的搜索/读取传输数据。它们经过真实GeneralWebGateway → recovery → ChatService → 临时SQLite发布出口；属于运行合同回归，不能冒充真实或原始响应绑定的来源资格证据。实际网络和模型调用不得从测试意图推算。

## 冻结四例

| 案例 | 恢复正文 | 所需结论 |
| --- | --- | --- |
| 替代官方来源 | 首选官方读超时，搜索找到另一官方站点正文，含明确日期 | 检查当前合同是否允许该URL和reader提供字段绑定；不支持则明确拒绝发布 |
| 非官方直接来源 | 正文包含目标版本和日期 | 可信/直接不等于发布权；无有效逐字段绑定则拒绝发布 |
| 相关但缺字段 | 目标版本教程正文，不含日期 | 可读与read_backed允许成立；日期支持和发布必须拒绝 |
| 多正文不支持 | 邻近版本正文 | ≤2搜索阶段、≤3逻辑读、≤30秒并保留finalization reserve；拒绝不支持的事实 |

每例分别记录：传输后端调用、逻辑read、查询阶段、耗时、目标覆盖、停止原因、可用正文、请求字段支持、发布refs及摘要。确定性出口答案模型调用为零；禁止用read_backed或目标marker覆盖替代逐事实支持。后端替换是控制数据，不是新reader能力。

## 已核对的发布权限边界

核对范围绑定main7ff7451d：

- `src/web/research/official_resolver.py:valid_candidate` 只接受查询计划中注册的URL。
- `src/web/tool_gateway.py:GeneralWebGateway.read` 通用读取返回正文，不生成原生官方字段跨度。
- `src/web/research/official_publication.py:publish_official_fields` 要求注册候选、native方法、版本一致性、摘要及真实字段跨度。官方域名本身不能授权通用正文。
- `src/application/chat_service.py:complete_turn` 的现有确定性研究出口调用上述字段发布入口，并保存审计；不能绕过该出口把模型知识或相关正文作为事实。

当前已知替代官方/非官方通用正文均缺少这一路径的字段发布权限。不得为了让L5成功临时伪造official_fields、切换模型判定或放宽Gate。若正式重放确认该限制，结论应为：Lookup-Official在其主线门完成后独立合格；Generic Rescue仅恢复、发布NOT QUALIFIED。Lookup整体仍NOT CLOSED。

## 开发失败样本

首轮两个正文写为Python3.14.0，而请求为Python3.14；通用正文的精确target marker不会采纳patch后缀，因此status为provider_exhausted，不能声称read_backed。日志保留 `D:/study-agent-validation/lookup-L5-development.log`（2 failed、85 passed）。该失败来自已知通用身份边界，不是新生产回归；当前不扩大身份能力。控件正文改成请求的精确3.14，专门测已有可读性通过后是否仍拒绝无字段绑定的发布。旧失败没有被重解释为通过。

## 开发准备记录（历史）

### 来源重放工具（开发准备）

`tools/run_lookup_rescue_support.py --manifest <sources.json> --main-ci <main-ci.json> --output <result.json>` 要求精确main7ff7451d的push CI37314347931 completed/success记录和干净候选。main-ci文件保存 `gh run view 37314347931 --json databaseId,headSha,event,status,conclusion` 的原始JSON；未完成/错误head/失败记录全部拒绝。

manifest的cases严格为上述四个id，每例query固定为 `Python 3.14什么时候发布`；前3例sources各1份、unbound_exhaustion为2份。每个source保存url、title、payload_path（相对manifest目录的已解码HTML）、payload_sha256、encoding、read_at和kind=captured_public_html。工具核对实际字节摘要，经现有local reader提取正文，走实际gateway/recovery/ChatService/临时SQLite，输出source provenance、raw calls、逻辑/后端计数、stop reason、摘要和发布refs。搜索候选与直达超时仍是受控注入，不能称live discovery或真实provider恢复。

工具开发smoke只使用标明synthetic_development的生成HTML，不计正式来源资格。Windows首次smoke因SQLite上下文只提交事务、未关闭句柄而在临时目录清理时报WinError32；修复仅在工具中追踪并finally关闭其临时连接，没有修改应用数据库。最终工具6 PASS/2.76s、最终命名影响集103 PASS/44.41s，Ruff/diff-check PASS。主线门未通过前仍不执行正式重放。

开发影响集 `lookup_rescue_support`：97 PASS/43.15s；Ruff全src/tests/tools及diff-check PASS。四例分别通过真实发布/保存出口验证零refs、零答案模型调用；前三例read_backed，第四例3次逻辑读有界停止。仅新增独立tests/docs/manifest，未触发生产合同变更或L3切换；#174已有完整3551/6 skip结果不重复跑。正式来源资格化仍未执行。

后续turn核对已知exact-main run37314347931及exactSHA。绿后运行独立四例的来源绑定重放/资格检查，保存明确来源provenance与真实出口审计；如原始来源不足则保持资格未完成。Standard与Deep暂不执行。


## 2026-10-05 来源重放结果与资格结论

干净执行head `fca4283da242953b7241ff15398735f2c16aef33`；base/main `7ff7451da608775324383968b4c7ed23c5687832`；main证据为CI37314347931 push completed/success。结果 `D:/study-agent-validation/lookup-L5-public-source-capture/result.json`，同目录manifest、原HTML、采集时间、payload/reader SHA均保留，不把临时语料提交仓库。实际采集5份公共页面；2份首读TLS/超时错误保存至captures-first-pass.json，换curl仅重试这2份成功。HTML均未经改写。

| 冻结案例与实际来源 | 恢复结果 | 逻辑读 / 查询阶段 | 重放耗时 | 发布 |
| --- | --- | --- | --- | --- |
| alternate_official：[Python官方博客](https://blog.python.org/2025/10/python-3140-final-is-here/) | read_backed | 2 / 2 | 1.515s | abstained，0 refs |
| nonofficial_direct：[Real Python](https://realpython.com/python314-new-features/) | read_backed | 2 / 2 | 0.563s | abstained，0 refs |
| related_missing_field：[3.14教程](https://docs.python.org/3.14/tutorial/index.html) | provider_exhausted | 2 / 2 | 0.312s | abstained，0 refs |
| unbound_exhaustion：[3.13变化](https://docs.python.org/3.13/whatsnew/3.13.html) + [3.15变化](https://docs.python.org/3.15/whatsnew/3.15.html) | provider_exhausted | 3 / 2 | 2.266s | abstained，0 refs |

所有案例答案模型调用=0、dangerous publish=0，实际保存答案摘要匹配发布审计。搜索候选与首选官方超时由工具控制，不是真实搜索provider运行或wall-time SLO。reader使用采集HTML进行真实本地提取；工具返回的read时间是重放执行时间，原采集时间单独保存。

实际替代官方正文有明确目标版本，但本地reader未保留该页发布日期，因此它不是“日期字段齐全”的发布正控，不能因官方域名或URL年月路径补写日期。Real Python正文含直接发布日期仍不具现有注册URL/native字段跨度权限，故安全拒绝。教程没有请求的精确version marker，现有恢复层未达到read_backed；可读3442字符只证明提取成功。邻近版本两份正文总共3逻辑读后有界停止。通用target coverage1/1仍只是marker命中，非逐字段覆盖。

结论：**Lookup-Official QUALIFIED；Generic Rescue recovery-only，publication NOT_QUALIFIED；Lookup整体NOT CLOSED。** 本轮证明已有恢复和拒绝合同成立，没有证明generic rescue可以发布requested claim。该缺口正式保留，不为关闭资格增加临时parser、伪造official_fields或放宽Evidence Gate。

旧#175 head d659801d PR CI37317083177的唯一最终失败为公开main SHA的secrets误报；逐行公开值allowlist注释修复，定向扫描0 finding，10个受影响控件PASS/5.17s；其余生产行为未变，命名L1 103 PASS/44.41s仍有效。注释/文档更新不重跑完整L3。下一执行门是#175新exact-head CI和最终审查→保护合并→exact-main；随后另分支推进Standard多源补全/双方比较/冲突，Deep与UI不混入此PR。


## P2审查修复：旧结果不再授予四例资格

远端head d9f33c7d CI37326488134绿后新增2个P2，#175不得合并。本刀只补资格runner/test，不改生产研究逻辑：CLI执行前验证MAIN是实际记录HEAD的祖先；每例除预算/最终拒绝，还验证如下恢复合同。

| case | status | reads | evidence_tool_calls采用证据 | publication |
| --- | --- | --- | --- | --- |
| alternate_official | read_backed | 2 | 必须有 | abstained |
| nonofficial_direct | read_backed | 2 | 必须有 | abstained |
| related_missing_field | read_backed | 2 | 必须有 | abstained |
| unbound_exhaustion | provider_exhausted | 3 | 必须无 | abstained |

修复head04a0ce63732332da71524a2c5aecf9bdba05a713：工具22 PASS/7.71s，命名影响集119 PASS/51.54s；真实临时Git仓库验证旧/无关HEAD拒绝，全reader失败及每例wrong status/read/evidence均拒绝；CLI负控验证未写产物。Ruff/diff-check PASS，mypy122/baseline128 NEW0，无L3重复。

原公开语料在该干净head重放被**正确拒绝**：教程related_missing_field只有提取成功，无精确目标marker，实际provider_exhausted/2读/无采用证据。日志D:/study-agent-validation/lookup-L5-P2-public-replay.log，exit1；P2-revalidated-result.json不存在。前述旧result.json保留原始观察，但旧“4例完成”的资格结论被撤销；不修改源正文、不调整生产marker来迁就该样本。Lookup-Official独立资格不受影响；L5 frozen-source qualification未完成，Generic Rescue发布NOT_QUALIFIED，Lookup整体NOT CLOSED。

下一步：修复head exact CI与最终review，并以单独小证据切片补真实第三例read_backed/缺日期来源；新的四例门完整通过才可认可来源资格。不把安全拒绝、旧CI或已解决线程当合并授权，Standard/Deep实现继续后置。


## 用户修订：Lookup终态与Standard交接合同（下一生产切片）

本节根据用户后续决定覆盖“related_missing_field必须read_backed”的旧验收要求。测试必须保留公开教程实际provider_exhausted状态，不修改系统迎合测试。本PR只纠正资格观测门；三终态生产路由及Standard接入另开独立slice，不借离线runner宣称生产已升档。

runner仍严格校验已验收main祖先和逐例行为。当前固定公开语料门为：alternate_official/nonofficial_direct各read_backed、2读、有采用证据；related_missing_field为provider_exhausted、2读、无采用证据但有discovery-linked可读正文；unbound_exhaustion为provider_exhausted、3读、无采用证据且邻近版本正文实际读取成功。每例最终abstained。`trusted_tool_calls`仅证明发现关联正文可读，`evidence_tool_calls`才是现有采用证据；两者均不授予claim authority。全reader失败、空正文、错误status/read/adoption仍拒绝资格文件。alternate_official当前博客未保留日期，无绑定，不能称VERIFIED；新路由正控必须用真正已有字段绑定来源。

下一生产终态冻结为：

| 终态 | 条件 | 动作 |
| --- | --- | --- |
| VERIFIED | 请求事实均有有效绑定并通过发布门 | 确定性回答并停止；不升档 |
| SAFE_ABSTAIN | 全provider失败、来源不相关、明确身份不匹配/确定性矛盾、无有价值的补证方向，或明确缺字段且无可行gap | 安全拒绝并停止 |
| ESCALATE_STANDARD | Lookup正常有界结束；至少一条可用且经相关性核验的来源；请求claim仍未绑定；无确定性矛盾/身份不匹配；有明确可继续研究的gap | 输出结构化handoff，由Standard在自己的预算与合同内续研 |

仅“可读”或provider_exhausted不触发升档。相关性不能用marker命中冒充语义支持；relevance未知时不自动升档。当前教程样本为升档候选，并非已通过相关性/身份核验的生产升档成功样例；可保持SAFE_ABSTAIN。generic prose不能因handoff获得新的事实发布权限。

handoff至少保存：schema_version、reason=claim_support_insufficient、原query与requested_claims（product/version/field）、已验证known身份事实及其原来源ref、usable_sources（source/candidate id、canonical/requested URL、reader/body digest、实际read时间、采用/身份/相关性状态，正文按现有持久化ref保存）、unresolved gap（需要的字段及binding缺口）、attempted（resolver/query/reader outcome及去重键）、lookup预算/停止原因/消耗、resume cursor。没有绑定的身份不能写入verified known；所谓official direct failed必须保存实际失败call ref。

Standard继承来源和已完成工作用于补缺，不继承Lookup发布权；不能重复消费已完成读取预算。Lookup剩余预算为0也不表示Standard没有预算，两档预算分别记账、共享overall deadline由后续生产合同确定。开始Standard前需产品策略允许，自动升档开关、档位切换、取消/恢复和UI提示在生产slice明确，当前不默默改用户所选模式。

验收必须覆盖：已有bound fields→VERIFIED/零Standard调用；provider全挂、不相关、身份冲突、矛盾前提、无gap→SAFE_ABSTAIN/零升档；相关可读未绑定→ESCALATE_STANDARD且handoff完整、已有read不重复；第三例保留真实provider_exhausted且能根据相关性/身份是否核验区别升档候选与安全结束；Standard续研必须找到真实claim-bound支持，否则仍拒绝事实发布。Lookup CLOSED不要求generic publication authority，但必须上述生产路由/持久化/预算/发布门验收完成。当前只冻结合同，Lookup/Standard/Deep仍未关闭。


### 修订后观测门执行

干净head2ed0b6ba0ff84dc92a759183ebb29b4ee3f72a7f，经祖先验证后用原5份未改写公开HTML完成四例，保存routing-contract-result.json；第三例仍provider_exhausted/2读/无采用证据，成功条件仅为相关候选正文确有发现关联读取，不冒充read_backed或请求字段支持。第一二例read_backed/2读，第四例exhausted/3读；四例均abstained/0 refs/0答案模型调用。最终L1 123 PASS/43.67s，Ruff/diff-check PASS，mypy NEW0。旧严格合同失败日志保留；新通过只授予修订的观测合同，不授予三终态生产资格、Standard升档成功或generic发布权。
