"""Probe the site pool with one real browser question.

This is a capability check, not a model run: it opens each site's own search
page through the paired browse extension and records what happened. No paid
call is made, so it can be repeated whenever a site changes its markup or asks
for a login.

    python tools/probe_site_pool.py --query "SQLite WAL concurrent writers" \
        --out D:/study-agent-validation/site-pool-20261115/matrix.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.web import site_pool
from src.web.browse_search import search_browse_at


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--timeout", type=float, default=12.0)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--keys", default="", help="comma-separated subset")
    args = parser.parse_args(argv)

    wanted = {key.strip() for key in args.keys.split(",") if key.strip()}
    sites = [site for site in site_pool.SITES if not wanted or site.key in wanted]
    results = []
    for site in sites:
        started = time.monotonic()
        if site.adapter != "generic":
            from src.web.browse_search import search_browse

            rows, error = search_browse(
                args.query, args.limit, args.timeout, engine=site.adapter
            )
            meta = {"status": "ok" if rows else (error or "browse:no_results"),
                    "seconds": round(time.monotonic() - started, 2),
                    "page_results": len(rows)}
        else:
            rows, error, meta = search_browse_at(
                site.search_url(args.query),
                args.limit,
                args.timeout,
                source=f"{site.label} via browse",
                selector=site.result_selector,
                pattern=site.result_pattern,
                own_hosts=site.own_hosts,
                wait_for=site.wait_selector,
            )
        results.append({
            "site": site.key,
            "label": site.label,
            "category": site.category,
            "needs_login": site.needs_login,
            "verified": site.verified,
            "default_enabled": site.default_enabled,
            "status": meta.get("status") or error or "unknown",
            "seconds": meta.get("seconds", round(time.monotonic() - started, 2)),
            "page_results": meta.get("page_results", 0),
            "results": len(rows),
            "sample": (meta.get("sample") or [])[:8],
            "accepted": [row["url"] for row in rows[:8]],
        })
        print(f"{site.key:14} {results[-1]['status']:32} "
              f"{results[-1]['seconds']:5.1f}s page={results[-1]['page_results']:2} "
              f"valid={results[-1]['results']}", flush=True)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "query": args.query,
        "probed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sites": results,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
