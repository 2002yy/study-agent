# B-Search-2B2 — GitHub Runner egress qualification: result

Diagnostic only. Isolated branch `diag/gh-egress-probe` (base `origin/main`
`f35b13b7`); **does not touch `main`, #208, or the B worktree**. Run
`37963315465` (push event, 18 s, success). Evidence:
`reading-notebook-ui-evidence/model-driven-search-2b/gh_runner_egress.txt`.
RP-1 NO-GO.

## Method
`.github/workflows/egress-probe.yml` (restricted `on: push` to that branch, since
`workflow_dispatch` needs the default branch) runs `tools/gh_egress_probe.py`:
DNS + HTTPS status/latency to eight hosts, then `pip install feedparser yt-dlp`
(anonymous, no credentials) and B站/YouTube/RSS tool tests. No cookies, no
anti-bot bypass.

## Result — runner egress works; platform anti-bot still blocks content
DNS + HTTPS reachability (all responded):

| target | dns | status | latency |
| --- | --- | --- | --- |
| bilibili_search_api | 148.153.45.10 | **200** | 0.62 s |
| youtube_watch | 142.251.155.4 | **200** | 0.16 s |
| v2ex_feed | 172.66.133.207 | 200 | 0.29 s |
| rss_python_blog | 185.199.108.153 | 200 | 0.05 s |
| google | 142.251.152.119 | 200 | 0.12 s |
| duckduckgo_html | 40.89.244.232 | 202 | 0.13 s |
| brave | 13.225.61.123 | **429** | 0.17 s |
| startpage | 67.63.51.231 | 200 | 0.21 s |

Tools (installed successfully: `yt-dlp 2026.8.19`, `feedparser 6.0.14`):

| tool test | result |
| --- | --- |
| `feedparser` RSS | **rc=0** (feed parsed) |
| `yt-dlp` bilibili search | **rc=1 — HTTP 412 Precondition Failed** |
| `yt-dlp` youtube | **rc=1 — "Sign in to confirm you're not a bot"** |

## Attribution (per-operation, not unified)
- **Egress**: the GitHub runner **has normal internet access** — every target host
  is reachable at the HTTP level with low latency. So a working egress environment
  **is available via Actions**.
- **Anti-bot (blocks content, not egress)**: B站 returns **412** and YouTube demands
  a **bot check** even from the runner → anonymous content extraction is blocked by
  the platforms, independent of our network. `brave` returns 429.
- **Working chain found**: **RSS via feedparser** works end-to-end (a real
  data-acquisition chain exists).

## Conclusion
- A hosted runner gives reliable egress, but **does not by itself unlock B站/YouTube
  content** (anti-bot), so the platform path stays blocked without auth (out of
  scope).
- For **generic web discovery**, the remaining reliable option is a **keyed search
  API** (its servers do the crawling) — consistent with the earlier finding.
- RSS is a genuine, immediately usable discovery chain.

Per the frozen decision: the honest failure for B站/YouTube is retained; next is to
evaluate a formal search API (or use RSS) — **not** to loosen the gate or bypass
anti-bot.

## Boundaries
No change to #208, the B worktree, `main`, the Agent loop, model budget, cookies,
or the Evidence Gate. Diagnostic branch kept (`diag/gh-egress-probe`).
