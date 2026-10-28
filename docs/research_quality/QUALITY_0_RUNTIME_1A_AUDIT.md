# Quality-0 Runtime-1A：只读审计与最小接线方案

> 状态：**只读审计，未发送任何模型或搜索请求，未修改任何生产代码。**
> 基线：`main` = `53da5509`（#302 合并提交）。
> 目的：在写运行器之前，先证明「四臂可以公平、可解释、可硬停地跑」，并给出最小改动范围。

## 1. 结论摘要

| 结论 | 依据 |
| --- | --- |
| 真实用户轮次有一个明确的 HTTP 入口，运行器不需要重造聊天链路 | `POST /chat/stream`（`src/api/routes/chat_routes.py:121`） |
| 每次模型发送只有一个收口点，发送计数与费用都从这里来 | `src/llm_client.py:472` 的 `reserve_call(...)` |
| E2 目前**只有离线回放实现**，生产检索是「顺序回退」而非「合并重排」 | `tools/run_provider_routing_replay.py:198` vs `src/web/tool_gateway.py:313` |
| 检索有一个干净的注入点，可以不改产品默认行为 | `WebLookupService(repository, gateway=...)`（`src/application/web_lookup_service.py:462`）+ `ResearchWebGateway`（`src/web/research_gateway.py:17`） |
| **FILE-02 的 CSV 附件当前会被产品拒绝** | `SESSION_ATTACHMENT_EXTENSIONS`（`src/domain/runtime_entities.py:20`）不含 `.csv` |
| 「每轮最多 4 次发送」缺少执行前硬停机制，现有 guard 只按金额 | `src/llm_spend_guard.py:778` 只检查现金上限 |

前三项让运行器可以做薄；第四项让 candidate 可以最小接线；**第五项是必须先解决的阻塞**；第六项是本轮最需要设计决策的缺口。

## 2. 真实调用链（current 臂）

```text
POST /sessions/new                    → 建会话（thread）
POST /sessions/{id}/attachments       → 上传固定资产（仅 FILE 题）
POST /chat/stream                     → 一轮用户输入（SSE）
  └ ChatService.start_turn            src/application/chat_service.py:540
       ├ 路由/准备（可能触发研究）
       └ spend_scope(...)             src/application/chat_service.py:1150
  └ ChatService.stream/generate       src/application/chat_service.py:985
       └ llm_client._build_request_kwargs
            └ reserve_call(...)       src/llm_client.py:472
GET /chat/turns/{turn_id}/status      → 终止状态与 assistant_message
```

要点：

- **一轮 ≠ 一次模型调用。** 研究型轮次会多次调用（计划、改写、综合、校验），这正是「45 次发送」按调用计而不是按轮次计的原因。
- 会话上下文由 `thread_id` 承载，天然满足「臂内连续、跨臂不共享」——**但前提是四臂各自使用独立会话**。
- 附件在 `_chat_command()` 里做会话归属校验（`chat_routes.py:762`），所以不能跨会话复用 attachment id。

## 3. E2 现状：回放有，生产没有

回放实现（`tools/run_provider_routing_replay.py`）：

- `capture()`（:128）一次抓取 bing + ddg 的结果并落盘；
- `_dedupe()`（:99）按 URL 去重；
- `_rank()`（:198）用生产同源的 `assess_sources()`（`src/web/source_assessment.py:116`）算相关性并排序；
- `replay()`（:324）在离线数据上比较 E0/E1/E2/E3。

生产实现（`src/web/tool_gateway.py:313` `_search_single`）：

```text
searxng（若启用）
  → 有结果就返回
  → 否则 bing（:373）
  → 仍无结果才 ddg（:384）
```

即**顺序回退，不合并、不重排**。所以：

- E2 的算法组件（去重、`assess_sources` 重排）已存在且可复用；
- 但「同时查询两个提供商并合并」这条路径在生产里不存在；
- **不能把离线 E2 结果说成已上线能力**。candidate 必须是一次真实的新路径。

## 4. candidate 最小接线：三个选项

| 选项 | 做法 | 风险 | 评价 |
| --- | --- | --- | --- |
| **A. 网关策略参数** | `GeneralWebGateway(search_strategy="merge_rank")`，`_search_single` 内按策略分流；默认 `fallback` | 需要在 `_search_single` 里加一个分支；两套策略共享同一批 provider 函数 | **推荐**：改动最小、可单测、默认值不变 |
| B. 新网关子类 | `MergeRankWebGateway(ResearchWebGateway)` 覆盖 `search()` | 与 `read()`、warnings、GitHub 直连逻辑要重复处理 | 可行但重复代码多 |
| C. 运行器侧猴子补丁 | 运行器直接替换方法 | 无法单测、容易漂移、可能污染 current | 拒绝 |

**推荐 A 的关键约束：**

1. 策略由**显式构造参数**决定，不用全局 env 决定行为（env 只作为组装层的输入，见 §5 的进程隔离）；
2. 默认值必须是 `fallback`，即 `current` 与今天完全一致；
3. merge 只合并**同一查询**的 bing + ddg 结果，不新增查询、不改写查询；
4. 重排只用 `assess_sources()` 的 `relevance`，排序稳定（同分保持原顺序）；
5. 必须写 trace：`{"strategy": "merge_rank", "providers": ["bing","ddg"], "merged_count": N, "duplicate_count": M, "ranked_urls": [...top5]}`，供 §10 的「证明真的执行了 E2」；
6. 不引入 E3 门控、不引入 QP-1B 查询计划。

## 5. 隔离：一臂一进程，一会话一任务

| 层级 | 做法 | 为什么 |
| --- | --- | --- |
| 臂 | **每臂独立进程**（独立 `LLM_SPEND_CAP_CNY`、独立配置、独立会话） | 环境变量是进程级的；同进程跑四臂无法证明配置不泄漏 |
| 会话 | 每题每臂一条新会话 | 上下文连续性按臂计算，跨臂共享会话会污染答案 |
| 账本 | **四臂共用一份** `LLM_SPEND_LEDGER_DB` + 同一 `LLM_SPEND_EXPERIMENT_ID` | 45 次 / 10 元是**整场**上限，分账本就可以绕过 |
| 归属 | 每次发送带 `run_id`（臂 + 题 + 轮次） | 事后按臂/按轮次归因 |

`model_direct` 也走独立进程，但**不使用** `WebLookupService`：直接 `llm_client.chat()`，并在记录里写 `research_used=false`。

`chatgpt` 臂由人工执行，运行器只做**导入**：读入人工保存的回答文本 + 时间戳，计算内容哈希，写入同一结果目录；运行器不得生成任何文本。

## 6. 发送计数与费用：收口点已存在，缺「每轮硬停」

**已有：**

- `reserve_call()`（`src/llm_spend_guard.py:778`）在请求发出前预留，覆盖 SDK 重试次数；
- 两道金额上限：进程 `LLM_SPEND_CAP_CNY` 与实验 `LLM_SPEND_EXPERIMENT_CAP_CNY`（`experiment_cap_cny()`，:632），两者都不设时**不限费**（这就是 #302 增加有效上限检查的原因）；
- 持久账本可用 `experiment_spend()`（:913）读取，且**设计上不可重置**。

**缺口：** guard 只按金额拒绝，不按发送次数拒绝。

- 「本臂最多 20 次」「本轮最多 4 次」如果只在运行器里事后统计，就可能在一次轮次内超发；
- 单纯依赖金额也不能保证次数：便宜的调用可以一直在额度内。

**方案对比：**

| 方案 | 做法 | 代价 |
| --- | --- | --- |
| **S1. 每轮收紧进程金额上限** | 每轮开始前把 `LLM_SPEND_CAP_CNY` 设为 `已花费 + 4 × 单次最坏预留` | 不改代码，但「单次最坏预留」是估算；估大→可能提前停（安全但截断），估小→可能多发一次（不安全） |
| **S2. guard 增加发送次数上限** | `reserve_call` 增加持久计数，超过 `LLM_SPEND_MAX_SENDS` 拒绝；每轮上限由运行器通过显式 API 设置 | 需要改 `llm_spend_guard.py`，但**精确**、可测、默认关闭 |
| S3. 运行器包一层客户端 | 包 `llm_client.chat` 计数 | 会有绕过路径（其他地方直接调 SDK），不可信 |

**推荐 S2**，并明确它只提供两条新能力：

1. `LLM_SPEND_MAX_SENDS`（整场，实验级持久计数；预留即计数，不退款）；
2. 运行器可设置的**轮次发送额度**（进程内，一轮结束即失效；不设则不限）。

这样「累计 45」「每轮 4」「本臂 20」三层都是**发送前拒绝**，且中断后重跑不能绕过（账本不重置）。

## 7. 阻塞项：FILE-02 的 CSV 附件不被支持

`SESSION_ATTACHMENT_EXTENSIONS`（`src/domain/runtime_entities.py:20`）为：

```text
.md .markdown .txt .pdf .docx  +  .jpg .jpeg .png .gif .webp
```

**没有 `.csv`。** 上传会在 `session_attachment_service.py:121` 直接 `Unsupported attachment type: .csv`。

影响：FILE-02 在四臂上都无法上传，要么退化成「文字描述附件」（四臂都拿不到同一字节，违反公平性），要么该题只能跳过。

三个选项：

| 选项 | 说明 | 影响面 |
| --- | --- | --- |
| **F1. 固定资产改为 `.txt`**（内容仍是 CSV 文本） | 题集只改 `assets[].path` 与哈希，题目文案保持「附一份数据表」 | 只动 Quality-0 fixture，需要**显式重冻结**（新版本文件，旧版本保留） |
| F2. 产品支持 `.csv` | 扩展附件白名单 + 加载器 + 测试 | 产品变更，需要独立切片与自己的验收 |
| F3. 跳过 FILE-02 | 预演变 3 题 | 与 owner 指定的 4 题不符 |

**建议 F1**：它不改变被测能力（读表、算分类计数、发现异常值），也不扩大产品面。但这是**冻结资产变更**，必须由 owner 确认后另开一个小 PR，本次审计不擅自修改。

## 8. 结果持久化合同（草案）

```text
docs/research_quality/quality0_runs/<run_id>/
  manifest.json          # run_id, head_sha, started_at, tasks[], assets{path:sha256},
                         # arms[{id,execution,model,sends,budget}], experiment_id,
                         # strategy="fallback|merge_rank", ledger_path
  arms/<arm>/<task>/
    request.json         # 实际发送的 prompt / 附件引用 / 会话 id
    reply.md             # 原始回答（不加工）
    trace.json           # 发送次数、搜索调用、provider 明细、耗时、费用、错误
    status.json          # ok | failed | cancelled（失败保留，不补齐）
  chatgpt/<task>/reply.md  # 人工导入
```

约束：

- 每份 `trace.json` 至少含 `model_sends`、`search_calls`、`latency_ms`、`cost_cny`、`failure_reason`；
- `reply.md` 写入后**不再修改**；重跑产生新 `run_id`，不覆盖旧目录；
- 评分继续用 `tools/run_quality_0.py`，**运行器不参与打分**（保持「运行」与「评分」分离）。

## 9. 四臂的定义差异（只允许这一处不同）

| 臂 | 检索 | 模型/温度/提示词 | 研究流水线 |
| --- | --- | --- | --- |
| `current` | 生产顺序回退 | 生产默认 | 完整 |
| `candidate` | **merge_rank（E2）** | **与 current 完全相同** | 完整 |
| `model_direct` | 无 | 同一基础模型 | **无** |
| `chatgpt` | 人工 | 人工 | 人工 |

验收时要能自动比对：`current` 与 `candidate` 的 `manifest` 中除 `strategy` 与检索 trace 外的字段必须完全一致。

## 10. 「真的执行了 E2」如何证明

只看配置名不够。每条检索 trace 必须能证明：

1. `providers_attempted` 同时包含 `bing` 与 `ddg`；
2. `merged_count > max(单提供商结果数)`（确实合并了两边）；
3. `duplicate_count > 0` 或 `merged_count` 等于两边并集（证明做了去重）；
4. `ranked_urls` 与合并前的顺序**不同**，或明确记录 `reorder_changed=false`（若 `assess_sources` 给出同分）；
5. 记录 `relevance` 分布（Routing-1 已知：0.33–0.41 区间偏平，所以「排序几乎没变」是正常且必须如实报告的结果）。

## 11. 最小改动清单（Runtime-1B 预估）

| 文件 | 改动 | 规模 |
| --- | --- | --- |
| `src/web/tool_gateway.py` | `search_strategy` 构造参数 + `_search_single` 分流 + merge/rank 分支 | 中 |
| `src/web/merge_rank.py`（新） | 去重 + `assess_sources` 重排 + trace 组装（从回放工具提取，不复制评测规则） | 小 |
| `src/llm_spend_guard.py` | 发送次数上限（实验级持久 + 轮次级进程内），默认关闭 | 中 |
| `tools/run_quality_0_runtime.py`（新） | 四臂编排、每轮计数、结果落盘、预算硬停 | 大 |
| `tests/test_quality_0_runtime.py`（新） | fake model / fake search 的离线端到端 | 大 |
| `tests/fixtures/quality_0/preview_v1.json` | 增加 `strategy` 与 `ledger` 字段（不改预算） | 小 |
| `docs/research_quality/QUALITY_0_PREVIEW.md` | 补运行器操作说明 | 小 |

**不改**：生产默认路由、`run_quality_0.py` 评分逻辑、`preview` 的 45/10 预算、任何前端代码。

## 12. Runtime-1B / 1C 的验收

- **1B（静态）**：fake model + fake search，四臂各跑 5 轮；断言 current 与 candidate 配置只差检索策略；断言五次调用里每轮 ≤4；断言超限时在发送前中止；断言失败轮次不被补齐；断言 `reply.md` 不可被重写。
- **1C（真实调用前）**：E2 trace 五项证明；附件哈希一致；中断后重跑不绕过账本；汇总输出能区分「失败」与「零分」。

**本阶段不得发起任何真实付费调用。**

## 13. 需要 owner 决定的两件事

1. **FILE-02 的附件类型**：选 F1（改 `.txt` 并重冻结）、F2（产品支持 CSV）、还是 F3（跳过）？
2. **发送次数上限的实现位置**：选 S2（guard 内精确计数，默认关闭）还是 S1（每轮收紧金额上限，不改代码）？

在 1 决定之前，运行器即使写完也无法完整跑四题；在 2 决定之前，无法宣称「每轮 4 次」是硬约束。
