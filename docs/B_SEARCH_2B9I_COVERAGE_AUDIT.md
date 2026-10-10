# B-Search-2B9-I：真实正文目标覆盖审计（2026-10-10）

**范围**：只诊断。基线 `0265a2e8`（本地）。未修改搜索 / follow / Reader / 预算 / 生产行为；
不新增语义裁判，不改 Evidence Gate，不动 RP-1（仍 NO-GO）。
**证据**：`2b9g_trace.json`（6r/3s/3rd，**含正文文本**）、`2b9h_ab.json`（6/3 与 8/4，**仅 URL 与动作序列**）。

## 一、冻结的评价标准

判定只有四档，**无正文不得判 SUPPORTED**：

| 任务 | SUPPORTED 条件 | PARTIAL 条件 |
|---|---|---|
| Factorio | 实际解释**列车中断机制**：触发条件、与固定时刻表的关系、何时不该用 | 出现列车主题但不解释中断 |
| 围棋 | 实际解释**提子、气的作用、打劫（禁止立即循环）** | 解释其中一部分 |
| Minecraft | 按该题实际提问，检查**红石中继器**的**延迟档位与锁定机制** | 仅泛泛提及红石结构 |
| Python | 按当轮原始问题，区分教程 / 发行公告 / 下载页 / 一般背景 | 相关但不回答 |

## 二、四件事分开评

发现候选 URL ≠ 成功读取 ≠ 覆盖目标 ≠ 结束决策正确。

## 三、逐篇对照（真实证据）

### 6 轮 / 3 搜 / 3 读（有正文文本）

| 任务 | 实际读到的正文 | 覆盖 | 依据片段 |
|---|---|---|---|
| factorio | `wiki.factorio.com/Main_Page/zh` | **MISSING** | 「欢迎来到异星工厂官方维基…最新版本 / 新手入门 / 进阶内容」（纯目录页，188 字符） |
| go_rules | `weiqigo.com/zh-cn/how-to-play/` | **PARTIAL** | 「提子的方式就是堵住对方一块棋的最后一口气」→ 提子/气 SUPPORTED；打劫在本段未见 |
| python_reference | 无正文 | **NOT_EVALUABLE** | `bodies` 为空 |
| portal_two_layer | 无正文（此轮） | **NOT_EVALUABLE** | `bodies` 为空 |

### 6/3 与 8/4 A/B（仅有 URL 与动作）

| 任务 | 6r/3s/3rd | 8r/3s/4rd | 覆盖判定 |
|---|---|---|---|
| factorio | read×2 全为 `Train_stop/zh`，`round_limit` | read×3 **仍是同一** `Train_stop/zh`，`finished` | **MISSING**（火车站材料，不解释中断） |
| go_rules | 无 ≥1k 正文，`round_limit` | 读 `how-to-play/`，`finished` | **PARTIAL**（提子/气；打劫未证） |
| python_reference | 无 ≥1k，`round_limit` | 无 ≥1k，`finished` | **NOT_EVALUABLE** |
| portal_two_layer | read×2 全为 `红石电路`，`round_limit` | read×3 **仍是同一** `红石电路`，`round_limit` | **MISSING/PARTIAL**（读的是红石电路，不是中继器延迟/锁定） |

## 四、发现（每条都可回指上表）

1. **发现与读取已不是瓶颈**：URL 被找到（含具体条目页），3/4 任务读到 ≥1k 正文。
2. **目标覆盖 0/4 SUPPORTED**：只有围棋达到 PARTIAL，且其成功部分（提子/气）来自同一篇通用规则页。
3. **多给两轮买不到新覆盖**：8/4 相对 6/3，factorio 与 Minecraft 都是**同一错页重复读取**（`Train_stop`×3、`红石电路`×3），围棋仅多出一次通用规则页。**增加的两轮在"切题证据"上是净零。**
4. **`finished` ≠ 成功**：8/4 下 3/4 自主结束，其中 3/3 结束时覆盖仍为 MISSING/PARTIAL ⇒ **结束决策在这 3 例上是错的**。
5. **[article] 标签不等于切题**：`Train_stop`、`红石电路` 都是结构上的 article，但不是目标条目——结构标签不能替代主题判断。
6. **`assess_body` 的已知假阳性继续作为负例**，本轮不以其结果判定覆盖。

## 五、Python 诊断（只读，不修）

| 证据 | 问题 | 读取 |
|---|---|---|
| 2B9 基线 `crosstopic.json.bak` | Python 3.15.0 正式发布说明 | **reads = 0 / read_urls 空** |
| 本轮 6/3 与 8/4 | 同上 | 无 ≥1k 正文 |
| 2B9b `validate.json` | 同批任务 | factorio/go 亦 `read_urls` 空或极少 |

**结论：与本轮不可比。** 「此前读到过正文」来自 **2B5 的注册源 feed 路径**（`python-official-blog`，问题为「Python 更新问题」），入口、问题与配置都不同；同问题的自由搜索路径在 2B9 基线上从未读到正文。故 Python 记为 **NOT_EVALUABLE（证据缺失/不可比）**，其运行时路径留给下一刀 A。

## 六、与推进表的对应

| 2B9-I 发现 | 对应行 | 是否匹配 |
|---|---|---|
| 文章已被发现，模型未选对 | 「改模型候选选择」 | **是**（Train_stop/红石电路被选中，目标条目未被选） |
| 已读文章但覆盖不足 | 「改后续追问与停止条件」 | **是**（`finished` 时覆盖 MISSING/PARTIAL） |
| 搜索与 follow 都找不到目标文章 | 「再考虑 Tavily/召回增强」 | **否**（目标条目已可发现） |
| Python 因入口不一致失败 | 「修复对照实验可比性」 | **是**（NOT_EVALUABLE，不可比） |
| 8/4 在覆盖上明显优于 6/3 | 「才考虑提高档位预算」 | **否**（覆盖净零，仅多出通用页） |

因此：**不要**据此提升档位预算；优先做「候选选择」与「停止/追问条件」。

## 七、边界

未 push（本地提交）；PR #209 仍 Open；main、其他 worktree、SearXNG 配置、安全门、
Evidence Gate、生产 B、发布门均未改动；RP-1 NO-GO、读后判断 UNQUALIFIED 不变。
