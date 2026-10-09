# B-Search-2A1 — SearXNG engine availability diagnostic

Diagnosis only. No Agent change, no budget change, no gate change. Base
`f99ed3c6`. RP-1 NO-GO. Evidence: `reading-notebook-ui-evidence/model-driven-search-2a/engine_matrix.txt`.

## Method
Container live config + DNS, container vs host HTTPS egress, SearXNG logs, and the
SearXNG JSON API per query (host reaches the engines, so the difference is inside
the container path, not the code).

## Engine matrix
| engine | host reach | container egress | SearXNG state |
| --- | --- | --- | --- |
| google cse | HTTP 200 | **FAIL** (DNS→bogus `2001::1`) | connection error |
| brave | HTTP 200 | timeout | Suspended: too many requests |
| duckduckgo | HTTP 200 | OK | timeout / CAPTCHA |
| startpage | HTTP 200 | – | Suspended: CAPTCHA |
| wikipedia | – | – | timeout; ~0 results |
| wikidata | – | – | engine init failed |

SearXNG JSON API: `python` → 1 result; `Factorio` / `weather` / `地租改正 1873 …` /
`空气源热泵 除霜` → **0 results**; `unresponsive_engines` always brave/duckduckgo/
google cse/startpage.

## Fault attribution (two distinct causes)
1. **Container network (narrow).** The container's DNS resolves `www.google.com` to
   a bogus `2001::1`, so `google cse` fails with a connection error; the **host**
   reaches google with HTTP 200. This is a Docker DNS/IPv6 issue and is fixable —
   but it only affects Google.
2. **Engine anti-bot (dominant).** `brave` (Suspended: too many requests),
   `duckduckgo` (CAPTCHA), `startpage` (CAPTCHA), plus repeated engine timeouts —
   even though the host reaches all of them with HTTP 200. So the free scrapers
   **block this egress path**; host-only 200 does not mean SearXNG can produce
   parsable results.
3. `wikidata` engine init fails; `wikipedia` mostly 0.

## Decision (per the frozen criteria)
This is the case **"全部通用引擎受阻 → 停止在免费网页抓取引擎上反复调参，转向评估正式搜索 API 的可靠性与成本"**. The general-purpose free engines are unreliable from this
environment; the marginal fix (container IPv6/DNS) recovers only Google, whose
scraper still 403'd. So:

- **Do not** keep tuning SearXNG scrapers.
- **Fix the container DNS/IPv6** as a cheap, worthwhile hygiene item (may recover
  `google cse`), but do not expect it to make the free engines reliable.
- **Evaluate a formal search API** (reliability + cost) as the infrastructure
  choice — search is base infrastructure for Study Agent and must not be the
  long-term blocker.

## Boundaries
No Agent/prompt/budget/Evidence Gate change; no CAPTCHA/rate-limit bypass; base
`f99ed3c6` preserved. B+A integration stays separate from this environment work.

## Next
1. Optionally fix the container DNS/IPv6 and re-probe `google cse`.
2. Otherwise/afterwards: short evaluation of one documented search API against the
   same three frozen cases (quality, latency, cost), then resume Experiment A/B.
