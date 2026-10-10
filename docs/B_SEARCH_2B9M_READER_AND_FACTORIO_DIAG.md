# B-Search-2B9-M：Reader 错误归因校准 + Factorio 目标页可达性（2026-10-10）

基线 `496c7cbd`（本地）。**本轮无生产代码改动**（诊断 + 校准）。
冻结：预算、SSRF、URL 确认、Evidence Gate、生产 B、RP-1 均未动；`assess_body` 仍 UNQUALIFIED。

## A. Reader 错误归因校准（纠正 2B9-L 的说法）

**接受纠正：`safe_fetch_result()` 的检查顺序是正确的。**
实际代码（`src/web/safe_http.py`，`inspect.getsource`）：
```
L45  if status >= 400:            → _raise_safe(f"http_{status}")
L47  if truncated:                → _raise_safe("response_too_large")
```
即先 HTTP 4xx/5xx、后截断。**不是顺序错误**，也不应在未复现前如此宣称。

**同一条生产路径的新复现（关键）**：
| 调用 | 结果 |
|---|---|
| `safe_fetch_result(URL, max_bytes=300000)` | RAISED `SafeFetchRefusal: response_too_large` |
| `max_bytes=64000` / `32000` / `16000` | 同上（错误码完全相同） |
| 同一时刻原始请求 | **HTTP 403，42 084 字节**（分块传输，无 `Content-Length`） |

**结论（事实并列，不制造单一根因）**
1. 站点侧确实返回 **403 Cloudflare 挑战页**（2B9-L 已证，直连/代理一致）。
2. 生产路径确实抛 **`response_too_large`**，且 **cap=300000（远大于 42 KB）也照样触发**。
   ⇒ 截断标志与传入上限**无关**，缺陷位于 **`http_get_raw` 内部**（`truncated` 被置真/上限未被采用），
   而不是 `safe_fetch_result` 的判定顺序，也不是「403 被状态分支吞掉」。
3. 因此 **2B9-L 中「先查大小后查状态」的猜测作废**；同时**也未确认** 403 被错误分类的直接证据——
   在本路径中状态判定分支（L45）根本没被 4xx 命中，说明 `http_get_raw` 返回的状态与该路径的原始 403 不一致。
   这两种观测**是否为同一次请求**仍需 `http_get_raw` 内部取证，本轮到此为止。

**是否需要代码修复：需要，但不在本轮。** 缺陷确定、可复现、位置收窄到 `http_get_raw`；
但它在**安全关键传输层**，且修法必须建立在「为何置 truncated」的取证之上（不得放宽任何限制）。
按约定最小修复应单独评审 + 补回归，本轮**不顺手改**，仅留下复现与定位。

## B. Factorio 目标条目可达性（逐层证据）

| 层 | 观测 |
|---|---|
| ① SearXNG 原始结果 | 5 个中断导向查询（`train interrupts` / `Factorio train interrupts wiki` / `site:wiki.factorio.com train interrupts` / `列车中断 Factorio` / `Factorio 2.0 interrupts schedule`）**均 0 条 URL 含 `interrupt`**；返回的是词典/门户页（百度百科、iciba、剑桥、游侠、知乎）与 wiki 首页 |
| ② 适配器 / Gateway | 2B9-I 已证 L1→L4 逐层一致（代码未丢结果） |
| ③ 已确认页面 + 同站导航 | `wiki.factorio.com/Main_Page` 与 `wiki.factorio.com/` 各 **465 条同站链接，0 条含 `interrupt`** → 即便排序完美，首页也**不链接**该条目 |
| ④ 搜索词/语言差异 | 英文与中文查询均失败；`site:` 语法未见生效（返回词典页） |

**结论：`SOURCE_RECALL_BLOCKED`** —— 目标条目不可达来自**搜索召回**（引擎不返回该条目）与
**站点首页不链接它**，**不是**预算不足、不是排序问题、不是确认规则过严。
未做任何站点特化绕过，未硬编码目标 URL，未用猜测 URL 冒充成功样本。

## C. 四题覆盖（沿用 2B9-L 独立复核，本轮无变化）

| 任务 | 判定 |
|---|---|
| 围棋 | **3/3 SUPPORTED**（保留为成功样本） |
| Python | release **SUPPORTED**（tutorial/download 过定义） |
| Factorio | **0/3 SUPPORTED**（目标条目不可达，见 B） |
| Minecraft | **0/3 SUPPORTED**（目标页 403 站点限制 + 词级假阳性） |

## D. 状态与边界

无代码改动，故无新增测试；沿用 2B9-K 门禁（32 passed、ruff clean、mypy 122/128 NEW 0）。
未 push；PR #209 仍 Open；main、其他 worktree、默认预算、Evidence Gate、发布门未动；RP-1 NO-GO。
证据：本文件 + 仓库外 `2b9m_reader_diag.py` / `2b9m_factorio_diag.py`。
