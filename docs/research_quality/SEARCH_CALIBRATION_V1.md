# 搜索调研与校准 v1

本文拥有 §171-A 的任务、计数和失败分类；当前状态、Git/CI、下一执行片由
`docs/PROJECT_STATUS.md` §0/§173 拥有。诊断不授予 qualified judge、release
admission、confirmed memory 或自动扩预算权限。

## 1. 要解决的真实体验

用户说“联网研究 opus5.5 是什么、性能如何、对比”后，应自主搜索并读相关正文；
“直接去”“再查查”继承原题，“赵翠”另起主题。不得把控制词送去查字典，
不得在仍有可执行的有价值路径时要求用户再次授权。

把问题分成五层，逐层定位，不用一个 success 掩盖缺口：

| 层 | 调研问题 | 保存的证据 | 失败后的修复方向 |
| --- | --- | --- | --- |
| 问题理解 | 原实体、版本、比较对象、子问题是否保留？ | episode 原题/hash、intent、RQ、policy | 修复继承/新主题边界 |
| 查询 | 实际发出的 query 是否包含实体与当前缺口？ | query、stage、provider、返回状态 | 短查询、已有官方域线索、精确页面类型 |
| 候选 | 搜到了好页面，却读了镜像/主页/失败域吗？ | 原始候选、排序/拒绝、canonical/locale/host | 修复排序、去重、剩余额度调度 |
| 正文 | 请求 URL 与最终 URL、相关性、截断是否正确？ | 双 URL、时间、内容 SHA、读取/采用分开 | 保留合法重定向，拒绝弱相关正文 |
| 回答 | 原问题各方面有对应回答且引用挂对了吗？ | 完整 answer/SHA、source/RQ、人工缺口 | 补缺口/缩弱断言；不以相关性代替支持 |

## 2. 外部调研依据与本项目取舍

- [Anthropic Research 工程实践](https://www.anthropic.com/engineering/multi-agent-research-system)：
  先宽后窄、观察实际调用轨迹、用小规模真实问题尽早评估；准确性、引用、
  完整性、来源质量和工具效率分开。本文采用这些评估维度，不引入其多 agent
  架构，也不将其他系统的性能数字作为本项目结论。
- [SearXNG Search API](https://docs.searxng.org/dev/search_api.html)：
  `q`、engine/category、language 等参数属于检索接口，`site:` 等语法依赖
  上游引擎。官方域限定必须检查实际返回 URL，不能相信 query 里写过 site。
- 任务锚点的独立入口：[Python 3.14](https://docs.python.org/3.14/whatsnew/3.14.html)、
  [FastAPI yield](https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-with-yield/)、
  [SQLite WAL](https://www.sqlite.org/wal.html)、
  [Flask async](https://flask.palletsprojects.com/en/stable/async-await/)。这些是
  人工核对入口，不直接注入被测 Agent，不能让人工找到页面冒充自主搜索成功。

## 3. 冻结任务与分层验证

`config/research_calibration_v1.json` 固定八题，Lookup/Standard 各四题。
每题两次，共十六次；同一 manifest、隔离线程，串行运行。每题预先定义关键
方面，结果失败后不改题目或将失效案例删除。版本信息以实际读取时间为准。

| 类型 | 控制或任务 | 必须观察 |
| --- | --- | --- |
| 近期/未知实体 | Opus、Python 版本 | 先搜；版本不替换；无证据不宣称不存在 |
| 多轮/长历史 | 原真实 replay | 控制词不做 query；原题/RQ 不被助手改写 |
| locale/redirect/地区失败 | docs → region wall → release | 发布页不饿死；合法最终 URL 保留 |
| 页面不够 | 首页、弱 overlap、版本提及、截断 | 正文相关性与完整支持分开 |
| 可恢复外部失败 | 超时后有备用页面 | 有收益且保留 finalize 时继续 |
| 无证据/全路径失败 | 阻断与无新候选负控 | provider/deadline/candidate/saturation 分开 |
| 多方面/多对象 | 性能、比较、并发/部署限制 | 缺哪方面明确记录；相关不等于 answered |
| 权限/取消/迟到 | history/web deny、cancel/CAS | 无越权、无旧结果写入新 turn |

八类用既有 focused/L2 控制验证；真实八题不是八类故障的全部自然出现样本。
UI/引用与事实支持需要人工诊断，自动模型仅作相关性建议。

## 4. 运行与可追溯数据

使用仓库 `.venv/Scripts/python.exe tools/run_research_calibration.py`，必须明确
`--output` 指向仓库外的新目录。不进 CI，不自动重试整批，不写用户 DB。
runner 记录 manifest/hash、exact head、dirty paths 和 production file digest，
provider/model/endpoint host、开始结束时间、原始调用、正文/hash/读取时间、
推理输出/hash、回答/hash。密钥不进入 artifact。

API 返回的展示 calls 已过滤失败；runner 在 production resolve seam 捕获原始
calls，避免将“展示里没有读取”误判为“根本没有尝试”。

同时记录：候选总数、attempted/successful/adopted reads、canonical 文档与
source family 数、base/recovery slots、跳过/拒绝原因、research/finalize/总时长、
model/writer calls、实际 stop reason。来源数不是独立证据数。

按 tier × recovery 分组，分别报告全部执行和有采用正文执行的 n/p50/p95；
后者叫 read-backed，不能叫 answered/success。八题两次的小样本 p95 仅观察。
问题覆盖与 citation 支持由人工复核另记，不由 target/string 命中推导。

## 5. 本次真实结果与归因

原始 artifact 在 `D:/study-agent-validation/research-calibration-20261004/result.json`。
16/16 执行结束，4/16 有采用正文（Standard Opus、框架比较各两次），Lookup
0/8；没有以此宣称 25% 的事实正确率或总体任务成功率。

| 分组 | n | 有采用正文 | 总时长 p50 / p95 |
| --- | --- | --- | --- |
| Lookup recovery | 8 | 0 | 9.703 / 14.203 秒 |
| Standard recovery | 8 | 4 | 15.953 / 26.781 秒 |

- SearXNG localhost:8080 connection refused，现有 Bing RSS 兜底实际运行；
  DuckDuckGo 最小通道诊断返回 challenge。没有恢复 Docker 或新增 provider。
- 多个不同 query 的 Bing RSS 返回泛 Python/FastAPI/SQLite 主页；市场/语言
  参数的小范围探针没有修好。`site:python.org Python 3.14` 探针能找精确发布页，
  但引擎仍混入域外结果；`site:fastapi.tiangolo.com yield` 仍返回词典。
- Lookup Opus 的官方域 query 发现 docs 和 release；地区重定向占了该阶段
  唯一读取机会，release 未消费，总 cap=3 却只读 1。属于调度违规，不是
  deadline 耗尽，不支持将 hard cap 扩到 75 秒。
- Standard Opus 第一轮仅采用第三方整理文；第二轮取得官方发布页与整理文。
  两次不能视为相同事实质量。框架比较采用多个高度相似的首页/教程，缺少
  Flask 官方异步页；“相关 RQ 都出现”不能验证比较两端证据完整。

## 6. 据结果实施的有界修复

1. 发现来源绑定请求 URL；合法公开重定向的最终 URL 保留。不能通过伪造
   destination 或补造 search result 越过发现/私网边界。
2. 回退正文拒绝 weak overlap；搜索候选的 worth-reading 阈值不作正文准入。
3. 兼容回退仅继承已知控制/引用轮；未知“刚刚发布的豆包”保留新题。广义
   语义仍由 episode interpreter 做，不继续增设主题词规则。
4. 最后 query 阶段使用仍剩余的 hard read slots；非最后阶段仍保留恢复额度。
   canonical/locale/host、chars、deadline/cancel 检查不变。
5. interpreter 规划短 query 与至少一个已有官方域线索；runtime 使用该官方
   query，不对所有厂商套用原始中文问题加 official documentation。
   对有明确版本的官方发现查询只保留域与实体/版本；实测附加 release/date/
   schedule 会退化为主页，原题和 RQ 的时间/性能/比较要求仍原样保留。
6. gateway 对单个正向 site 域检查真实 hostname 与子域；OR/排除式复杂语法
   不自行改语义；域外候选过滤并单独记录计数，不能显示“已查官方”成功。

以上有 deterministic negative controls；仍存在外部搜索质量和问题完整性缺口。
一次网络质量失败不触发全局 host reputation，不扩大 model/read/time cap。

两题修复后定向验收（不扩充分布统计）另存
`D:/study-agent-validation/research-calibration-fix-20261004/result.json`：
Lookup Opus 17.266秒、2次读取/2条采用正文，含官方精确发布页；Python仍0正文，
因为模型规划的 scoped query 加了 release schedule 后又退化为主页。保留该失败；
据独立通道探针对官方版本查询进一步删去填充词，后续仅验证该查询/read seam，
不重跑16次研究或由额外样本重算p95。

## 7. 下一片与关闭标准

完成本片合并后，针对报告中的 FastAPI/SQLite/框架比较缺口做 §171-B：
从已发现页面获得精确文档入口，缺失 RQ 决定剩余查询/候选优先级；按页面
类型区分相关主页与能回答问题的章节，特别保证比较两端都有证据机会。
先在隔离诊断验证，再接生产；不增加 provider，不启用 Deep，不扩 75 秒。

§171-A 仅在八类控制通过、manifest 原样执行、每个可回答锚点关键方面和
引用经复核、剩余缺口有 owner/repro 后关闭。本轮 source availability 差，
不把 fail-closed 误称成功；§171-A calibration remains partial/blocked。


## 第二批：宽 Discovery / 有界 Reader（用户最新授权）

2026-10-04：最新要求以 SearXNG 为 primary，候选不足、低相关、同质或
provider failure 时才用 Bing RSS / DDG HTML rescue；不默认每个 query 都
重复调用三路。与 Kimi 的循环理念一致，但不复制其深度研究量级：
[Kimi 官方介绍](https://www.kimi.com/help/deep-research/deep-research-overview)
描述平均74关键词/206网址，以及依据中间结果调整路径。
[SearXNG Search API](https://docs.searxng.org/dev/search_api.html)
允许查询、category/engine 等控制；引擎成功返回仍须本地相关性筛选。

冻结本批：每 query 最多12候选；Lookup最多2 / Standard最多4 queries
即理论24/48候选机会，URL重复后实际数量可更少，不声称必得30–60。
保留15条未读候选，排序后最多5条进入一次候选语义窗口；未评估尾部
仍需确定性筛选、正文相关性及既有证据门，不因未被窗口选中就丢弃。
Read仍为3/5、chars16k/24k、time30/60s、模型调用≤6。
4–8queries、6–12reads及coverage-driven wave属于后续待实测合同，不在
本批偷偷放宽。各provider统计和晚到结果隔离必须有回归证明。

新manifest：`config/research_calibration_discovery_v1.json`，8题×2。
包括Opus比较、Python/FastAPI/SQLite发布、HTTP重试、原始论文、开源许可、
实时地震；新增分布独立报告，不覆盖旧v1的16次失败。
执行：`tools/run_research_calibration.py --manifest config/research_calibration_discovery_v1.json --output NEW_OUTSIDE_REPO_DIR`。
每题记录provider attempted/results/unique_urls/bodies_read/bodies_adopted，
完整答案、原题/RQ、query/candidate/read轨迹、source SHA/read time、代码摘要。
provider贡献允许重叠，同URL被两路找到不被误计成两份独立证据。
read-backed仍仅来源可用性；问题覆盖和数字支持须读正文逐项人工复核。

部署复核：当前Docker29.8.1与study-agent-searxng容器healthy、8080通；
Python general搜索仍0结果，底层brave限流、DDG/startpage CAPTCHA、
google cse连接失败。不能将健康检查写成搜索恢复PASS。
定向engine探针：bing无结果、wikipedia timeout、github可返回候选。
GitHub搜索成功仅证明特定engine网络通，不授权取代通用搜索。
未改本机secret或服务配置；保留失败事实，不通过切换引擎伪造通过。


## 第三步 steering：adaptive 12→24（实际实施）

当前每query12起步；候选不足/官方来源缺失/单域/Top5偏弱时，后续不同
规划query扩大24。Lookup池上限25，Standard池上限80；上限是容量，不
保证40–80实际unique URLs。正文仍3/5，不提高模型/时间/字符预算。
跨query去tracking/fragment identity合并来源，保留未读候选。
发布意图对release/changelog/download候选加权、教程降权；有官方规划域
时教程不消耗版本问句读取；provider blocked/timeout使用run-local cooldown。
Late worker不写结果；全cooldown返回providers_degraded_for_run，非配置缺失。

四门分别记录：Discovery工程 / Source-quality / Search-answer / Firefly。
当前工程与UI通过，FastAPI/SQLite最新版本和日期未闭合，main NO-GO。
定向发布三题×2：Python2/2有正文，FastAPI0/2、SQLite0/2；数字仅诊断。
SQLite下载页的875字符只有模板说明，版本表格被include_tables=False丢掉。
这是后续Reader/actual-link discovery合同的直接触发证据，不能靠加候选掩盖。
SearXNG360search engine定向可发现SQLite changes/releaselog；不是默认general
恢复通过，也未直接修改服务engine设置。

下一执行片应先冻结“有界结构化正文+实际官方页面链接发现”，保证新链接
来自真实读过HTML、受public/DNS/redirect与同源/预算限制，不伪造search
candidate、不把discovery-only导航页放进答案证据。两题真实Source-quality/
Search-answer通过后，才做有效最终组合L3及main合并。
