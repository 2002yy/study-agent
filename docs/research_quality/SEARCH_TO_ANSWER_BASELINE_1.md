# Search-to-Answer-1 基线（检索层，第一轮 5 题）

> 本轮只测量**检索层**：真实搜索 + 真实网页读取。没有零成本回答生成器接入本检出，
> 因此 `answer_status` / `TTFU` / `evidence_verdict` / 多轮追问行为一律记为 `not_measured`，
> 不用检索指标冒充回答质量。

## 运行信息

| 项 | 值 |
| --- | --- |
| 问题集 | `tests/fixtures/search_to_answer/baseline_v1.json`（`search-to-answer-baseline-v1`，冻结于 2026-10-28，共 20 题） |
| 本轮题目 | A01 / B01 / B02 / C01 / D01（`round_1: true`） |
| 提供商模式 | `auto` / `fallback`（SearXNG 关闭，Bing RSS + DDG）/ `ddg_only` |
| 采集脚本 | `tools/run_search_to_answer_baseline.py`（复用 `GeneralWebGateway`，仅记录有界操作元数据） |
| 模型调用 | 无（付费开关保持 OFF） |

两次运行（同一代码，间隔约一小时），用于观察波动：

| 运行 | run_id | HEAD | 产物 |
| --- | --- | --- | --- |
| 第一次 | `4f0f6b07726d499a9ef735d9ff383b42` | `e470a456` | `SEARCH_TO_ANSWER_BASELINE_1.run1.json` |
| 第二次（合同修正后） | `9fc09d8cfa8a43e4a1cf2c4f77251798` | `18d5ca84` | `SEARCH_TO_ANSWER_BASELINE_1.json` |

环境事实：本机 SearXNG 在 `127.0.0.1:8080` 正常响应（`/healthz` = OK），但仅 **bing** 引擎返回结果
（同机探测：`google news: CAPTCHA`、`brave.news: too many requests`、`duckduckgo news: timeout`）。
因此 `auto` 实际等同于「SearXNG 的 bing 引擎」，`fallback` 等同于「Bing RSS 直连」。

## 读取口径（本轮修订）

读取指标**不是**「相关正文抽取成功率」，而是**每题结果列表前 2 条 URL 的技术读取**：

| 名称 | 定义 |
| --- | --- |
| `read_sampling` | `results[:max_reads]`（默认 2），**不做相关性过滤**；每条记录都写明 `sampled` 与 `available_results` |
| `top_k_url_technical_read_successes` | 抓取与抽取都成功且正文非空（不判断是否有用） |
| `top_k_url_length_qualified_reads` | 技术成功且正文 ≥ 800 字符（`--min-content-chars`） |
| `claim_support` | **`not_measured`**：长度达标不等于相关，更不等于支持某个结论 |
| `related_source_read_quality` | **`not_measured`**：需要对相关 URL 单独抽样并人工判读 |

**抽样偏差**：B01/B02/C01 的前两条 URL 多为「星」的字典页、云游戏首页，D01 前两条是词语解释与时钟网站。
因此下文的读取数字只描述「读取路径在首批返回结果上的表现」，不能推断「相关攻略来源的抽取质量」。

**命名变更**：run2 产物里这两个计数叫 `top_k_url_technical_read_successes` 与 `top_k_url_evidence_usable_reads`；
后者在后续代码中已改名为 `top_k_url_length_qualified_reads`，两者是**同一口径**（只改名，未改数据）。
run2 的原始产物保持原样，不做改写。

## 结果数字

### 搜索层

| 运行 | 模式 | 搜索成功 | 结果数 | 中位 / P90 | 摘要存在率 | 结果来源 |
| --- | --- | ---: | ---: | --- | ---: | --- |
| run1 | `auto` | 5/5 | 30 | 0.672 s / 4.219 s | 1.00 | SearXNG/bing |
| run1 | `fallback` | 5/5 | 30 | 0.297 s / 0.312 s | 1.00 | Bing RSS |
| run1 | `ddg_only` | **2/5** | 12 | 2.812 s / 5.016 s | 0.00 | DuckDuckGo |
| run2 | `auto` | 5/5 | 30 | 0.375 s / 2.125 s | 1.00 | SearXNG/bing |
| run2 | `fallback` | 5/5 | 30 | 0.297 s / 0.328 s | 1.00 | Bing RSS |
| run2 | `ddg_only` | **5/5** | 30 | 2.485 s / 5.422 s | 0.00 | DuckDuckGo |

**DDG 可用性是波动的**：run1 有 3 题失败（2 次 `challenge`、1 次 SSL `UNEXPECTED_EOF`），run2 全部成功。
所以更准确的说法是「DDG 在连续请求下不稳定」，而不是「DDG 不可用」。

### 读取层（前 2 条 URL，run2）

| 模式 | 技术读取成功 | 正文长度达标（≥800 字符） | 读取错误码 |
| --- | ---: | ---: | --- |
| `auto` | 1/10 | **0/10** | `fetch_failed`、`other`、`provider_failed` |
| `fallback` | 1/10 | **0/10** | `fetch_failed` |
| `ddg_only` | 3/10 | **3/10** | `fetch_failed`、`provider_failed` |

run1 的同口径值为：`auto` 1/10（长度达标 0/10）、`fallback` 1/10（0/10）、`ddg_only` 1/4（1/4）。
长度达标只说明正文足够长可作候选，**不说明它相关或能支撑结论**（`claim_support: not_measured`）。

### 人工相关性判读（n=5，仅第一轮样本，不作为统计结论）

| 题目 | auto / fallback | ddg_only |
| --- | --- | --- |
| A01 版本/卡池 | 部分相关（官网页面，读不出正文） | **相关**：官网 4.6 页面、卡池时间表（`gachia.com`，3727 字符可读） |
| B01 千冶·刃配装 | **无关**：`星_百度百科`、`汉语查`、`AstroGaze` | **相关**：米游社攻略、B 站（2061 字符可读）、今日头条 |
| B02 虚构叙事自动战斗 | **无关**：与 B01 完全相同的 6 条 | 相关但**版本偏旧**（V3.4 / V2.1 文章，米游社读取失败） |
| C01 60000 分 | **无关**：同样 6 条 | 相关但**版本过旧**（V1.6 攻略） |
| D01 配队 | **无关**：`当前_百度百科`、`time.ms` | **相关**：4.5 虚构叙事阵容视频（1467 字符可读）、V4.4 攻略 |

## 失败样例（可复核）

**1. 整句提问被直接当成检索词，引擎退化为单词匹配**

- B01/B02/C01 三个不同问题在 `auto` 与 `fallback` 下返回**完全相同**的 6 条结果：
  `星_百度百科` / `云·星穹铁道` / `汉语查` / `星星_百度百科` / `星穹铁道官网` / `AstroGaze`。
- D01 返回 `当前_百度百科`、`Time.ms`、`北京时间`。
- `attempted_queries` 只有 1 条，就是原始整句提问（未做关键词抽取或改写）。

**2. 抽取失败集中在特定站点（与网络无关）**

| URL | 结果 |
| --- | --- |
| `https://sr.mihoyo.com/` | 直连 HTTP 200，但 `provider_failed`（SPA，无可抽取正文） |
| `https://baike.baidu.com/item/星/1586` | `http_403`（反爬；走代理同样 403） |
| `https://www.miyoushe.com/sr/article/75743090`（DDG 命中的相关攻略） | `provider_failed` / `fetch_failed`（两种模式反复失败） |
| `https://www.bilibili.com/video/BV1uZV96gEXd/` | 成功，2061 字符（正文长度达标） |
| `https://gachia.com/zh/starrail/guides/banner-schedule-guide` | 成功，3727 字符（正文长度达标） |
| `https://time.ms/zh-cn/` | 成功但仅 282 字符 → 技术成功、**证据不可用** |

**3. 摘要缺失是 DDG 专属**

`ddg_only` 摘要存在率 **0.00**（0/30），Bing 路径 **1.00**（30/30）。DDG 恰好也是唯一给出相关结果的提供商，
所以它的结果只有「标题 + URL」可用，直到某次读取成功。

**4. DDG 连续请求下不稳定**

run1：A01 `URLError:<urlopen error [SSL: UNEXPECTED_EOF_WHILE_READING] ...>`、C01/D01 `challenge`；
run2：全部成功。run1 的 challenge 不是查询词回显误判（查询不含 challenge 字样），说明 #293 的结构化标记修复有效。

## 根因归类（按实测影响排序）

| 序 | 根因 | 证据 | 归属 |
| --- | --- | --- | --- |
| 1 | **查询构建缺失**：整句中文提问直接下发，引擎退化为单词匹配 | 3 题返回同一组无关结果；D01 匹配「当前」 | 检索编排（query planning），不是 provider |
| 2 | **读取路径在攻略站基本不可用**（前 2 条 URL 口径）：米游社/米哈游 SPA 抽取失败，baike 403 | `auto`/`fallback` 技术 1/10、长度达标 0/10；DDG 路径 3/10 长度达标 | 读取层 |
| 3 | **路由只看「有没有结果」**：Bing 有无关结果就结束，DDG 从不参与 | `auto`/`fallback` 30 条全部 Bing，DDG 0 条 | 路由策略 |
| 4 | **DDG 突发请求不稳定**：无退避/节流/缓存 | run1 第 4、5 题 challenge，另有 SSL EOF | provider 调用策略 |
| 5 | **DDG 无摘要**：解析器只取标题与链接 | 0/30 | 解析器（P3，仅 DDG） |

## 未测量项

| 指标 | 原因 |
| --- | --- |
| 有效回答率 | 无零成本回答生成器 |
| 主张证据支持率 | 需要生成的主张才能核验 |
| 首个有用内容时间（TTFU） | 需要真实回答流式输出 |
| 多轮追问行为（D01 第二轮等） | 需要会话级运行 |
| 相关来源的正文抽取质量 | 需要对相关 URL 单独抽样并人工判读（当前只测了前 2 条） |
| 证据是否支持具体结论（claim_support） | 需要生成的主张才能核验；长度达标不是证据 |

## 技术备忘：哪些出口需要代理（本轮实测，不改代码）

同一台机器、同一代理 `127.0.0.1:7890`、每个端点 1 次 GET、8 s 超时：

| 出口 | 直连 | 走代理 | 处置 |
| --- | --- | --- | --- |
| DuckDuckGo | 超时 | 200 / 3.1 s | 已实现 provider-scoped 代理（`WEB_DUCKDUCKGO_PROXY`） |
| Bing RSS | 200 / 0.3 s | 200 / 0.3 s | **不加代理**：本来就通，加了只会更慢 |
| SearXNG | 本机 `127.0.0.1:8080` | 不适用 | **永不加代理**：回环服务，进程级代理会重现 `CL_M1_REBIND_PREVIEW.md §7` 记录的故障 |
| GitHub API | 200 / 0.5 s | 200 / 2.5 s | 不加代理：直连更快 |
| **Jina Reader**（`r.jina.ai`，默认关闭） | **超时** | 200 / 2.5 s | **启用时必须配代理**，见下方约定 |
| `baike.baidu.com`（读取目标） | 403 | 403 | 与代理无关（反爬） |
| `sr.mihoyo.com` / `miyoushe.com`（读取目标） | 200 / 0.1 s | 200 | 与代理无关（SPA / 抽取失败） |

**结论：本仓库当前只有两个出口真正需要代理——DuckDuckGo 与 Jina Reader。**

### 对 Jina Reader 的约定（下一轮实现，本轮不动代码）

1. 只有当读取层确实启用 Jina（`jina_fallback_enabled()` 为真且实测被它阻塞）时才实现；
2. 实现时必须沿用 DDG 的 **provider-scoped** 模式：为这一次请求构建独立 opener，
   使用**专属环境变量**（例如 `WEB_JINA_PROXY`），**不得**依赖或引入进程级 `HTTP(S)_PROXY`；
3. 测试必须证明三件事：配置了 Jina 代理时其它请求不受影响、回环地址不被代理、
   代理地址与凭据不进入日志或产物；
4. 在该约定落地之前，Jina Reader 保持默认关闭。

**为什么不现在做**：Jina 默认关闭；本轮读取失败的主因是 SPA 与正文抽取（mihoyo / miyoushe 直连均 200），
不是出口问题。先实现代理旋钮属于「先建设、后测量」。

## 复现方式

```powershell
# 需要本地 SearXNG(:8080) 与 .env 中的 WEB_DUCKDUCKGO_PROXY
python tools/run_search_to_answer_baseline.py `
  --mode auto --mode fallback --mode ddg_only `
  --case A01 --case B01 --case B02 --case C01 --case D01 `
  --min-content-chars 800
```

每次运行生成新的 `run_id`，`head_sha` 记录代码版本；`read_contract` 记录选择规则与阈值，便于跨轮对比。
