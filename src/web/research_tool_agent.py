"""B-Search-2 controlled research tool agent (prototype).

The model chooses the next tool action; the program executes it and enforces
URL safety, quotas and the deadline, then returns the real result (body or error)
so the model can decide again. Bodies read here are **exploratory**: they grant no
evidence or publication authority; the Evidence Gate and post-read verification
stay outside this loop.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import time
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, Callable, Mapping

from src.web.tool_evidence import _public_url

TOOLS = {"search", "feed", "read_page", "finish"}
SYSTEM = (
    "You are a bounded research tool agent. Decide the SINGLE next action toward "
    "answering the user's question, learning from previous observations. "
    'Return JSON only: {"tool":"search","query":"<keywords>","reason":"..."} OR '
    '{"tool":"feed","url":"<rss/atom url>","reason":"..."} OR '
    '{"tool":"read_page","url":"<http(s)>","reason":"..."} OR '
    '{"tool":"finish","reason":"..."}. '
    "Use feed to discover article links from an RSS/Atom feed; read specific article "
    "pages, never home/dictionary/navigation pages; do not repeat a failed action; "
    "one action per turn. A page you read is exploratory and does not prove any fact."
)


def parse_feed(payload: str, *, limit: int = 10) -> list[dict[str, str]]:
    """Extract (title, url) from RSS <item> or Atom <entry>; stdlib only."""
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return []
    entries: list[dict[str, str]] = []
    for node in root.iter():
        tag = node.tag.split("}")[-1]
        if tag not in {"item", "entry"}:
            continue
        title = ""
        link = ""
        for child in node:
            ctag = child.tag.split("}")[-1]
            if ctag == "title" and child.text:
                title = child.text.strip()
            elif ctag == "link":
                link = (child.get("href") or child.text or "").strip()
        if link:
            entries.append({"title": title, "url": link})
        if len(entries) >= limit:
            break
    return entries


@dataclass(frozen=True)
class AgentBudget:
    max_rounds: int = 6
    max_searches: int = 4
    max_reads: int = 3
    hard_seconds: float = 60.0


def parse_action(raw: Any) -> dict[str, str]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            raise ValueError("action_not_json") from None
    if not isinstance(raw, Mapping) or raw.get("tool") not in TOOLS:
        raise ValueError("action_tool")
    tool = str(raw["tool"])
    reason = str(raw.get("reason") or "")
    if tool == "search":
        query = str(raw.get("query") or "").strip()
        if not query:
            raise ValueError("action_query")
        return {"tool": "search", "query": query, "reason": reason}
    if tool == "feed":
        url = str(raw.get("url") or "").strip()
        if not _public_url(url):
            raise ValueError("action_private_url")
        return {"tool": "feed", "url": url, "reason": reason}
    if tool == "read_page":
        url = str(raw.get("url") or "").strip()
        if not _public_url(url):
            raise ValueError("action_private_url")
        return {"tool": "read_page", "url": url, "reason": reason}
    return {"tool": "finish", "reason": reason}


def _prompt(question: str, observations: list[str]) -> list[dict[str, str]]:
    context = {
        "question": question,
        "observations": observations[-6:],
        "instruction": SYSTEM,
    }
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
    ]


def run_tool_agent(
    *,
    gateway: Any,
    completion: Callable[..., str],
    question: str,
    budget: AgentBudget | None = None,
    initial_urls: tuple[str, ...] = (),
    monotonic: Callable[[], float] = time.monotonic,
    should_cancel: Callable[[], bool] = lambda: False,
) -> dict[str, Any]:
    budget = budget or AgentBudget()
    started = monotonic()
    deadline = started + budget.hard_seconds
    calls: list[dict[str, Any]] = []
    observations: list[str] = []
    searches = reads = 0
    bodies: list[dict[str, Any]] = []
    # Only URLs confirmed by an actual search result (or supplied up front) may be
    # read; a model-guessed URL is recorded as pending, never fetched.
    confirmed: set[str] = {url for url in initial_urls if _public_url(url)}
    stop = "round_limit"
    for rnd in range(budget.max_rounds):
        if should_cancel():
            stop = "cancelled"
            break
        if monotonic() >= deadline:
            stop = "budget_exhausted"
            break
        try:
            raw = completion(
                messages=_prompt(question, observations),
                timeout=min(20.0, max(1.0, deadline - monotonic())),
                task_name="research_tool_agent",
            )
            action = parse_action(raw)
            error = ""
        except Exception as exc:  # noqa: BLE001 - a bad action is recorded, not fatal
            action = {"tool": "invalid", "reason": ""}
            error = f"{type(exc).__name__}"
        call: dict[str, Any] = {"round": rnd, "action": action, "error": error}
        if error:
            observations.append(f"round {rnd}: your action was rejected ({error}); return valid JSON.")
            calls.append(call)
            continue
        if action["tool"] == "finish":
            stop = "finished"
            calls.append(call)
            break
        if action["tool"] == "search":
            if searches >= budget.max_searches:
                call["result"] = {"status": "quota_exceeded", "reason": "search_quota"}
                observations.append(f"round {rnd}: search quota reached.")
                calls.append(call)
                continue
            searches += 1
            try:
                result = gateway.search_exact(action["query"], max_results=5)
            except Exception as exc:  # noqa: BLE001
                result = {"status": "unavailable", "reason": f"{type(exc).__name__}"}
            rows = result.get("results") or []
            for r in rows:
                url = str(r.get("url") or "")
                if _public_url(url):
                    confirmed.add(url)
            call["result"] = {"status": result.get("status"), "reason": result.get("reason"),
                              "n": len(rows), "urls": [r.get("url") for r in rows]}
            brief = "\n".join(
                f"- {r.get('title')} | {r.get('url')} | {str(r.get('snippet'))[:160]}" for r in rows
            )
            observations.append(f"round {rnd}: search '{action['query']}' ->\n{brief or '(no results)'}")
            calls.append(call)
            continue
        if action["tool"] == "feed":
            if action["url"] not in confirmed:
                call["result"] = {"status": "pending_url_confirmation",
                                  "reason": "url_not_from_search_result"}
                observations.append(
                    f"round {rnd}: feed rejected: {action['url']} was not confirmed; "
                    "use a provided or already-discovered URL."
                )
                calls.append(call)
                continue
            if searches >= budget.max_searches:
                call["result"] = {"status": "quota_exceeded", "reason": "search_quota"}
                observations.append(f"round {rnd}: feed/search quota reached.")
                calls.append(call)
                continue
            searches += 1
            try:
                request = urllib.request.Request(action["url"], headers={"User-Agent": "StudyAgent/feed"})
                with urllib.request.urlopen(
                    request, timeout=min(15.0, max(1.0, deadline - monotonic()))
                ) as response:
                    payload = response.read(300_000).decode("utf-8", "replace")
                entries = parse_feed(payload)
            except Exception as exc:  # noqa: BLE001
                entries = []
                call["feed_error"] = type(exc).__name__
            for entry in entries:
                if _public_url(entry["url"]):
                    confirmed.add(entry["url"])
            call["result"] = {"status": "ok" if entries else "empty", "n": len(entries),
                              "urls": [entry["url"] for entry in entries]}
            brief = "\n".join(f"- {entry['title']} | {entry['url']}" for entry in entries)
            observations.append(f"round {rnd}: feed '{action['url']}' ->\n{brief or '(no entries)'}")
            calls.append(call)
            continue
        if action["tool"] == "read_page":
            if action["url"] not in confirmed:
                call["result"] = {"status": "pending_url_confirmation",
                                  "reason": "url_not_from_search_result"}
                observations.append(
                    f"round {rnd}: read rejected: {action['url']} was not confirmed by a search "
                    "result; choose a URL that appeared in the search results."
                )
                calls.append(call)
                continue
            if reads >= budget.max_reads:
                call["result"] = {"status": "quota_exceeded", "reason": "read_quota"}
                observations.append(f"round {rnd}: read quota reached.")
                calls.append(call)
                continue
            reads += 1
            try:
                body = gateway.read(action["url"], max_chars=6000,
                                    timeout=min(8.0, max(0.5, deadline - monotonic())))
            except Exception as exc:  # noqa: BLE001
                body = {"ok": False, "url": action["url"], "error": f"{type(exc).__name__}"}
            content = str(body.get("content") or body.get("readme") or "")
            call["result"] = {"ok": body.get("ok"), "chars": len(content),
                              "error": body.get("error") or body.get("error_code")}
            bodies.append({"url": action["url"], "ok": bool(body.get("ok")),
                           "chars": len(content), "preview": content[:600],
                           "reason": action.get("reason", "")})
            observations.append(
                f"round {rnd}: read {action['url']} ok={body.get('ok')} chars={len(content)} "
                f"error={body.get('error') or body.get('error_code') or ''}\n{content[:1200]}"
            )
            calls.append(call)
            continue
    elapsed = round(monotonic() - started, 3)
    return {
        "question": question,
        "stop_reason": stop,
        "rounds": len(calls),
        "searches": searches,
        "reads": reads,
        "elapsed_seconds": elapsed,
        "bodies": bodies,
        "calls": calls,
        "publication_authority": False,
    }
