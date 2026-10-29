# Answer-Quality A/B：fallback vs ddg_first（2026-10-30）

对象是 **真实聊天服务**（`POST /chat` 调用的同一组函数），题集是已冻结的
Search-2 十题（`tests/fixtures/provider_routing/search_2_fact_checks_v1.json`）。
本轮只回答一个问题：Search-2 的检索改动，是否让**最终回答**更好。

## 1. 方法

产品里"有引用的回答"是两段式的，本轮按这个真实链路跑：

1. **研究**：`WebLookupService.lookup(query, max_items=8)`——创建并同步执行一个
   ResearchRun，产出 `source_block`（检索 + 读取 + 来源编号）。
2. **回答**：`ChatService.start_turn` + `ChatService.generate`，命令字段与
   `_chat_command` 对 run-backed 轮次一致：`web_context=run.source_block`、
   `web_context_run_id=run.id`、`research_sources=research_sources_snapshot(run)`、
   `answer_validation=research_binding_rows(run)`（有 provenance 时）。

两臂唯一差异是部署开关 `WEB_SEARCH_STRATEGY`（`fallback` / `ddg_first`），
在网关构造前设置，与部署方式相同，并断言网关实际采用的策略。

**刻意排除**（不是遗漏）：

- **Deep 研究档**：`performance_mode=deep` 是另一条管线，且未接入结算准入链，
  在本轮预算内无法受控计费；两臂统一 pin 到 `standard`。
- **聊天内联工具循环**：本轮试过，research 意图的轮次直接确定性拒答（见 §5 缺陷 1），
  18 次请求、¥0.54 未产出任何可评答案。
- **结算准入链**（`STUDY_AGENT_SETTLEMENT_ADMISSION`）：研究解释器没有绑定
  experiment invocation，开启后每次研究调用都被 `send_not_admitted` 拒绝。

## 2. 预算与实际花费

| 项 | 上限 | 实际 |
| --- | ---: | ---: |
| 题量 | 10 × 2 臂 | 10 × 2 |
| 模型请求 | 45（原 40，经批准 +5） | **42** |
| 金额 | 每进程 ≤¥5，两进程 ≤¥10 | **¥2.40**（预留口径，只会 ≥ 实付） |
| 自动重试 | 不允许 | 0 |
| 停止条件 | 任一上限先到即停 | 未触发 |

- 硬约束来自现有 `llm_spend_guard`：发送前预留最坏情况、失败不退款；
  进程上限 ¥5 × 2 臂 = ¥10，与授权一致。
- 发送计数由 harness 持久记录（`answer_ab/sends_state.json`），因为 experiment
  账本在本场景不可用（研究调用无法绑定 experiment）。
- 价格：输入 ¥2.5 / 输出 ¥9.0 每百万 token（沿用已验收配置）。

## 3. 结果（逐题）

`relevance` 是产品自己给来源打的分（`assessment.relevance`），`引用` 是答案里的
`[web-N]` 标记数。

| 题 | fallback：研究/正文/相关度/回答/引用 | ddg_first：研究/正文/相关度/回答/引用 | 人工判读（fallback / ddg） |
| --- | --- | --- | --- |
| B01 星铁 千冶·刃 遗器 | 6.3s / 3154 / 0.10 / 5.1s / 0 | 9.8s / 3145 / 0.10 / 7.3s / 0 | 编造 / 编造 |
| N02 FastAPI 会话 | 9.1s / 9634 / 0.34 / 6.6s / 0 | 8.3s / 6432 / 0.57 / 6.3s / 3 | 正确 / 正确 |
| N05 VACUUM FULL | 9.5s / 5089 / 0.36 / 9.1s / 0 | 7.5s / 3245 / 0.77 / 6.5s / 0 | 正确 / 正确 |
| N07 vLLM release | 10.0s / 7580 / 0.37 / 2.8s / 1 | 12.2s / 4902 / 0.44 / 1.8s / 4 | 正确 / 正确 |
| N09 uv vs pip | 10.4s / 1319 / 0.34 / 4.8s / 0 | 7.6s / 9730 / 0.47 / 8.3s / 14 | 正确（明文用模型记忆）/ 正确 |
| N11 Node LTS | 9.7s / 4652 / 0.42 / 3.5s / 0 | 10.8s / 7230 / 0.73 / 2.4s / 5 | **错误** / 正确 |
| N13 PostgreSQL 版本 | 6.5s / 5100 / 0.37 / 2.8s / 5 | 12.8s / 7269 / 0.61 / 3.1s / 8 | 正确 / 正确（GA 日期不在块内） |
| N16 游戏科学总部 | 4.6s / 820 / 0.10 / 1.3s / 0 | 3.6s / **0** / 0.42 / — / 0 | 正确（证据无关）/ **无答案** |
| N17 诺贝尔物理学奖 | 1.5s / 795 / 0.33 / 2.9s / 0 | 8.5s / 1368 / 0.80 / 2.6s / 0 | 正确（证据无关）/ 正确（片段无正文） |
| N19 SQLite WAL | 5.5s / 5063 / 0.36 / 6.1s / 0 | 13.1s / 9738 / 0.55 / 4.7s / 14 | 正确 / 正确 |

汇总：

| 指标 | fallback | ddg_first |
| --- | ---: | ---: |
| 有答案 | 10/10 | 9/10 |
| 人工判定正确 | 8/10 | 8/10 |
| 编造 | 1（B01） | 1（B01） |
| 事实错误 | 1（N11：`24.11.1`） | 0 |
| 答案含引用 | 2/10 | **6/10** |
| 引用标记总数 | 6 | **48** |
| 来源相关度均值 | 0.34 | **0.55** |
| 研究耗时中位数 | 7.8 s | 9.1 s |
| 回答耗时中位数 | 4.1 s | 4.7 s |

## 4. 关键判断

1. **检索优势确实传到了答案层**：ddg_first 的来源相关度均值 0.34 → 0.55，
   引用从 6 个标到 48 个、含引用的答案 2/10 → 6/10。N11 是直接收益：
   fallback 给出证据里不存在的 `24.11.1`，ddg_first 给出块内的 `24.11.0`（Krypton）。
2. **正确率没有提升，因为两个模型错误都不是检索能修的**：B01 两臂都编造
   （检索到的是"星"字字典页，模型仍按记忆写配装）；fallback 的 N11 是模型
   在没有支持证据时补了个补丁号。
3. **代价是 1 道题丢失**：ddg_first 的 N16 研究阶段返回 `completed` 但
   `source_block` 为 0 字符，回答阶段按设计跳过——用户拿不到答案。
   这比"慢 1.3 秒"严重得多，见缺陷 2。
4. **引用是涌现的，不是契约**：ddg 的引用多，是因为证据块更相关；产品没有
   "事实必须带 `[web-N]`"的强制要求，所以 fallback 的 N05/N02/N19 写了大段
   正确内容却一个来源都没标。

## 5. 发现的产品缺陷（按优先级）

**P1-A｜research 意图的聊天轮次永远不会回答，即使工具已读到正文。**
证据：`fallback_20261030T011732.json`、`ddg_first_20261030T012159.json` 共 6 轮，
`answer_generation_calls=0`，回答都是固定句"本次尚未取得能逐事实支持所问内容的记录…"，
但同一轮 `web_read` 成功了 1–4 次（B01/N02 为候选页，N05 读到 4 页）。
根因：`answer_validation_active()` 对 `task_intent=="research"` 恒为真，而
`prepared.answer_validation` 只能由 `_chat_command` 从 ResearchRun 注入；
内联工具循环没有 provenance 行，于是 `generate()` 直接走确定性拒答分支。
影响：用户明确说"研究"却拿到"没有记录"，且这 6 轮花了 ¥0.54。

**P1-B｜`completed` 但正文为空的研究任务不报错。**
证据：ddg_first N16，`status=completed`、`stop_reason` 非空、`source_block_chars=0`。
下游按"没有证据"跳过回答，用户只看到空结果。空正文应至少是 `partial` 并带原因。

**P2｜run-backed 回答没有发布校验，答案可以超出证据。**
证据：`research_run_provenance()` 对 `lookup()` 产生的 run 返回空，
`answer_validation` 因此为 `None`，`answer_validation_active()` 为假；
B01 两臂、fallback N09（自称"基于我已有的知识"）、fallback N17（自称"无法访问实时网络"）
都在这条无校验路径上回答了。这不是检索问题，是发布资格问题。

**P2｜引用密度无契约。** 同上：是否标 `[web-N]` 取决于模型心情，
同一产品里 2/10 与 6/10 的差别不该由提示词偶然决定。

## 6. 结论

- Search-2 的 DDG-first 改动**在生产聊天链路上是正收益**：证据相关度、引用、
  版本类正确性都变好，延迟多约 1.3 s。
- 它**没有**解决"证据不足时模型照写"这个更靠前的问题，也没有解决
  "research 意图轮次不给答案"这个更靠前的缺陷。
- 下一步不该再调检索权重，而应处理 §5 的 P1-A / P1-B：这两条都在用户可见的
  主路径上，且都能用静态负控覆盖。

## 7. 复现

```
python tools/run_answer_quality_ab.py --plan
python tools/run_answer_quality_ab.py --validate-budget --check-wiring
python tools/run_answer_quality_ab.py --arm fallback  --live --confirm ANSWER-AB-PAID
python tools/run_answer_quality_ab.py --arm ddg_first --live --confirm ANSWER-AB-PAID
```

`--live` 需要显式价格、`LLM_SPEND_CAP_CNY ≤ 5`、不设置
`LLM_SPEND_EXPERIMENT_ID`、不开启 `STUDY_AGENT_SETTLEMENT_ADMISSION`，
并带固定确认串；缺一项就拒绝运行。原始证据（每题的研究正文与答案）在
`docs/research_quality/answer_ab/`。
