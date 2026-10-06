# Study Agent 当前状态

> **唯一进度入口**
> 更新：2026-10-06
> 产品定义：**Study Agent 是长期保持“正在学什么、已经确认什么、还不会什么、下一步是什么”的个人学习工作台。**

本文件只维护当前权威状态、可复核边界和唯一下一门。2026-10-06 本次收敛前的完整状态原样归档到 [`archive/PROJECT_STATUS_PRE_177_FINAL_REVIEW_2026-10-06.md`](archive/PROJECT_STATUS_PRE_177_FINAL_REVIEW_2026-10-06.md)；更早历史继续由既有 archive 与 Git 历史持有。

## 0. Current Handoff（cold-start 入口）

**当前执行权：Standard-2 持久化计划与可恢复循环候选验证。** #178 已 CLOSED：最终 head `978708602de57da39c71a1c5d21bcabc1e5655f2`，本地 clean-head L3 `3719 passed / 6 skipped / 1129.63s`，preflight PASS；exact-head PR fast CI `37448530911` success。最终本地静态审查没有 blocker；远端 threads / formal reviews 均为 0，不冒充远端批准。

**合并：** 按 expected-head `97870860` squash merge；main `eb139900a77f91f6f16c4b1ad69589b0f18d3d4a`，exact-main push CI `37464024389` completed / success。本轮已核对，不重复旧候选 L3。

**已合范围：** durable child run、SQLite dispatch journal、single operation lease、reserve-before-network、持久化计费／cursor／deadline、Lookup 和完成结果复用、unknown 禁止自动重发、取消／接管 fencing、旧 executor／late result 拒绝、受限 provider worker。它不拥有研究规划、事实绑定、冲突裁决、自动续研或发布权。

**原 RQ1-C 事件：** 未冻结 clean HEAD 的旧 L3 出现两个资格前置失败；不是产品回归。它不计 PASS。新基线 `f55738bd` 上的 `97870860` clean-head L3 已通过，生产文件相对 `c974c61c` 没有变化。#179 已合并，新基线 exact-main CI `37444357260` success。

**交接施工位置：** 独立 worktree `D:/study-agent-validation/standard-2-research-loop`，分支 `codex/standard-2-research-loop`，base `eb139900`。合同见 [`STANDARD_2_CONTRACT.md`](STANDARD_2_CONTRACT.md)。当前实现：一次有记录的模型规划、严格计划校验与摘要、复用优先队列、搜索结果插入读取队列、观察与 cursor 原子保存、跨进程恢复、取消／deadline 的诊断完成结果。执行与计费仍只认既有 SQLite journal；所有 gap 保持 unresolved / NOT_EVALUATED，publication_authority=false。

**候选证据：** `standard_research_loop` 命名影响集 351 passed / 161.23s；旧执行基础 focused 50 passed。负控覆盖 planner 越权／篡改、未知 dispatch 禁止重发、旧 token fencing、独立 Python 进程恢复、保存观察前崩溃、取消与 deadline。mypy no-new-errors PASS（current 122 / baseline 128），Ruff、格式与 diff check PASS。生产候选 `02747a42d4671401c14751410720a05ec6fd7378` clean，preflight PASS；其全量回归运行至约 38% 后按用户新的阶段门停止，**INTERRUPTED，不计 PASS，不自动重跑**。外部日志与候选 SHA 记录保存在 `D:/study-agent-validation/standard-2-{impact,mypy,l3}.log` 和 `standard-2-candidate.json`，不将临时证据混入生产 diff。

**测试门覆盖（用户 2026-10-06 最新明确指示）：** Standard 整个阶段完成后才跑一次完整 L3；Standard-2 / Standard-3 / Standard-4 slice 期间只跑 L0、命名 L1 impact set 与相应 L2 stage integration。该明确指示优先于旧 early-L3 默认触发规则；不能因每个 slice 涉及持久化／authority 再各跑全量。仍保留 exact-head CI、最终审查和 expected-head merge 门。

**本机主 worktree：** `C:/Users/Zhang/Desktop/study agent` 位于 main，但 `.mcp.json`、`docs/PROJECT_STATUS.md`、`frontend/package.json`、`frontend/package-lock.json` 有既存修改，本轮保留原样，不用远端 main 覆盖。

**新路线（用户 2026-10-06 冻结）：**

1. Standard-2：持久化研究计划 + 可恢复执行循环，只负责去哪找、怎么继续、何时停止，输出研究结果 artifact。
2. Standard-3：逐事实证据绑定、来源身份、冲突处理与 publication gate。
3. Standard-4：ChatService 的 Lookup → Standard 自动 continuation；此前不自动接线。
4. Deep：多轮重写、Evidence Gain、saturation、长预算与 interruption/resume；UI 继续独立后置。

**唯一下一门：** Standard-2 最终审查／独立 PR／exact-head fast CI；然后独立 Standard-3 事实绑定 slice。完整 L3 留到 Standard 总验收。验证机器、事实绑定、自动续研、Deep、UI 不扩入本批。Lookup / Standard / Deep overall 均 **NOT CLOSED**。

## 0A. 冻结研究路线

```text
Lookup
  → VERIFIED / SAFE_ABSTAIN / pending ESCALATE_STANDARD
Standard
  → 多源补全 / 双方比较 / 冲突处理（尚未接入自动消费）
Deep
  → plan / gap / Evidence Gain / saturation / interruption-resume（后置）
```

共享原则：**模型决定“去哪找、找什么”；程序决定“你到底找到了什么”。** `usable/read_backed/relevant` 不等于 claim support；claim support 不等于 publication authority。

## 0B. 仓库与施工纪律

- 一个 feature slice 尽量整块完成、一次验证、少提交；只在阶段门需要权威 exact-head 证据时触发 CI。
- push/PR 之后只认当前 exact head；旧 HEAD 绿灯不能替代新 HEAD。
- 生产候选只有在 CI、最终审查与 expected-head 一致时才允许合并；merge 与 CLOSED 是不同门。
- UI、研究与其他项目保持独立 bounded slice，禁止为赶门把无关改动混入。
