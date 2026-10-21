# studyctl

## GitHub可信采集核心

实时只读入口（需要已登录的`gh`，不会等待CI）：

```powershell
python tools/studyctl.py ci collect --github-repo 2002yy/study-agent --pr 279 --exact-head <40-char-sha> --required-check test --json
python tools/studyctl.py ci main --github-repo 2002yy/study-agent --exact-head <current-main-sha> --required-check test --json
```

`collect`要求正整数PR；`main`只核验当前main及push事件。`--required-check`可重复，表示调用者明示的项目检查要求，不写入服务器保护规则，也不代替服务器要求。两类要求全部满足才可PASS。`--dry-run`不访问网络、不写output，返回BLOCKED/3和计划信息，不制造已采集证据。已有output会在任何网络调用前阻断；正常output仅创建新报告。权限/传输/预算/身份变化等前提不满足返回脱敏BLOCKED/3，明确的required check失败返回FAIL/4。外层head_sha是实际CLI代码提交，内部expected_head_sha才是所检远端SHA。

`tools/studyctl_github.py`可按显式repository、PR/主线SHA和项目检查名称采集当前GitHub证据，CLI入口已接入。固定GitHub host，只读GET/固定GraphQL，不触发或重跑工作流、不自动合并。90秒总预算、每请求最多15秒、最多80请求/每流10页、每响应输出最多2MiB；预算或权限不足阻断，不重试。

采集branch protection、生效rules、check runs/statuses、workflow events及完整review threads/reviews，前后核对PR/head/base/policy。无保护须同时有admin权限和branch unprotected证据；没有任何required check合同不能PASS。项目显式检查与服务器要求分开报告；GitHub Actions检查还绑定suite、event与PR身份。未知附加规则、未解决意见、请求修改、skipped/neutral、旧SHA、分页缺失或采集中状态变化均不能通过。

PASS仅表示采集期间指定SHA的GitHub检查/审阅门通过；不是L3、真实模型质量或合并许可，`merge_authorized=false`。主线必须另采集当前main及push事件。采集不是原子事务；调用方合并时仍须expected-head保护和自身本地/人工验收。保存报告日后只能当历史证据，不能继承live资格。

## CI证据范围（离线核心）

离线入口（不会查询或等待GitHub）：

```powershell
python tools/studyctl.py ci inspect --snapshot <saved-query.json> --github-repo owner/repository --pr 7 --exact-head <40-char-sha> --json
python tools/studyctl.py ci outcomes --receipt <raw-outcomes.json> --exact-head <40-char-sha> --run-id 42 --event pull_request --json
```

inspect支持已保存的prs/checks查询快照，展示历史身份/运行/审阅缺口；outcomes只回放带head/run/event/routing的原始步骤回执。外层head_sha标识实际CLI检出，expected_head_sha是被检查提交，二者不能混用。--output仍拒绝覆盖，--dry-run只读且不写报告。两个命令都不合并或触发工作流；完整live ci verify仍待后续采集required-check策略、全部上下文、当前review以及merge/main证据，不能用这两个离线命令冒充。

## 后续CLI建设范围

Study Agent只读/测试基础、研究目录/诊断/分页/差异已分别有候选；尚未全部合流main。当前CI离线入口后，优先补GitHub可信只读采集和完整exact-head CI/review核验、兄弟片合流和main验收，以及成功/失败/取消等完整真实run记录与原工具一致性验收。已有B5只证明历史摘要能被如实读取。真实研究运行入口是后置片，另需明确预算/授权，仅DeepSeek，不另建调度器。

其余仓库按原合同逐一做局部G0→复用入口→至少三条业务E2E，不把项目已有能力当CLI已验收：LingBot环境/实验与可比性；Vector Breach地图/资产审计与比赛记录；VoxelCombat构建/战斗证据/门报告且保留D的NO-GO；Cardfront状态/测试清单/规则门并遵Grill冻结范围；BallWar正式codec只读存档验证和Android预检，目标4.7。此表为本开发线待接线/验收方向，不宣称其他窗口当前分支的全局状态。

tools/studyctl_ci.py只解析已保存的CI数据，不访问GitHub或等待工作流。inspect_ci_snapshot兼容本地cli-review-fixes-closeout快照结构（prs/checks）：核对仓库URL、PR、40位head、workflow event/head与审阅分页，保留运行状态和证据缺口。该旧格式没有required-check policy/check contexts，也不能证明当前性，因此即使全绿也BLOCKED；明确同head/event的失败可报告FAIL，不借旧head结果。

replay_outcomes复用check_ci_outcomes.failed_steps，判断原始outcome而非continue-on-error后的conclusion，保留pytest_impact替代、frontend/browser路由规则。输入studyctl-ci-outcomes-v1为可选离线回执包装：head_sha/run_id/event/frontend_required/browser_required/steps；steps直接采用CI_STEP_RESULTS的原始字典，不要求改写旧快照或修改CI workflow。回执身份/路由缺失阻断，既有规则判失败为FAIL/4。PASS/0只代表提供的原始outcome满足该门，不证明回执真实性、当前PR状态、必需检查或可合并；merge_authorized始终false。CLI接线在下一独立片。

仓库内执行，无需全局安装：

```powershell
python tools/studyctl.py status --json
python tools/studyctl.py doctor --json
python tools/studyctl.py --help
python tools/studyctl.py --help --json
```

status/doctor只读本地Git与权威文件是否存在，不加载产品、模型或凭据，不联网、不运行测试。status分别统计tracked变化和Git normal模式的未跟踪条目（目录不展开，不能冒充文件总数）。doctor失败为BLOCKED，不代表产品测试失败或通过。

正常命令stdout恰好一个agent-cli-result-v1 JSON；参数错误不回显未知值，Git stderr不直接泄露。退出码：0成功，2参数错误，3前提缺失，4执行/验收失败，5超时/取消。--help默认人类文本，--help --json为机器说明。

--repo可放在子命令前后；显式--output只发布新的报告文件，拒绝覆盖，以同目录临时文件和hard link发布；--dry-run即使指定--output也不写文件。不支持hard link的文件系统保守阻断，不降级为覆盖写入。

## 测试计划（只读，不执行）

审阅修复：--head必须等于目标checkout当前HEAD，避免历史SHA配当前manifest/runner。登记文件在目标root解析，不用CLI自身root验证其他checkout。quick_checks以目标绝对路径运行Ruff，以base/head检查已提交范围，显式包含WIP时另查HEAD到working tree，并列tracked status检查；status需stdout为空才算clean，退出0本身不是洁净证明。Git字面反斜杠路径阻断，不能被路径归一化缩小影响集。

```powershell
python tools/studyctl.py test plan --base <ancestor-sha> --head HEAD --json
python tools/studyctl.py test plan --base <ancestor-sha> --include-working-tree --json
```

复用本CLI检出的ci_scope.classify和stage gate读取/解析器；policy_root明确其来源，不从任意--repo加载Python。提交范围用精确commit与祖先关系校验；rename按删除/新增两边分类。默认排除working tree并显示排除标记，显式include才纳入tracked和未跟踪文件；未提交的门配置必须显式纳入，不能暗中用排除的配置缩小测试。

命名影响集必须已登记、非空且在目标检出存在；输出原runner的argv、测试路径与L0检查，仅计划而不执行。文档/无改动只推荐L0；未知或混合范围没有唯一已登记集时返回PARTIAL/3及scope_review，保持保守扩大，不拼造新影响集。full_scope和l3_eligible不是自动执行L3的许可；L2阶段关闭/L3显式资格仍按AGENTS和原预检执行。带前后空白/换行的异常文件路径阻断，不修剪成已登记路径。

## 受控测试执行

审阅修复：L1/L2默认300秒；L3必须显式--timeout（最多3600秒，例如1800），未提供预算时参数错误且不执行预检。所有事后判定超时/日志超额的路径同样清理进程树；Windows通过私有pipe让bootstrap等待，先纳入带kill-on-close的Job Object再放行命令，避免父进程退出后无法按PID找回后代。Job归属失败则不放行；清理按Job成员数确认，不把父进程已退出当作后代清理完成。正常结束也回收本次Job遗留进程。

```powershell
python tools/studyctl.py test run --impact-set conversation_decision_admission --timeout 120 --json
python tools/studyctl.py test run --level L2 --stage p2-a-retrieval-stack --dry-run --json
python tools/studyctl.py test run --level L3 --timeout 1800 --dry-run --json
```

L1/L2只允许已登记、非空、位于tests内的文件集，复用原run_stage_gate.py，不接受任意shell/pytest透传或任意repo的可执行脚本。L3只能显式选择，先执行原l3_preflight.py，成功后才启动全套pytest；预检失败/总deadline耗尽不启动后续步骤。dry-run只列argv，不执行预检、pytest或创建运行日志。

真实执行会创建独立临时日志/用户目录，子进程只继承OS运行必需变量及CI SHA，不继承提供商凭据、代理或PYTEST_ADDOPTS，设置离线模型环境；根目录或祖先存在.env时阻断，不读取其内容。源码可在L1/L2中含WIP，结果明确记录执行前后tracked/untracked状态，不能把dirty结果冒充精确HEAD资格。该适配器不是网络隔离沙箱，也不替代测试自身的离线/权限合同。

stdout仍一份JSON，子日志转stderr（最多1MiB诊断）并保留原始日志路径；检测1MiB日志阈值超限时停止，磁盘日志可在检测间隔内短暂超过阈值。timeout是全步骤总预算，停止进程树另有最多约10秒清理；取消/超时以退出5报告，cleanup_complete=false时不能假装已确认清理。Windows按自有PID树停止，POSIX用自有进程组。没有自动重试。

子失败映射CLI退出4并保留child_exit_code；L3预检失败为3，取消/超时/日志预算为5。显式output在执行前拒绝已有文件，避免测试已执行才发现不能写结果；输出报告与子日志共同列为artifacts。不提供真实研究或付费调用。

## 研究记录检查（只读离线快照）

已有B5归档的数值差异可以只读比较：

```powershell
python tools/studyctl.py research compare --left-artifact <baseline.json> --right-artifact <current.json> --run b5_active_searxng_smoke --json
```

两边须为同一已支持schema、指定run身份、完全相同的问题和reference_date；问题只用于本地匹配，不输出正文。各计数列出left/right/delta（right-left），任一侧缺失则delta=null，停止码与缺证据提示各自保留，不合成优劣评分。输出两侧artifact SHA256、上下文fingerprint与same_artifact，避免把同一文件当两次实验。该schema缺模型/执行配置身份及完整时间线，结果始终PARTIAL/3，不代表控制变量成立、质量提升或发布许可；不同任务/日期、坏输入等BLOCKED/3。无网络或模型调用。
SQLite事件输出默认最多50条，--event-limit为1～100；has_more/next_event_cursor表示后续页。使用同一database/run与--event-cursor继续读取，游标绑定快照SHA256、run_id和最后sequence；快照变化、跨run或不存在的位置阻断，坏格式为参数错。total_event_count统计整条已校验trace，coverage_scope=whole_recorded_trace，不因当前页没有read/gate/stop事件而判缺证据。分页不写数据库。只有摘要的--artifact输入不接受事件分页选项，也不会生成假时间线。

Git归档诊断也可直接读取，无需重跑研究或重建SQLite：

```powershell
python tools/studyctl.py research inspect --artifact docs/research_quality/B5_ACTIVE_SEARXNG_SMOKE.json --run b5_active_searxng_smoke --json
```

artifact与database必须二选一。当前只支持既有research-quality-b5-active-smoke-v2、最多2MiB；不导入其会发起真实请求的producer，只读现成文件。该版本只在ui_progress保存run_id，producer由同一completed run生成此关联；CLI仅将它用于身份关联，不把UI播报当证据。保存artifact_sha256并原样呈现run状态/停止码及有记录的数值摘要；缺项是null，绝不补0。重复JSON键、非法计数、未知schema、身份不匹配等阻断。question、brief_excerpt、query正文不输出，不从摘要推导新失败原因。无论摘要状态是否completed，缺时间线/引用支持事件都保持PARTIAL/3且events=[]，不捏造trace。

Git主线归档的此样本实际记录partial/evidence_budget_exhausted、7个候选、0次读取、0条eligible evidence；这是既有真实smoke的有限诊断回放，不是本次真实模型质量验收。归档提交cbb6ba0a0ddceb0ac4eb314ab3119b505ab9e099，blob e8b43a243b01051d90e4945d07709790d121638d；生成工具在执行完后删除临时SQLite，主线已查范围未见此smoke的完整数据库，CLI不从摘要重建它。

### 已执行的离线业务样例

在干净提交b054a58c7e37672541a0333c9a3b8892ddf2ea9c上，实际子命令得到以下结果；回执位于D:/study-agent-validation/studyctl-business-examples-20261021/manifest.json，记录argv、实际进程/信封退出码、head及输入SHA256。两个输入文件校验和未变，无SQLite旁文件、真实研究或模型调用。

| 场景 | 实际状态/退出码 | 含义 |
| --- | --- | --- |
| list历史空库 | PASS/0 | 目录可读且明确为空，不代表研究质量通过 |
| list --limit 0 | FAIL/2 | 参数错误，未执行研究 |
| inspect归档但run不存在 | BLOCKED/3 | 身份前提不满足，不解释其他run |
| inspect真实B5归档 | PARTIAL/3 | 可见既有摘要，缺完整事件/引用支持 |
| 无pytest的系统Python执行登记门 | FAIL/4，child_exit_code=1 | 环境执行失败已保留，不能冒充产品测试失败或通过 |

先发现run ID，再检查所需记录：

```powershell
python tools/studyctl.py research list --database <offline-snapshot.sqlite> --limit 20 --json
python tools/studyctl.py research list --database <same-snapshot.sqlite> --cursor <next_cursor> --json
```

list只返回run ID、记录状态、阶段和停止码，不解析问题/答案/来源正文或运行研究。按ID的二进制顺序分页，limit为1～100，next_cursor为空表示结束；游标绑定整个输入文件的SHA256，快照改变则BLOCKED，不能继续拼接两份快照。空目录明确返回runs=[]且无后续页，PASS只表示目录成功读取，不代表存在研究记录或研究通过。输入同样须一致离线快照，不自动连接产品运行库。

审阅修复：即使--repo指向其他检出，外层head_sha仍取实际CLI代码ROOT的提交；requested_repo_head_sha单列用户指定检出的提交，inspection_root显示解释器来源。输入快照SHA256继续独立记录，不把目标仓库版本误写为检查工具版本。

```powershell
python tools/studyctl.py research inspect --run <run-id> --database <offline-snapshot.sqlite> --json
```

必须显式提供由现有数据库备份/导出手段产生的一致离线SQLite快照；本命令不负责备份，不自动查找或连接运行中的产品数据库。拒绝同路径的-wal/-shm/-journal旁文件及超过64MiB的文件，JSON列各限2Mi字符。在内存反序列化后只查询指定run，不打开产品RuntimeDatabase、不执行迁移或恢复，不修改输入或创建SQLite旁文件。结果含输入快照SHA256；外层head_sha是CLI检出版本，不是研究执行版本。大数据库/在线WAL支持后续另片处理。

复用known_research_evidence_ids与load_claim_engine_state校验server-owned证据和research-state-v1。只输出记录状态、停止码及已验证事件，不读取或推断最终答案；搜索、读取、引用支持（链接和gate事件）及停止记录分别标明有记录/证据不足。整条trace出现其他run_id时不归属给当前run。缺字段、旧schema、缺事件、未知停止码为PARTIAL/3；无指定run、坏数据库/JSON、缺必要列等前提错误为BLOCKED/3。CLI PASS/0仅表示所需记录齐全，不证明研究成功、引用正确或允许发布；已失败研究仍可被成功检查。--dry-run可只读检查但不写output；CI查询仍未实现。
