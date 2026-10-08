# RP-1 R6b：研究资格诊断与小修复合同

2026-10-08，来源：用户 R6a→R6b→R6c 执行裁定。
**合同已登记；R6b 未实施 / NOT CLOSED。** 与已关闭的 R6a 展示适配修复分开。
不是 RP-1 PR、资格批准或发布权限。

## 恢复点与范围

- B线 `codex/reading-notebook-ui`；R1–R5恢复点 `4c36b935`，R6真实诊断
  `b979b7aa`，R6a本地修复 `ff8b87ca2fb1b10a11314caa96716e2508df08bc`。
- 已观察新main `f35b13b78498f1e7ce2ad678bf6687bd85fb220a`；本刀不复制工作台
  文件、不重做UI、不推送RP PR。R6c封板后基于届时最新main比较RP增量。
- Lookup/Standard/Deep 当前冻结预算、模型调用配额、fail-closed 与发布权限不变。
  不强制task路由、不写ESCALATE状态、不制造gap或Deep child。
- 第一次迭代只有两个独立子切片：身份提取/规范化与语义协议。各自产生可审查
  commit和证据，不混成“放宽验证”。展示层使用R6a，避免同时修改UI/引擎。

## B1：支持域身份资格

入口：S3/S5原始durable记录，`r6-batch-1/S3-durable.json`、`S5-durable.json`。
现有首次阻断：非空、hash有效的正文将project/version分开写，
`target_identity_pattern`要求相邻实体和版本，故未取得verified relevance。

已知owner：`src/web/research/official_resolver.py`、`src/web/research_recovery.py`、
`src/web/research/lookup_terminal.py`；调用边界为`standard_continuation.py`。

实施前建立逐项可复核表：请求实体、请求版本、允许的规范化、来源URL、HTTP transport
digest、读取content digest、解析字段值/原始span或JSON路径、来源身份与完整性验证。
区分官方结构化记录与任意正文，不把字段拼在一起便视为可信。只在可证明的解析/序列化
或规范化缺陷位置修复，或用已经受验证的结构化身份关联建立relevance-only适配。

不得改变：

- 原始版本约束，尤其不同minor/non-zero patch不能混同；已有明确canonical alias
  只按冻结规则采用。请求域未支持的facet不能被删除或由已取得字段反推。
- 来源span/值/内容hash/transport关联；伪造字段、错URL、错owner、缺失或不一致
  hash、错误版本、相似字符串均不合格。没有可靠来源身份就保持abstain。
- relevance不授予claim support；未支持字段保持gap；FastAPI包上传日期不冒充发布日期。
  仍须Lookup正常终态、预算事实可验证、许可与其他现有资格门。

验收：真实原始记录的只读重放证明身份关联与来源一致；错误实体/版本/alias/span/hash/
URL/ownership负控拒绝。修复影响集涵盖提取、Lookup terminal、Standard admission和绑定
投影。引擎未改变全局资格含义时执行L1/L2；触发AGENTS.md强制L3条件则升级。

## B2：搜索前语义协议

入口：S2 `question_identity`，S4 `invalid_rows`；run.stop_reason为
chat_tool_loop_failed，没有搜索调用。最终字段计划缺失不覆盖这个更早执行失败。

已知owner：`src/web/semantic_recovery.py`与`src/tools/persistent_web_agent.py`。
现有记录不足以区分空questions与重复ID，或_rows拒绝的具体分支，不猜测模型能力/网络
故障/预算耗尽。先保存受限、去凭据的原始模型响应、请求schema/任务身份、解析阶段、
拒绝路径与实际调用计量，并按同一task/run关联；观测不改变决策或资源上限。

可修复范围：已证实的协议不一致、确定可恢复的格式问题、服务器适配缺陷。
保留原始输入hash；纠错后的对象必须通过原有严格schema和身份校验；在当前预算内
执行，不增加隐式循环或调用额度。错误实体/重复问题ID/丢失原问题/非法rows/未知intent/
额外权威字段仍fail-closed。不得删除question_identity、随意丢弃问题、伪造非空RQ，
或把planner/execution failure改成Deep可升级缺口。

验收：原始失败响应可重放、拒绝分支可区分；合法协议成功且负控仍拒绝。
若真实模型仍输出不可靠对象，诚实保持失败，给出响应与阶段trace，不绕过校验。

## R6c门（本合同不宣告通过）

先分别关闭B1/B2且固定生产候选，再预登记两个独立集合：

1. 回归集：S1–S5查询原样，各重新运行一次，使用真实提供商/运行时，不改任务措辞
   或插入升级结果。比较已识别缺陷，不把旧SQLite重放算作真实重跑。
2. 新资格集：执行前锁定样本数、查询与域；固定停止点，不无限追加，至少争取一条
   自然Lookup→Standard→后台Deep→terminal→audited-not-approved的完整lineage及真实
   Deep运行期间的持久恢复。未满足触发资格不得强迫进入Deep；失败保持NO-GO。

记录task_intent、requested_fields、每层终态/首次阻断、真实预算消耗与未观测项。
恢复必须保持原child身份、版本、parent与审计，不新建替代child；旧SSE不能覆盖较新
快照或使终态复活。

TTFP记录真实研究进度可见；TTUV同时记录服务端发布条件成立和**对应合格内容片段**
首次可见时间/片段证据，避免仅观察正文容器、提示、首token或被遮挡区域。
S1已有机械VERIFIED但之前TTUV测量不足，不能因此推断响应慢。
Deep audited候选没有发布权威，不能计为TTUV；没有合格片段观测则NOT_OBSERVED。
Terminal latency取持久终态，并标采样/时钟误差。

R6c通过后才运行RP整阶段候选门/独立review/最新main差异核对，并进入bounded RP PR
及exact-head CI；当前不启动这些远端门。
