# 多窗口工作方向与整合审计（2026-10-11）

这是当前批次的可复用审计快照；唯一长期进度入口仍为 [PROJECT_STATUS](PROJECT_STATUS.md)。核对基线 main `4486e600683003feee5777642d98d16cad50177c`，B-Search `ac78c74a14f3e6b8a2a6bcf151a0b09c7d171d30`，Answer Reliability `c60a0ab1cefe78f44623c329e33061b135d945d4`，原 RP-1 `40e0e311eb9653282ae12b36d4835a3bfa68616b`。后续先检查这几棵树以来的增量，不重扫历史。

## 统一目标与四条证据边界

模型决定问题和检索动作，公共程序骨架治理预算、URL准入、读取、持久化与发布。分开核对：发现候选、读到相关正文、正文支持原题的具体断言、用户学习确认。搜索非空、工具完成、计算正确或UI呈现正常，都不能互相替代这些门。只有学习closure的显式验证链可形成mastery；Deep-4B仍无qualified semantic judge，不能自动发布。

## 各线合理改动与当前处置

| 工作线 / 来源 | 合理作用 | 当前 main 与剩余增量 | 处置 |
| --- | --- | --- | --- |
| Reader / source-quality，#171、#174/#175/#177 | 正文提取、来源权威、字段覆盖、Lookup VERIFIED/SAFE_ABSTAIN/pending ESCALATE_STANDARD | 已有后继生产路由；查到候选不等于答案有支持 | 保留现有权威与支持门，不倒回旧Lookup逻辑 |
| B-Search工具执行，#210 `31cf7993` | 模型选search/feed/follow/read/finish；程序严格URL准入、Reader容量、DoH缓存/检查与连接同IP | 已在main，`safe_http.py`还含比原B分支更新的policy hook与重试重定向处理 | 继续使用main版本；旧文档NOT-main记录已过时，禁止整树覆盖 |
| B自由子问题规划，`codex/model-driven-research-entry` | 保持原题实体/版本/条件，模型提自由子问题，A骨架接管ID/去重/继承/预算 | `model_driven_planning.py`的127行新模块仍不在main；不能把模型选工具误称自由子问题规划已上线 | 与公共执行治理单独资格化；不恢复第二套研究引擎 |
| Provider实验，同B分支 | SearXNG语言可配置、可选Tavily | Tavily79行及SearXNG12/2行增量未迁移；#209已修Bing302与启停。未注册google引擎会回退默认集，不能据google标签归因 | 不加Key、不扩大预算；先验证生效provider与真实具体文章召回，单独可选adapter切片 |
| M4-A/#211、M4-B/#212 | 把B-Search接入Standard/Lookup/Deep作隔离观测 | 已合并；三个BSEARCH_*_SHADOW默认OFF；结果telemetry_only、UNVERIFIED；默认6轮/4搜/3读/20秒 | 可作测量入口，不影响答案、证据、学习或发布；60秒旧矩阵不冒称默认预算 |
| M4-C/#213 `2cab7bbc`、#214 `5155f107` | 同站深页候选排序/可见链路、错误恢复、navigation-family展示去重 | 已合并；raw/filter/shown/confirmed/read链路及10候选显示；原B分支缺少main101行link-discovery后继改动 | 单一下一搜索切片采用冻结Slice-1/Q1合同，不能仅加prompt或扩大候选池就称质量GO |
| Answer Reliability，`codex/answer-verification-shadow` | 逐字quote/hash/span、精确算术、公式来源降级、一次有界修复再验证 | 影子/1B/1C本地完成；计算器与reconciliation等仍是独立未合并增量。1C固定资料样例修正阈值，不证明自然搜索质量 | 不作为通用搜索修复整条合并；保留原资料与封存样本，待检索支持路径稳定后独立port/资格化 |
| UI/#201、#207与旧#164/#176 | 阅读/对话并排、正文/PDF/引用定位、唯一顶部H1、笔记本参考资产 | #201/#207已合并；#215已恢复五份图片/JSON与历史规范，#176参考资产已覆盖。旧Firefly/search-first PR含旧base与重叠实现 | 使用已整合UI；#161/#164/#168/#176暂保留，不自动关PR或导入过时状态 |
| Learning State-1/#203 | 学习事实来源分类与研究/UI持久化隔离 | L1 `0de80751`；新增真实服务/HTTP快照与四写入负控、显式closure正控，精确headCI `38119916006` SUCCESS，merge `4486e600` | 两条P1最终语义审阅通过；学习验收可按该证据收口，非研究质量或自然模型验收 |
| 工作区/#205/#208/#215 | 固定开发MCP、惰性目录/平台契约、保留工作索引 | 已合并；#208契约不授予运行/发布权；#215CI `38119966073` SUCCESS、merge `0eed3a73` | 保留原6文件/26图/11MCP与备份、旧worktrees和refs；main干净不表示其他工作已清空 |
| RP-1证据/#204 | 409原始实验/UI文件与机械证据归档 | 原133哈希误报已审查；CI又发现新增清单158项和工具4项，修复head `bd7c42da5eb5c51c0047aae680c8a55c7ac0b3aa`，exact-head pull_request CI `38122180943` SUCCESS，expected-head merge `7a8b6d5573a202debb1051ecb743aedc5138cbc8` | 必须保持扫描插件/排除/强制门；逐字段重计算清单元数据。提交后完整扫描199项均验证，注入合成AWS格式Key后仅真实告警保留并拒绝通过 |

## 当前已执行与验收

- 已expected-head合并#215、#203、#204并fast-forward主目录，未改研究生产权威。
- #204真实失败原因已修复：元数据只接受从原文件重新计算的manifest/file SHA256、源字段SHA1，工具只接受四个已固定公开Git身份。源报告133项与新增162项重放均无剩余；21过滤/负控+41 CI enforcement共62 PASS，Ruff与差异检查PASS。提交前目录扫描会漏掉未跟踪新文件，现以提交后完整候选扫描为验收；原409字节不改。
- 全量4294 PASS/6 SKIP仍是原组合候选证据。主线生产/frontend/依赖树未改，新增隔离和安全工具分别有定向证据，不为本批文档与普通合并重跑后端全量。
- 旧RP-1 R6、B-Search跨主题到达/读后判断仍NO-GO/PARTIAL，盲审揭盲后的诊断不重新包装为未见资格样本。算术PASS不能提升semantic_support或publication authority。

## 单一下一执行切片

main `4486e600` exact-main push CI `38121690501` SUCCESS；#204已通过新headCI和最终安全审阅并合并，当前main `7a8b6d5573a202debb1051ecb743aedc5138cbc8` 的CI另核对。整理门最终CI与#217文档收口并行；用户已授权启动搜索切片。搜索主线按 [M4-C冻结合同](M4C0_ARCHIVE_AND_SLICE1_CONTRACT.md) 的具体文章到达/有效阅读继续：定位已确认的高相关文章首次在哪个raw→filtered→shown→confirmed→read（读取分开记录eligible / attempted / succeeded）环节丢失；保持原预算与安全门，并按冻结Q1记录是否真正回答原题字段。先复用已有trace与负控，再对实际改动补必要配对真实证据。不要并行导入Tavily、替换规划、Answer Reliability修复、学习UI新功能来掩盖同一失败。涉及对外模型/provider的费用运行另按合同范围执行。
