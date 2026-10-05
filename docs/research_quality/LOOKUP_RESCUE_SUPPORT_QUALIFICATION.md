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
