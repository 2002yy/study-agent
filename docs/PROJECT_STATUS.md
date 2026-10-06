# Study Agent 当前状态

> **唯一进度入口**
> 更新：2026-10-06
> 产品定义：**Study Agent 是长期保持“正在学什么、已经确认什么、还不会什么、下一步是什么”的个人学习工作台。**

本文件只维护当前权威状态、可复核边界和唯一下一门。2026-10-06 本次收敛前的完整状态原样归档到 [`archive/PROJECT_STATUS_PRE_177_FINAL_REVIEW_2026-10-06.md`](archive/PROJECT_STATUS_PRE_177_FINAL_REVIEW_2026-10-06.md)；更早历史继续由既有 archive 与 Git 历史持有。

## 0. Current Handoff（cold-start 入口）

**#177 最终人工审查修正 / 当前执行权：** PR #177 `codex/lookup-terminal-handoff` 基于 main `d13a338e9d1c78a9077a6ca63ec766a9cd083c2a`。旧审查 head `615f4b1ae1c9b658ded2b493918e029d9de3daa3` 的 exact-head CI #3739 / run `37348909594` 已 `completed/success`，但随后人工最终审查发现两项真实生产阻断，因此该旧绿灯**不得**授权合并。

**本刀修正：**

1. **三终态真实可达性。** 官方 Lookup 在 `official_plan()` 命中时会绕过 semantic recovery；旧 handoff 又只认可 semantic RQ relevance，导致 `ESCALATE_STANDARD` 在真正的官方 fallback 路径不可达。当前合同增加严格的、仅用于**相关性**的 deterministic exact-single-version body proof：要求单一命名版本、真实 target coverage、trusted `web_read`、正文 digest 一致且正文精确包含目标版本。它只能证明“这个可读正文与目标版本相关”，**不能**升级为 claim support，也不能授予 publication authority。相邻版本必须拒绝。
2. **requested-field planner 收紧。** 字段规划改为“只消费确实映射到支持字段的 span”；不再把泛化的“时间/date/现在/更新”吞成 release date。`更新时间`、`当前时间`、下载地址、安装要求等未支持额外 facet 留在 remainder 中，因此整题安全返回未规划，不能误报 `VERIFIED`。
3. **真实生产路径回归。** 测试不再手工替换 `prepared.rag`；由 `resolve_web_tools → WebToolTrace.to_dict() → ChatService.start_turn/complete_turn → SQLite → fresh repository readback` 验证 `VERIFIED / SAFE_ABSTAIN / ESCALATE_STANDARD`、pending handoff、owner、零答案模型调用与 handoff reload。另有邻近版本负控，防止 deterministic relevance 跨版本绑定。
4. **recovery P1 保留。** `web_tools["recovery"]` 继续作为真实持久化 budget/completion authority，handoff 保存为 `lookup_budget`，reload 用同一份 snapshot 重算；`research_recovery` 不需要重新塞回 sanitized calls。

**当前验证身份：** 本文件所在提交即当前候选身份；最终资格只认该 exact head 的新 CI。旧 `615f4b1a` CI 和此前本地 `3624 passed / 6 skipped` 仅作为历史证据，不借给本次最终修正。

**冻结边界：** pending handoff 仍然**不执行 Standard**、不改变用户模式、不授予事实发布权。Standard consumption、跨档总 deadline / tier accounting、run/cursor ownership、exactly-once source reuse、interrupt/resume 仍未实施。Lookup / Standard / Deep overall 均 **NOT CLOSED**。UI 继续独立，不混入研究 PR。

**唯一下一门：** 将本刀压成一个 bounded commit → 只认该 exact-head CI → 最终人工审查。两者通过后按 expected-head 保护合并，并核一次 exact-main；随后另开独立 slice 实施 Standard consumer + source reuse + shared budget + cancel/resume，再进入 Standard 多源／比较／冲突资格验收。

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
