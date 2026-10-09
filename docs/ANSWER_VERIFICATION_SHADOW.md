# 通用回答核验影子切片（AB2 可复用）

基线：B 线 `40e0e311eb9653282ae12b36d4835a3bfa68616b`。独立工作树 `D:/study-agent-validation/answer-verification-shadow`，分支 `codex/answer-verification-shadow`。

## 使用边界

模型提出引用、变量、表达式和候选结果；服务端提供实际读取快照、现有 Claim—Evidence ledger 和其读取来源关联。检查器只核验明确提供的输入，不从自然语言猜公式、引用区间或研究问题身份，不触碰规划器、UI、模型调用预算或发布门。

`AnswerVerificationInputs` 将服务端的 `documents`、`evidence_rows`、`evidence_reads` 与模型提出的 quotes/calculations/boundaries 分开。适配器只能从已有读取记录构建前者，不能将整个对象从模型或客户端 JSON 反序列化为权威。evidence_reads 是现有 provenance 的只读连接，形状为 `(evidence_id, read_id, content_sha256, payload_sha256)`，不是新证据数据库。

调用 `observe_answer_verification(candidate, inputs)` 取得离线报告；在线使用 `observe_answer_verification_bounded`，复用现有影子资源隔离执行器，调用方等待上限100ms，容量不足/超时返回 UNKNOWN。超时工作没有写入、停止或发布能力。

通用 ChatService 路径通过 `PreparedChatTurn.answer_verification_inputs` 明确选择接入。默认 None 保持原路径；适配器设置该字段后，`complete_turn` 在已有发布和学习判断之后记录 `rag_snapshot.answer_verification_shadow`，仅使用剩余研究时限内的最多100ms。报告绑定原候选 answer_hash；同一报告不能移用到其他答案。字段只记录影子诊断，所有既有发布和学习判断不读取它。

## 三态与限制

- 直接引用：复用 ReadDocument，检查读取身份、URL、可见正文SHA、原始载荷SHA、原文区间、逐字引用；同URL不代表同读取版本。复用 binder 支持强度和 Claim—Evidence 归属检查。
- 转述：不执行逐字相等测试，语义支持保持 UNKNOWN；不能通过相似度自动授予支持。
- 计算：受限 AST 仅接受十进制数字、变量、加减乘除、受限整数幂；Decimal 字面量转为 Fraction 精确运算，无 eval。默认要求精确结果，近似值必须明确小数位和取整方式。
- 临界点：只支持结构上可证明为线性的方程，检查唯一临界点和跨越该点的两侧方向；非线性、不能跨越临界点的探针、不可处理的表达式返回 UNKNOWN。
- PASS 仅表示提供的机械命题匹配。公式对应真实条件、转述含义、引用是否支持主张、整体覆盖率均不能因此变成 VERIFIED。报告固定 semantic_support=UNKNOWN、publication_authority=false、stop_authority=false。
- 缺少引用区间、读取关联或计算提案时报告 UNKNOWN/NOT_OBSERVED，不当作零错误。现有生产回答/binder没有保证提供这些字段，本切片不宣称已自动检查全部自然语言答案。

资源上限：每式512字符/64 AST节点、32变量、数值分子分母各1024 bits、指数绝对值最多8；报告最多32条提案、40份读取文档、每份20万字符、64条ledger/provenance。超出范围不猜测、不修复。

## AB2 的独立性

AB2 可复用同一 API 及通用 ChatService seam。原 AB 的24候选、匿名标签、评分标准、映射和原始响应均冻结；不拿保留题反向调整本模块。

AB2 开始前另行冻结输入、模型、工具、资料、提示词、预算、采样及观察政策。若测量核验器效果，两侧上述条件相同，唯一差异是影子核验启用；结果在独立目录保存，不替换 AB 原答案。不把旧 A/B 的规划差异同时引入后再把收益全部归给核验器。

本切片只记录 would-reject/UNKNOWN。拒绝或修复后的增强系统实验需要独立声明策略；本次没有启用自动拒绝、重试、答案改写、自动发布，也没有运行新的 AB2 模型样本。

## 验证

`answer_verification_shadow` L1 和 `answer-verification-shadow-v1` L2 位于 tests/stage_gates.json。六类公开控制覆盖错引文、跨读取版本、正确转述、错误运算、错误公式不能获语义资格、正确临界值却颠倒两侧；补齐未知、恶意表达式、容量、旧候选、影子超时、默认不启用和持久化不改答案控制。生产语义权限与旧 Evidence Gate 保持原样。

首轮L2中的async流测试在启动事件循环之前已消耗100ms截止窗口，导致prefix偶发缺失。基线与新分支均可用150ms启动延迟复现；仅调整该测试，在运行中的事件循环里开始计时，保留真实超时及迟到token丢弃断言。生产截止实现不变。最终结果由 PROJECT_STATUS Current Handoff 与外部closeout记录。
