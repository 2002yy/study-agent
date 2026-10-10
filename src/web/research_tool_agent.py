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
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET
from typing import Any, Callable, Mapping

from src.web.link_discovery import classify_page, extract_candidates, question_terms, rank_candidates
from src.web.safe_http import get_dns_stats, host_resolves_public, reset_dns_stats, safe_fetch
from src.web.tool_evidence import _public_url


TOOLS = {"search", "feed", "read_page", "follow", "finish"}
SYSTEM = (
    "You are a bounded research tool agent. Decide the SINGLE next action toward "
    "answering the user's question, learning from previous observations. "
    'Return JSON only: {"tool":"search","query":"<keywords>","reason":"..."} OR '
    '{"tool":"feed","url":"<rss/atom url>","reason":"..."} OR '
    '{"tool":"follow","url":"<confirmed page>","reason":"..."} OR '
    '{"tool":"read_page","url":"<http(s)>","reason":"..."} OR '
    '{"tool":"finish","reason":"..."}. '
    "Use feed to discover article links from an RSS/Atom feed; if a discovered page is "
    "only a hub/home/navigation page, use follow to list its same-site article links and "
    "then read the specific article; never treat a hub page as the answer; do not repeat a "
    "failed action; one action per turn. A page you read is exploratory and does not prove any fact. "
            "Prefer reading a specific article URL that a search already returned; only follow a "
            "hub/home/navigation page when the search returned no suitable specific article. "
            "Search results and follow links are labelled [article|category|home|uncertain]: read "
            "[article] targets first. A follow answers with up to ten ranked same-site links and "
            "never fetches them; spend one action per page you actually need, and if the first "
            "layer only holds a category that matches the question, follow that category once "
            "more before reading the article. Do not repeat a query or a page you already used."
)


def parse_feed(payload: str, *, limit: int = 10) -> list[dict[str, str]]:
    """Extract (title, url) from RSS <item> or Atom <entry>; stdlib only.

    Raises ``ValueError('invalid_feed_xml')`` on malformed XML so a non-feed body
    is distinguished from a valid-but-empty feed.
    """
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise ValueError("invalid_feed_xml") from exc
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
    if tool == "follow":
        url = str(raw.get("url") or "").strip()
        if not _public_url(url):
            raise ValueError("action_private_url")
        return {"tool": "follow", "url": url, "reason": reason}
    return {"tool": "finish", "reason": reason}


def _prompt(question: str, observations: list[str],
            reliable_sources: tuple[str, ...] = (),
            state: str = "") -> list[dict[str, str]]:
    context: dict[str, Any] = {
        "question": question,
        "observations": observations[-6:],
        "instruction": SYSTEM,
    }
    if state:
        context["budget_state"] = state
    if reliable_sources:
        context["reliable_sources"] = [
            {"url": url, "basis": "registry_seed"} for url in reliable_sources
        ]
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
    registry_sources: tuple[tuple[str, str], ...] = (),
    sub_goals: tuple[tuple[str, tuple[str, ...]], ...] = (),
    entry_selection: bool = True,
    assessment_feedback: bool = True,
    capture_full_text: bool = False,
    monotonic: Callable[[], float] = time.monotonic,
    should_cancel: Callable[[], bool] = lambda: False,
) -> dict[str, Any]:
    budget = budget or AgentBudget()
    started = monotonic()
    deadline = started + budget.hard_seconds
    reset_dns_stats()  # per-run DoH cache + counters
    calls: list[dict[str, Any]] = []
    observations: list[str] = []
    searches = reads = 0
    searched_queries: set[str] = set()
    visited: set[str] = set()
    read_pages: dict[str, int] = {}
    body_fingerprints: dict[str, str] = {}
    coverage_log: list[dict[str, Any]] = []
    covered_terms: set[str] = set()
    goal_terms = question_terms(question)
    # Sub-goals are supplied (frozen per task) rather than auto-extracted, so the
    # state never invents meta-words like 什么/分别. Each entry is (label, terms).
    goal_specs = {label: tuple(terms) for label, terms in sub_goals}
    sub_goal_state: dict[str, dict[str, Any]] = {
        label: {"status": "missing", "url": "", "excerpt": ""} for label in goal_specs
    }
    bodies: list[dict[str, Any]] = []
    # Only URLs confirmed by an actual search result (or supplied up front) may be
    # read; a model-guessed URL is recorded as pending, never fetched. Registry
    # seeds are confirmed as ``registry_seed`` (distinct from search/initial).
    reliable_sources: tuple[str, ...] = tuple(
        url for _, url in registry_sources if _public_url(url)
    )
    confirmed: set[str] = set()
    confirmed_basis: dict[str, str] = {}
    feed_links: dict[str, str] = {}
    # URL -> exclusion reason for the CURRENT question. ``confirmed`` proves a URL was
    # reliably DISCOVERED; it does not prove it fits the goal. These are separated: a
    # feed entry excluded for this goal stays readable-by-no-one here even if another
    # source later confirms the same URL (see the read_page gate below).
    entry_exclusions: dict[str, str] = {}
    url_admission: dict[str, str] = {}  # url -> search admission (allow/explore)
    seen_links: set[str] = set()
    follow_provenance: dict[str, str] = {}
    source_chain: list[dict[str, str]] = []
    for _url in initial_urls:
        if _public_url(_url):
            confirmed.add(_url)
            confirmed_basis.setdefault(_url, "initial_urls")
    for _url in reliable_sources:
        confirmed.add(_url)
        confirmed_basis.setdefault(_url, "registry_seed")
    stop = "round_limit"
    for rnd in range(budget.max_rounds):
        if should_cancel():
            stop = "cancelled"
            break
        if monotonic() >= deadline:
            stop = "budget_exhausted"
            break
        missing_terms = [term for term in sorted(goal_terms) if term not in covered_terms][:5]
        unread_candidates = [url for url in confirmed if url not in read_pages]
        budget_state = ("round %d/%d | searches %d/%d (left %d) | reads %d/%d (left %d) | %ds left"
                        " | read pages: %d | unread candidates: %d"
                        " | still uncovered (term check, hint only): %s"
                        % (rnd + 1, budget.max_rounds,
                           searches, budget.max_searches, max(0, budget.max_searches - searches),
                           reads, budget.max_reads, max(0, budget.max_reads - reads),
                           max(0, int(deadline - monotonic())),
                           len(read_pages), len(unread_candidates),
                           ", ".join(missing_terms) if missing_terms else "(none)"))
        if goal_specs:
            pending = [label for label, st in sub_goal_state.items() if st["status"] == "missing"]
            budget_state += (
                "\n  sub-goals explored %d/%d | still to verify: %s"
                "\n  next step: target the missing sub-goals - search for their specific terms or"
                " follow a confirmed category page; do not repeat the whole question, re-read a"
                " page, or guess an unconfirmed URL"
                % (len(goal_specs) - len(pending), len(goal_specs),
                   ", ".join(pending) if pending else "(none)"))
        try:
            raw = completion(
                messages=_prompt(question, observations, reliable_sources, state=budget_state),
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
            # A completion claim is audited before it is recorded: unfinished coverage is
            # reported as unfinished instead of being presented as completion. This grants
            # no publication authority (Evidence Gate and RP-1 stay untouched).
            missing_terms = [term for term in sorted(goal_terms) if term not in covered_terms]
            pending_goals = [label for label, st in sub_goal_state.items()
                             if st["status"] == "missing"]
            call["coverage_audit"] = {
                "covered": sorted(covered_terms),
                "missing": missing_terms,
                "read_pages": len(read_pages),
                "sub_goals": {label: {"status": st["status"], "url": st["url"],
                                      "excerpt": str(st["excerpt"])[:200]}
                              for label, st in sub_goal_state.items()},
                "pending_sub_goals": pending_goals,
            }
            if pending_goals or (not goal_specs and missing_terms):
                unresolved = pending_goals or missing_terms
                stop = "finished_incomplete"
                call["result"] = {"status": "finished_incomplete", "missing": unresolved}
                observations.append(
                    "round %d: finish recorded, but the coverage audit still misses: %s"
                    % (rnd, ", ".join(unresolved))
                )
            else:
                stop = "finished"
                call["result"] = {"status": "finished_complete"}
            calls.append(call)
            break
        if action["tool"] == "search":
            if searches >= budget.max_searches:
                call["result"] = {"status": "quota_exceeded", "reason": "search_quota"}
                observations.append(f"round {rnd}: search quota reached.")
                calls.append(call)
                continue
            normalised_query = " ".join(action["query"].split()).casefold()
            if normalised_query in searched_queries:
                call["result"] = {"status": "duplicate_search", "reason": "query_already_issued"}
                observations.append(
                    f"round {rnd}: search '{action['query']}' was already issued; reuse those "
                    "results or use a materially different query."
                )
                calls.append(call)
                continue
            searched_queries.add(normalised_query)
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
                    confirmed_basis.setdefault(url, "search_result")
                    if entry_selection:
                        from src.web.research.entry_selection import search_admission

                        adm = search_admission(str(r.get("title") or ""),
                                               str(r.get("snippet") or ""), question)
                        url_admission[url] = adm["decision"]
                        if adm["decision"] == "refuse":
                            entry_exclusions[url] = "search_" + adm["reason"]
            call["result"] = {"status": result.get("status"), "reason": result.get("reason"),
                              "n": len(rows), "urls": [r.get("url") for r in rows]}
            call["search_diag"] = {k: result.get(k) for k in
                                   ("status", "reason", "providers_attempted", "provider_errors")
                                   if k in result}
            page_types = [
                classify_page(str(r.get("url") or ""), str(r.get("title") or ""),
                              str(r.get("snippet") or ""))
                for r in rows
            ]
            brief = "\n".join(
                f"- [{ptype}] {r.get('title')} | {r.get('url')} | {str(r.get('snippet'))[:160]}"
                for ptype, r in zip(page_types, rows)
            )
            if rows and "article" not in page_types:
                brief += ("\n(no [article] target among these results: read nothing yet - follow a "
                          "[category] page closest to the question, or search different terms)")
            rounds_left = max(0, budget.max_rounds - rnd - 1)
            searches_left = max(0, budget.max_searches - searches)
            if rows:
                brief += ("\n(next step: %d rounds and %d searches left - if any result above can "
                          "lead to the answer, follow or read it before searching again; search "
                          "again only when nothing above is usable)"
                          % (rounds_left, searches_left))
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
                payload = safe_fetch(action["url"], timeout=15.0, deadline=deadline)
                entries = parse_feed(payload)
                feed_status = "ok" if entries else "empty"
            except Exception as exc:  # noqa: BLE001
                entries = []
                feed_status = "unavailable"
                call["feed_error"] = type(exc).__name__
                if str(exc):
                    call["feed_reason"] = str(exc)
            for entry in entries:
                if _public_url(entry["url"]):
                    confirmed.add(entry["url"])
                    confirmed_basis.setdefault(entry["url"], "feed_entry")
                    feed_links.setdefault(entry["url"], action["url"])
            call["feed_status"] = feed_status
            call["result"] = {"status": feed_status, "n": len(entries),
                              "urls": [entry["url"] for entry in entries]}
            if entry_selection:
                from src.web.research.entry_selection import admission_map, rank_entries, select_entry

                ranked = rank_entries(entries, question)
                selected = select_entry(entries, question)
                admission = admission_map(entries, question)
                for _u, _why in admission.items():
                    if _why:
                        entry_exclusions[_u] = _why
                call["entry_selection"] = {
                    "selected": selected["entry"]["url"] if selected else "no_relevant_entry",
                    "eligible": [u for u, why in admission.items() if not why],
                    "excluded": {u: why for u, why in admission.items() if why},
                    "ranked": [
                        {"title": row["entry"]["title"], "score": row["score"],
                         "reasons": row["reasons"], "excluded": row["excluded"]}
                        for row in ranked[:10]
                    ],
                }
                brief = "\n".join(
                    f"- [{row['score']}] {row['entry']['title']} | {row['entry']['url']}"
                    + (f" | reasons={','.join(row['reasons'])}" if row["reasons"] else "")
                    + (f" | EXCLUDED:{row['excluded']}" if row["excluded"] else "")
                    for row in ranked[:10]
                )
                note = "" if selected else "\n(no_relevant_entry: no title matches the question's goal)"
            else:
                brief = "\n".join(f"- {entry['title']} | {entry['url']}" for entry in entries)
                note = ""
            observations.append(
                f"round {rnd}: feed '{action['url']}' ->\n{brief or '(no entries)'}{note}"
            )
            calls.append(call)
            continue
        if action["tool"] == "follow":
            # Bounded in-page discovery: ONE fetch of a CONFIRMED page, then every same-site
            # link is parsed (lxml), classified and ranked by relevance to the question.
            # Children are never fetched here; the model must read a target explicitly.
            from src.web.safe_http import safe_fetch_result

            url = action["url"]
            if url in visited:
                call["result"] = {"status": "already_visited", "reason": "page_seen_before"}
                observations.append(
                    f"round {rnd}: follow rejected: {url} was already visited; use a link "
                    "discovered there, or read a target you have not opened."
                )
                calls.append(call)
                continue
            if url not in confirmed:
                call["result"] = {"status": "pending_url_confirmation", "reason": "url_not_from_search_result"}
                observations.append(f"round {rnd}: follow rejected: {url} was not confirmed.")
                calls.append(call)
                continue
            if reads >= budget.max_reads:
                call["result"] = {"status": "quota_exceeded", "reason": "read_quota"}
                observations.append(f"round {rnd}: follow/read quota reached.")
                calls.append(call)
                continue
            if not host_resolves_public(urlsplit(url).hostname or ""):
                call["result"] = {"status": "blocked_unsafe_target", "reason": "host_not_public"}
                observations.append(f"round {rnd}: follow rejected: {url} resolves to a non-public address.")
                calls.append(call)
                continue
            reads += 1
            try:
                res = safe_fetch_result(url, timeout=min(8.0, max(0.5, deadline - monotonic())),
                                        max_bytes=300_000, deadline=deadline)
                raw = res.get("content") or res.get("body") or res.get("text") or ""
                html = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
            except Exception as exc:  # noqa: BLE001
                html = ""
                call["follow_error"] = type(exc).__name__
            try:
                candidates = extract_candidates(html, url)
            except Exception:  # noqa: BLE001 - discovery must never break the loop
                candidates = []
            links = rank_candidates(candidates, question_terms(question), limit=10)
            for link in links:
                seen_links.add(link.url)
            for link in links:
                if _public_url(link.url):
                    confirmed.add(link.url)
                    confirmed_basis.setdefault(link.url, "followed_link")
                    follow_provenance.setdefault(link.url, url)
            page_type = classify_page(url)
            call["result"] = {"status": "ok", "n": len(links), "candidates": len(candidates),
                              "page_type": page_type}
            call["links"] = [link.as_dict() for link in links]
            brief = "\n".join(
                f"- [{link.page_type} {link.score:g}] {link.anchor or '(no anchor text)'} | {link.url}"
                + (f" | section: {link.context}" if link.context else "")
                for link in links
            )
            if links and "article" not in [link.page_type for link in links]:
                brief += ("\n(no [article] link on this page: follow a [category] closest to the "
                          "question once more, instead of guessing a URL)")
            visited.add(url)
            observations.append(
                f"round {rnd}: follow '{url}' ->\n{brief or '(no same-site links found)'}"
            )
            calls.append(call)
            continue
        if action["tool"] == "read_page":
            # Goal-fit gate (deterministic, tool layer): a feed entry excluded for the
            # CURRENT question may not be read even if it is otherwise confirmed. This
            # runs BEFORE the confirmed/quota/safety checks so it cannot be bypassed by
            # another confirmation path and does not consume the read quota.
            if action["url"] in entry_exclusions:
                _why = entry_exclusions[action["url"]]
                call["result"] = {"status": "entry_not_eligible", "reason": _why}
                observations.append(
                    f"round {rnd}: read rejected: {action['url']} is not eligible for this "
                    f"goal ({_why}); pick a different entry or finish."
                )
                calls.append(call)
                continue
            if action["url"] not in confirmed:
                call["result"] = {"status": "pending_url_confirmation",
                                  "reason": "url_not_from_search_result"}
                observations.append(
                    f"round {rnd}: read rejected: {action['url']} was not confirmed by a search "
                    "result; choose a URL that appeared in the search results."
                )
                calls.append(call)
                continue
            if action["url"] in read_pages:
                # Already read successfully: refuse WITHOUT spending read quota, and say so,
                # so the previous audit's "same page read three times" cannot happen again.
                call["result"] = {"status": "already_read", "reason": "page_read_before",
                                  "chars": read_pages[action["url"]]}
                observations.append(
                    f"round {rnd}: read skipped: {action['url']} was already read successfully "
                    f"({read_pages[action['url']]} chars) and did not spend read quota; reuse that "
                    "body or pick an unread target."
                )
                calls.append(call)
                continue
            if reads >= budget.max_reads:
                call["result"] = {"status": "quota_exceeded", "reason": "read_quota"}
                observations.append(f"round {rnd}: read quota reached.")
                calls.append(call)
                continue
            if not host_resolves_public(urlsplit(action["url"]).hostname or ""):
                call["result"] = {"status": "blocked_unsafe_target", "reason": "host_not_public"}
                observations.append(
                    f"round {rnd}: read rejected: {action['url']} resolves to a non-public address."
                )
                calls.append(call)
                continue
            reads += 1
            try:
                body = gateway.read(action["url"], max_chars=6000,
                                    timeout=min(8.0, max(0.5, deadline - monotonic())))
            except Exception as exc:  # noqa: BLE001
                body = {"ok": False, "url": action["url"], "error": f"{type(exc).__name__}"}
            final_url = str(body.get("url") or action["url"])
            # Defense in depth: the reader follows its own redirects, so re-check
            # the FINAL url it reports. (Pre-connection safety inside the reader is
            # a separate slice; the production block stays until then.)
            if body.get("ok") and not _public_url(final_url):
                body = {**body, "ok": False, "error": "reader_final_url_not_public"}
            content = str(body.get("content") or body.get("readme") or "")
            call["result"] = {"ok": body.get("ok"), "chars": len(content),
                              "error": body.get("error") or body.get("error_code")}
            assessment: dict[str, Any] = {}
            if body.get("ok") and entry_selection:
                from src.web.research.entry_selection import assess_body

                assessment = assess_body(content, question)
                call["assessment"] = assessment
                call["admission"] = url_admission.get(action["url"], "")
            body_record = {"url": final_url, "ok": bool(body.get("ok")),
                           "chars": len(content), "preview": content[:600],
                           "reason": action.get("reason", ""), "assessment": assessment}
            if capture_full_text:
                # Opt-in (default off): persist the text THIS run actually read, so an
                # independent audit never has to substitute a later re-fetch for the
                # original same-run evidence.
                body_record["text"] = content
            bodies.append(body_record)
            if body.get("ok"):
                import hashlib as _hashlib

                fingerprint = _hashlib.sha256(
                    content.strip().encode("utf-8", "ignore")).hexdigest()
                duplicate_body = fingerprint in body_fingerprints
                if duplicate_body:
                    # Same text behind a different URL: no new evidence, and it must not
                    # inflate coverage. The fetch already happened, so only report it.
                    call["result"] = {**(call.get("result") or {}), "duplicate_body": True,
                                      "duplicate_of": body_fingerprints[fingerprint]}
                    observations.append(
                        f"round {rnd}: body is byte-identical to {body_fingerprints[fingerprint]} "
                        "already read; it adds no new coverage."
                    )
                body_fingerprints.setdefault(fingerprint, final_url)
                read_pages[final_url] = len(content)
                if action["url"] != final_url:
                    read_pages[action["url"]] = len(content)
                if not duplicate_body:
                    contributed = [term for term in goal_terms if term in content.lower()]
                    covered_terms.update(contributed)
                    coverage_log.append({"url": final_url, "chars": len(content),
                                         "contributed": sorted(contributed)})
                    # Targeted sub-goal tracking: a term hit is only a clue that this body
                    # may address the sub-goal; status stays "explored (unverified)".
                    low = content.lower()
                    for label, terms in goal_specs.items():
                        state = sub_goal_state[label]
                        if state["status"] == "explored":
                            continue
                        hit = next((term for term in terms if term in low), "")
                        if not hit:
                            continue
                        idx = low.find(hit)
                        state.update({
                            "status": "explored",
                            "url": final_url,
                            "excerpt": content[max(0, idx - 80):idx + 160].replace("\n", " "),
                        })
                source_chain.append({
                    "basis": confirmed_basis.get(action["url"], ""),
                    "feed_url": feed_links.get(action["url"], ""),
                    "entry_url": action["url"],
                    "read_url": final_url,
                })
            goal_note = ""
            if assessment and assessment_feedback:
                goal_note = f" [goal-match: {assessment['verdict']}"
                if assessment.get("missing"):
                    goal_note += " missing=" + ",".join(assessment["missing"])
                goal_note += "]"
            observations.append(
                f"round {rnd}: read {action['url']} ok={body.get('ok')} chars={len(content)} "
                f"error={body.get('error') or body.get('error_code') or ''}{goal_note}\n{content[:1200]}"
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
        "dns_stats": get_dns_stats(),
        "coverage_audit": {
            "covered": sorted(covered_terms),
            "missing": [term for term in sorted(goal_terms) if term not in covered_terms],
            "read_pages": len(read_pages),
            "sub_goals": {label: {"status": st["status"], "url": st["url"],
                                  "excerpt": str(st["excerpt"])[:200]}
                          for label, st in sub_goal_state.items()},
            "pending_sub_goals": [label for label, st in sub_goal_state.items()
                                  if st["status"] == "missing"],
            "complete": bool(read_pages)
            and not [label for label, st in sub_goal_state.items() if st["status"] == "missing"]
            and not [t for t in goal_terms if t not in covered_terms],
        },
        "coverage_log": coverage_log,
        "bodies": bodies,
        "calls": calls,
        "registry_sources": list(reliable_sources),
        "source_chain": source_chain,
        "publication_authority": False,
    }
