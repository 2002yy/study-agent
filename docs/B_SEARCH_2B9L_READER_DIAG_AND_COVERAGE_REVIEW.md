# B-Search-2B9-L：Minecraft Reader 故障定位 + 2B9-K 离线覆盖复核（2026-10-10）

基线 `ab7922f5`（本地）。**本轮无生产代码改动**（诊断 + 离线复核）。
冻结：搜索策略、默认预算、Evidence Gate、RP-1、SSRF、URL 确认均未动。

## A. Minecraft Reader 精确诊断

目标 URL：`https://zh.minecraft.wiki/w/红石中继器`（2B9-J/A-B 轮真实发现）
复现脚本：DoH 解析 → 原始 HTTP → 生产 Reader 链路 ×2。原始输出见本目录 `2b9l_reader_diag.txt`。

| 阶段 | 观测 |
|---|---|
| URL 安全校验 / DoH | 通过；解析得 Cloudflare 公网 IP：`104.26.6.107 / 104.26.7.107 / 172.67.72.106 / 2606:4700:20::…`（0.59 s） |
| 原始 HTTP（直连） | **403**，`text/html; charset=UTF-8`，**gzip，42 340 字节**，无重定向跳转，最终 URL = 原 URL |
| 原始 HTTP（经 7890） | **403**，gzip，42 297 字节（与直连一致） |
| 响应体特征 | `<title>Please wait</title>` → **Cloudflare 机器人挑战页**，不是正文 |
| 生产 Reader `read()` #1 | `ok=False`，`error=security_refused:response_too_large`（final URL 正确，3.0 s） |
| 生产 Reader `read()` #2 | 同上错误码（1.7 s） → **未观察到 `empty_cache_entry` 掩盖**；错误码稳定 |

**失败分类（按要求区分）**：DNS 正常；连接正常；TLS 正常；无超时；**HTTP 状态 = 403（站点侧机器人挑战）**；
响应未超 Reader 上限却被判为「过大」；正文提取未执行。

**结论**
1. **根因在目标站点**：Cloudflare 对本网络返回 403 挑战页，非 DNS/连接/TLS/超时问题，也非 DoH 或 SSRF 拦截。
   因此**不做站点特化绕过**，不改安全传输层。
2. **存在一个确定性缺陷（值得单独最小修复）**：403 挑战页被归为 `security_refused:response_too_large`，
   即「大小限制」错误掩盖了真实的 HTTP 状态。这正是 2B9-L 想验证的「普通异常被合并/误分类」。
   修复方向（下一刀，单独评审）：在读取路径中先判定 HTTP 状态，再判大小；为 4xx/5xx 输出
   `http_<status>`（或 `challenge_page`）这类稳定、可诊断的错误码。本轮**不顺手改**。
3. `article_fetcher._fetch_html_payload()` 把多种异常合并为 `fetch_failed` 的隐患仍成立，本轮未改。

## B. 2B9-K 离线覆盖复核（独立判定，不使用 `assess_body`）

证据：`2b9k_ab.json` 保存的 URL 与正文片段。判定标准：无正文证据不得 SUPPORTED。

### Factorio（问：列车中断的触发/时刻表关系/如何配置）
| 子目标 | 判定 | 依据 |
|---|---|---|
| trigger mechanism | **MISSING** | 无任何正文片段；候选/跟随页中未出现中断条目 |
| schedule relation | **MISSING** | `Train_stop/zh` 片段为「车站用于标识火车停靠的位置…在列车时刻表界面内增加一个可供停靠的地点」→ 讲车站，**不是**中断与时刻表的关系；**词级命中** |
| how to configure | **MISSING** | 同页片段为「可以通过车站界面或信号网络为其设置列车限制」→ 讲车站限制，非中断配置；**词级命中** |

### 围棋（问：提子/打劫/禁止立即重复局面）
| 子目标 | 判定 | 依据 |
|---|---|---|
| liberties and capture | **SUPPORTED** | 「提子的方式就是堵住对方一块棋的最后一口气」 |
| ko rule | **SUPPORTED** | 「禁着手：自杀与打劫…」 |
| no immediate repetition | **SUPPORTED** | 「为了制止无休止地反复提子，**你不能在劫中立刻提回**（一种只提一颗子、会简单恢复上一手前局面的提子）」→ 明确解释禁止立即回提 |

→ 围棋 **3/3 SUPPORTED**：这是本阶段唯一经独立复核成立的完成。

### Python（问：3.15.0 正式发布说明）
| 子目标 | 判定 | 依据 |
|---|---|---|
| release information | **SUPPORTED（简短）** | `python.org/downloads/release/python-3150/`：「version: 3.15.0 release_date: 2026-10-09」 |
| tutorial / download | **MISSING（且属过定义）** | 原问题只问发布说明；这两条由我方冻结清单**加码**，不应作为失败依据 |

### Minecraft（问：红石中继器的延迟档位与锁定机制）
| 子目标 | 判定 | 依据 |
|---|---|---|
| delay tiers | **MISSING** | 片段出自 `红石电路` 页的「负逻辑…优化电路指标（譬如降低体积、延迟、卡顿）」→ 顺带提到「延迟」，**不解释中继器档位**；词级假阳性 |
| locking | **MISSING** | 同页「…漏斗保持锁定状态」→ 讲漏斗，非中继器锁定；词级假阳性 |
| repeater mechanics | **MISSING** | 同页仅**列举**「红石中继器」为传输元件之一 |

→ Minecraft **0/3 SUPPORTED**；且**目标页被 403 挑战页挡住**（见 A），故目标条目**不可读**而非「读到了没覆盖」。

## C. 汇总与门禁

| 任务 | 探索状态（2B9-K） | 独立复核（本轮） |
|---|---|---|
| 围棋 | 3/3 explored | **3/3 SUPPORTED** |
| Python | release explored | **release SUPPORTED**；tutorial/download 过定义 |
| Factorio | 2/3 explored | **0/3 SUPPORTED**（词级假阳性） |
| Minecraft | 3/3 explored | **0/3 SUPPORTED**（词级假阳性 + 目标页 403） |

**要点**：`explored (unverified)` 与 `SUPPORTED` 的区分已被证实必要——Factorio/Minecraft 正是
「词命中但没回答问题」的反例；`assess_body` 仍 **UNQUALIFIED**，`explored` 不获发布权；RP-1 **NO-GO**。

**门禁**：本轮无代码改动，聚焦回归/ruff/mypy 沿用 2B9-K 结果（32 passed、ruff clean、mypy 122/128）。
未 push（本地提交）；PR #209 仍 Open；main、其他 worktree、生产默认预算、Evidence Gate、发布门未动。
