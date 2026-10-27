# Search-to-Answer-1 基线（检索层，第一轮 5 题）

> 本轮只测量**检索层**：真实搜索 + 真实网页读取。没有零成本回答生成器接入本检出，
> 因此 `answer_status` / `TTFU` / `evidence_verdict` / 多轮追问行为一律记为 `not_measured`，
> 不用检索指标冒充回答质量。

## 运行信息

| 项 | 值 |
| --- | --- |
| run_id | `4f0f6b07726d499a9ef735d9ff383b42` |
| HEAD | `e470a456`（#293 合并提交，DDG POST 修复已在 main） |
| 问题集 | `tests/fixtures/search_to_answer/baseline_v1.json`（`search-to-answer-baseline-v1`，冻结于 2026-10-28，共 20 题） |
| 本轮题目 | A01 / B01 / B02 / C01 / D01（`round_1: true`） |
| 提供商模式 | `auto` / `fallback`（SearXNG 关闭，Bing RSS + DDG）/ `ddg_only` |
| 采集脚本 | `tools/run_search_to_answer_baseline.py`（复用 `GeneralWebGateway`，仅记录有界操作元数据） |
| 原始产物 | `docs/research_quality/SEARCH_TO_ANSWER_BASELINE_1.json` |
| 模型调用 | 无（付费开关保持 OFF） |

环境事实：本机 SearXNG 在 `127.0.0.1:8080` 正常响应（`/healthz` = OK），但仅 **bing** 引擎返回结果
（同机探测：`google news: CAPTCHA`、`brave.news: too many requests`、`duckduckgo news: timeout`）。
因此 `auto` 实际等同于「SearXNG 的 bing 引擎」，`fallback` 等同于「Bing RSS 直连」。

## 结果数字

| 模式 | 搜索成功 | 有结果 | 结果数 | 中位耗时 | P90 | 摘要存在率 | 读取成功 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `auto`（SearXNG/bing） | 5/5 | 5/5 | 30 | 0.672 s | 4.219 s | 1.00 | **1/10** |
| `fallback`（Bing RSS） | 5/5 | 5/5 | 30 | 0.297 s | 0.312 s | 1.00 | **1/10** |
| `ddg_only`（DuckDuckGo） | **2/5** | 2/5 | 12 | 2.812 s | 5.016 s | **0.00** | 1/4 |

结果来源：`auto` = `SearXNG/bing` ×30；`fallback` = `Bing RSS` ×30；`ddg_only` = `DuckDuckGo` ×12。

**关键事实：搜索「成功」不等于搜到有用的东西。** `auto` 5/5 状态 `ok`，但按人工判读只有 1/5 题
（A01）拿到部分相关结果，其余 4 题的结果与问题无关。

### 人工相关性判读（n=5，仅第一轮样本，不作为统计结论）

| 题目 | auto / fallback 结果 | ddg_only 结果 |
| --- | --- | --- |
| A01 星铁当前版本/卡池 | **部分相关**：官网首页与 4.6 页面，但需读取正文才能给出版本/卡池 | 不可用（SSL EOF） |
| B01 千冶·刃配装 | **无关**：`星_百度百科`、`汉语查`、`AstroGaze`、官网首页 | **相关**：米游社千冶·刃攻略、B 站、17173 |
| B02 虚构叙事自动战斗 | **无关**：与 B01 完全相同的 6 条（引擎只匹配到「星」） | 相关但**版本偏旧**（V3.4 / V2.5 文章） |
| C01 虚构叙事 60000 分 | **无关**：同样 6 条 | 不可用（challenge） |
| D01 虚构叙事配队 | **无关**：`当前_百度百科`、`time.ms`、`北京时间` —— 引擎只匹配到「当前」 | 不可用（challenge） |

## 失败样例（可复核）

**1. 整句提问被直接当成检索词，引擎退化为单词匹配**

- B01/B02/C01 三个不同问题返回**完全相同**的 6 条结果：`星_百度百科` / `云·星穹铁道` / `汉语查` /
  `星星_百度百科` / `星穹铁道官网` / `AstroGaze`。
- D01 返回 `当前_百度百科`、`Time.ms`、`北京时间`。
- `attempted_queries` 只有 1 条，就是原始整句提问（未做关键词抽取或改写）。

**2. 网页读取基本不可用**

| URL | 结果 |
| --- | --- |
| `https://sr.mihoyo.com/cloud/`、`https://sr.mihoyo.com/` | `provider_failed`；直连探针为 `all_backends_failed`（SPA，无可抽取正文） |
| `https://baike.baidu.com/item/星/1586` | `http_403`（反爬） |
| `https://www.miyoushe.com/sr/article/75743090`（DDG 命中的相关攻略） | `provider_failed` |
| `https://time.ms/zh-cn/` | 成功，但只有 **282 字符**，且与问题无关 |
| `https://codingchallenges.fyi/` | 成功，但只有 **481 字符**（样板文字为主） |

即：即便拿到相关 URL（DDG 的 B01），**读不出正文**，证据链在第一跳就断了。

**3. DDG 在高频请求下不可用**

| 题目 | 错误 |
| --- | --- |
| A01 | `duckduckgo_html:URLError:<urlopen error [SSL: UNEXPECTED_EOF_WHILE_READING] ...>` |
| C01 | `duckduckgo_html:challenge` |
| D01 | `duckduckgo_html:challenge` |

5 题在数十秒内连续执行，第 4、5 次开始被拦。注意：本次**没有出现**查询词回显导致的误判
（C01 的查询里不含 challenge 字样），说明 #293 的结构化标记修复有效，这里是真的被拦。

**4. 摘要缺失是 DDG 专属，不是全局**

`ddg_only` 摘要存在率 **0.00**（0/12），而 Bing 路径为 **1.00**（30/30）。因此 snippet 缺口只影响
DDG 这条fallback；但恰好也是这次唯一返回相关结果的提供商。

## 根因归类（按实测影响排序）

| 序 | 根因 | 证据 | 归属 |
| --- | --- | --- | --- |
| 1 | **查询构建缺失**：整句中文提问直接下发，引擎退化为单词匹配 | 3 题返回同一组无关结果；D01 匹配「当前」 | 检索编排（query planning），不是 provider |
| 2 | **正文抽取不可用**：SPA 与反爬站点读取失败，成功样本仅 282–481 字符 | 1/10 成功；mihoyo `all_backends_failed`、baike `http_403`、miyoushe `provider_failed` | 读取层 |
| 3 | **路由只看「有没有结果」**：Bing 一有无关结果就结束，DDG 从不参与 | `auto`/`fallback` 30 条全部 Bing，DDG 0 条 | 路由策略 |
| 4 | **DDG 突发请求被拦**：无退避/节流/缓存 | 第 4、5 题 challenge；另有 SSL EOF | provider 调用策略 |
| 5 | **DDG 无摘要**：解析器只取标题与链接 | 0/12 | 解析器（P3，仅 DDG） |

## 未测量项

| 指标 | 原因 |
| --- | --- |
| 有效回答率 | 无零成本回答生成器 |
| 主张证据支持率 | 需要生成的主张才能核验 |
| 首个有用内容时间（TTFU） | 需要真实回答流式输出 |
| 多轮追问行为（D01 第二轮等） | 需要会话级运行 |

本轮**没有**用检索时延冒充 TTFU，也没有用「搜到 URL」冒充「回答有证据」。

## 下一步（按影响排序，待定授权）

1. **查询构建**：把整句提问拆成检索式（实体识别 + 关键词），例如「星铁」→「崩坏：星穹铁道」，
   并保留时间限定词。验收：B01/B02/C01 三题返回结果不再是同一组。
2. **读取层**：为攻略站（米游社/米哈游官网）建立可用的读取或官方接口路径；验收：相关 URL 的读取成功率。
3. **路由**：结果非空但相关性低时继续尝试下一个 provider（或并行取回后统一排序）。
4. **DDG 节流**：单飞 + 退避 + 短期缓存，避免连续请求被 challenge。
5. **DDG 摘要**：解析 `result__snippet`（仅此 provider 需要）。

补齐 1–3 之前，讨论 snippet（第 5 项）对最终答案的影响缺乏证据。

## 技术备忘：哪些出口需要代理（本轮实测，不改代码）

第三轮测量（同一台机器、同一代理 `127.0.0.1:7890`、每个端点 1 次 GET、8 s 超时）：

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
  --case A01 --case B01 --case B02 --case C01 --case D01
```

产物写入 `docs/research_quality/SEARCH_TO_ANSWER_BASELINE_1.json`；
每次运行生成新的 `run_id`，`head_sha` 记录代码版本，便于跨轮对比。
