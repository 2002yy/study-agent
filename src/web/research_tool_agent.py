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

from src.web.link_discovery import (
    classify_page,
    derive_sub_goals,
    extract_candidates,
    looks_like_navigation,
    question_terms,
    rank_candidates,
    verify_goal_evidence,
)
from src.web.safe_http import get_dns_stats, host_resolves_public, reset_dns_stats, safe_fetch
from src.web.research_notebook import ResearchNotebook
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


def _rank_unread(urls: list[str], terms: set[str], basis: dict[str, str]) -> list[dict[str, str]]:
    """Order confirmed-but-unread URLs so the model can act on what it already has.

    Deterministic and cheap: more question-term hits in the URL path win, deep pages
    beat site roots, and stable bases beat exploratory ones. This only *orders* the
    candidates the run has already legitimately discovered — it grants no new access.
    """
    basis_priority = {
        "followed_link": 0, "feed_entry": 1, "search_result": 2,
        "initial_urls": 3, "registry_seed": 4,
    }

    def key(url: str) -> tuple[int, int, int, str]:
        lowered = url.casefold()
        hits = sum(1 for term in terms if term and term.casefold() in lowered)
        depth = 0 if urlsplit(lowered).path.strip("/") else 1  # 0 = deep page
        return (-hits, depth, basis_priority.get(basis.get(url, ""), 9), lowered)

    return [{"url": url, "basis": basis.get(url, "")} for url in sorted(urls, key=key)]


#: Outcomes that mean the action was refused without spending a network request.
MAX_CORRECTIONS = 2  # bounded free corrections for refused decisions

_REFUSED_OUTCOMES = frozenset({
    "duplicate_search", "already_read", "already_visited", "pending_url_confirmation",
    "quota_exceeded", "entry_not_eligible", "blocked_unsafe_target", "budget_reserved",
})


def _action_row(call: dict[str, Any]) -> dict[str, str]:
    """One line of structured action state for the model (tool, target, outcome)."""
    action = call.get("action", {})
    result = call.get("result") or {}
    outcome = str(result.get("status") or result.get("reason")
                  or ("ok" if result.get("ok") else ""))
    return {"tool": str(action.get("tool") or ""),
            "target": str(action.get("query") or action.get("url") or "")[:80],
            "outcome": outcome}


def _prompt(question: str, observations: list[str],
            reliable_sources: tuple[str, ...] = (),
            state: str = "",
            candidates: list[dict[str, str]] | None = None,
            pending_follows: list[str] | None = None,
            actions: dict[str, Any] | None = None,
            notebook: dict[str, Any] | None = None) -> list[dict[str, str]]:
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
    if candidates:
        # Already-discovered, not-yet-read targets. Reading one of these needs no new
        # search and no new confirmation, so it is the cheapest way to spend a read.
        context["confirmed_unread"] = candidates
    if pending_follows:
        # A navigation page that was read but never expanded: following it is the next
        # action, and it takes precedence over the generic "prefer an article" advice.
        context["next_follow"] = pending_follows[:3]
    if actions:
        # Structured action state (C1): what is already done, what was refused and why,
        # and which concrete actions are legal next. The model still spends a decision on
        # every attempt; only the network request is saved.
        context["action_state"] = actions
    if notebook:
        # Bounded run-local notebook: goals, best verbatim evidence, gaps, next action.
        context["research_notebook"] = notebook
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
    escalation_budget: AgentBudget | None = None,
    escalation_budgets: tuple[AgentBudget, ...] = (),
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
    # Effective limits: the run may be extended ONCE by ``escalation_budget`` (dynamic
    # tier escalation) without restarting, so these are local and mutable.
    max_rounds, max_searches, max_reads = (
        budget.max_rounds, budget.max_searches, budget.max_reads)
    escalated = False
    corrections = 0        # free corrections used, bounded by MAX_CORRECTIONS
    model_calls = 0        # every completion call, corrections included
    #: Ordered escalation chain (each entry is used at most once).
    pending_escalations = [item for item in
                           ((escalation_budget,) + tuple(escalation_budgets)) if item]
    escalations_applied: list[int] = []
    #: Per-round PROGRESS is measured in productive events, not in "a body arrived":
    #: new coverage from a genuine body, a newly discovered navigation page, or a follow
    #: that newly confirmed candidates. A duplicate or off-topic body counts for nothing.
    progress_history: list[bool] = []
    productive_events = 0
    last_productive = 0
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
    #: Per-goal evidence records: url, host, excerpt and how each verdict was reached.
    #: One body may serve several goals, but every goal keeps its own record.
    goal_evidence: dict[str, list[dict[str, Any]]] = {}
    #: Run-local notebook: caches the bodies actually read so a 20-round run can still cite
    #: its early evidence without re-fetching. Rebuilt from authoritative state each round.
    notebook = ResearchNotebook()
    #: Per-goal evidence records (url, host, excerpt, how it was verified).
    #: URLs whose read returned navigation/index content. Kept across rounds so the state
    #: can distinguish "already read, must not read again" from "not yet followed".
    navigation_urls: set[str] = set()
    coverage_log: list[dict[str, Any]] = []
    covered_terms: set[str] = set()
    goal_terms = question_terms(question)
    # Sub-goals are supplied (frozen per task) rather than auto-extracted, so the
    # state never invents meta-words like 什么/分别. Each entry is (label, terms).
    goal_specs = {label: tuple(terms) for label, terms in sub_goals}
    # C3: the real entry often supplies no sub-goals (the shadow runner passes none), so
    # the question's own clauses are split into goals. Deterministic and answer-free.
    derived_goals = () if sub_goals else derive_sub_goals(question)
    if derived_goals:
        goal_specs = {label: tuple(terms) for label, terms in derived_goals}
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
    # Slice-1 diagnostics: raw -> filtered -> shown -> confirmed -> read, per tool call.
    candidate_trace: list[dict[str, Any]] = []
    for _url in initial_urls:
        if _public_url(_url):
            confirmed.add(_url)
            confirmed_basis.setdefault(_url, "initial_urls")
    for _url in reliable_sources:
        confirmed.add(_url)
        confirmed_basis.setdefault(_url, "registry_seed")
    stop = "round_limit"
    unread_candidates: list[str] = []
    pending_follows: list[str] = []
    rnd = -1
    while True:
        if rnd + 1 >= max_rounds:
            # Dynamic escalation along an ordered chain, inside THIS run (sources, bodies,
            # goal state and history stay in scope). It requires an unresolved goal, an
            # actionable state, RECENT PROGRESS (looping must not buy budget) and time
            # still available; otherwise the run stops.
            nxt = pending_escalations[0] if pending_escalations else None
            # "Unresolved" must not depend on explicit sub-goals: the default shadow entry
            # passes none. Without them the question's own uncovered terms are the honest
            # signal - a coverage gap, never a claim that keyword hits mean completion.
            has_unresolved = (
                any(st["status"] != "supported" for st in sub_goal_state.values())
                if sub_goal_state
                else bool([t for t in goal_terms if t not in covered_terms])
            )
            recent_progress = (productive_events != last_productive
                               or any(progress_history[-3:]))
            if (nxt is not None and nxt.max_rounds > max_rounds
                    and has_unresolved
                    and (unread_candidates or pending_follows)
                    and recent_progress
                    and monotonic() < deadline):
                pending_escalations.pop(0)
                escalations_applied.append(nxt.max_rounds)
                escalated = True
                max_rounds = nxt.max_rounds
                max_searches = nxt.max_searches
                max_reads = nxt.max_reads
                deadline = started + nxt.hard_seconds
                continue
            break
        rnd += 1
        # Bounded immediate correction: a decision that was refused (duplicate or invalid)
        # does not consume a research round, at most MAX_CORRECTIONS times. The absolute
        # model-call cap still bounds the total, so repeated invalid actions cannot spiral.
        if (calls and corrections < MAX_CORRECTIONS
                and (calls[-1].get("result") or {}).get("status") in _REFUSED_OUTCOMES):
            corrections += 1
            rnd -= 1
        model_calls += 1
        if model_calls > max_rounds + MAX_CORRECTIONS:
            stop = "model_call_limit"
            break
        if rnd > 0:
            progress_history.append(productive_events != last_productive)
        last_productive = productive_events
        if should_cancel():
            stop = "cancelled"
            break
        if monotonic() >= deadline:
            stop = "budget_exhausted"
            break
        missing_terms = [term for term in sorted(goal_terms) if term not in covered_terms][:5]
        unread_candidates = [url for url in confirmed
                             if url not in read_pages and url not in entry_exclusions]
        # A navigation page that was read but never followed is the clearest next action:
        # it is NOT in the unread list (it was read) yet it must still be expanded.
        pending_follows = sorted(url for url in navigation_urls if url not in visited)
        unread_rows = _rank_unread(unread_candidates, goal_terms, confirmed_basis)[:6]
        # C1: structured action state. The model still spends a decision on every attempt -
        # the saving is the network request, never the hard round limit.
        action_rows = [_action_row(call) for call in calls]
        # Persistent readable evidence: what was already read, which goals it touched. A
        # long run must never have to re-read a page just to remember it.
        read_evidence = [
            {"url": url, "chars": chars,
             "goals": sorted(label for label, rows in goal_evidence.items()
                             if any(row["url"] == url for row in rows))}
            for url, chars in list(read_pages.items())[-5:]
        ]
        needs_evidence = [label for label, st in sub_goal_state.items()
                          if st["status"] == "missing"]
        action_state: dict[str, Any] = {
            "completed": [row for row in action_rows
                          if row["outcome"] not in _REFUSED_OUTCOMES][-6:],
            "invalid": [row for row in action_rows
                        if row["outcome"] in _REFUSED_OUTCOMES][-6:],
            "read_evidence": read_evidence,
            # Full legal choice set (read / follow / search / finish), not a page-only
            # list: a goal with no candidate still needs a new search.
            "legal_next": (
                [{"tool": "read_page", "target": row["url"]} for row in unread_rows[:4]]
                + [{"tool": "follow", "target": url} for url in pending_follows[:2]]
                + ([{"tool": "search",
                     "target": f"new query covering: {', '.join(needs_evidence[:2])}"}]
                   if needs_evidence and searches < max_searches else [])
                + [{"tool": "finish", "target": "only when every goal is settled"}]
            ),
        }
        # Run-local notebook view: bounded, rebuilt from authoritative state, no model call.
        notebook_view = notebook.build_view(
            goals=goal_specs, goal_state=sub_goal_state, goal_evidence=goal_evidence,
            refused=[row for row in action_rows if row["outcome"] in _REFUSED_OUTCOMES],
            next_action=(action_state["legal_next"][0] if action_state["legal_next"] else None))
        budget_state = ("round %d/%d | searches %d/%d (left %d) | reads %d/%d (left %d) | %ds left"
                        " | read pages: %d | unread candidates: %d"
                        " | still uncovered (term check, hint only): %s"
                        % (rnd + 1, max_rounds,
                           searches, max_searches, max(0, max_searches - searches),
                           reads, max_reads, max(0, max_reads - reads),
                           max(0, int(deadline - monotonic())),
                           len(read_pages), len(unread_candidates),
                           ", ".join(missing_terms) if missing_terms else "(none)"))
        if goal_specs:
            # Two different states, deliberately not merged: a goal with NO candidate needs
            # searching for, while a goal that was merely explored needs VERIFYING against a
            # body already in hand. `explored` is never treated as settled.
            need_evidence = [label for label, st in sub_goal_state.items()
                             if st["status"] == "missing"]
            needs_verification = [label for label, st in sub_goal_state.items()
                                  if st["status"] == "explored"]
            settled = len(goal_specs) - len(need_evidence) - len(needs_verification)
            budget_state += (
                "\n  goals supported %d/%d | needs evidence (no candidate yet): %s"
                " | has candidates, needs verification: %s"
                "\n  next step: verify the candidates you already hold before searching again;"
                " for a goal with no candidate, search for its terms or follow a confirmed"
                " category page; never repeat the whole question, re-read a page, or guess an"
                " unconfirmed URL"
                % (settled, len(goal_specs),
                   ", ".join(need_evidence) if need_evidence else "(none)",
                   ", ".join(needs_verification) if needs_verification else "(none)"))
            if need_evidence:
                hints = "; ".join(
                    f"{label} -> {', '.join(list(goal_specs[label])[:4])}"
                    for label in need_evidence[:3])
                budget_state += (
                    f"\n  MISSING goals (search for these specifically): {hints}")
        # Conditional budget reserve: instruction, not a refusal. A refusal would spend the
        # very round it is trying to save (the round loop is fixed), so once searches are
        # half spent and readable candidates already exist, the guide tells the model the
        # remaining rounds belong to follow/read. It never fires without candidates, so a
        # topic that genuinely needs more searching is not cut short.
        if searches >= 1 and unread_candidates and max_rounds - rnd <= 4:
            budget_state += (
                "\n  BUDGET: %d round(s) left - do NOT search again. This overrides the "
                "generic 'prefer an article' rule: if the run already holds a navigation/"
                "index page (see next_follow) or confirmed unread candidates, FOLLOW the "
                "navigation page to obtain its chapter links, then read_page the specific "
                "chapter, so the run reaches mechanism text instead of another list of links."
                % (max_rounds - rnd))
        try:
            raw = completion(
                messages=_prompt(question, observations, reliable_sources,
                                 state=budget_state, candidates=unread_rows,
                                 pending_follows=pending_follows, actions=action_state,
                                 notebook=notebook_view),
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
                             if st["status"] != "supported"]
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
            if searches >= max_searches:
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
            shown_urls = [str(r.get("url") or "") for r in rows]
            candidate_trace.append({
                "round": rnd, "tool": "search", "query": action.get("query"),
                "results": len(rows), "shown": shown_urls[:10],
                "excluded": [u for u in shown_urls if u in entry_exclusions],
            })
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
            rounds_left = max(0, max_rounds - rnd - 1)
            searches_left = max(0, max_searches - searches)
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
            if searches >= max_searches:
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
            if reads >= max_reads:
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
            links = rank_candidates(candidates, question_terms(question), limit=10,
                                    question=question)
            before_confirm = set(confirmed)
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
            newly_confirmed = [link.url for link in links
                               if _public_url(link.url) and link.url not in before_confirm]
            if newly_confirmed:
                productive_events += 1          # a follow that discovered something new
            candidate_trace.append({
                "round": rnd, "tool": "follow", "page": url, "page_type": page_type,
                "raw_candidates": len(candidates), "ranked": len(links),
                "shown": [link.url for link in links],
                "page_types": [link.page_type for link in links],
                # truly NEW this call, not merely "a followed link seen before"
                "newly_confirmed": newly_confirmed,
            })
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
                candidate_trace.append({
                    "round": rnd, "tool": "read_page", "url": action["url"],
                    "basis": confirmed_basis.get(action["url"], ""),
                    "confirmed": action["url"] in confirmed, "eligible": False,
                    "attempted": False, "succeeded": False,
                    "failure_reason": f"entry_not_eligible:{_why}"})
                observations.append(
                    f"round {rnd}: read rejected: {action['url']} is not eligible for this "
                    f"goal ({_why}); pick a different entry or finish."
                )
                calls.append(call)
                continue
            if action["url"] not in confirmed:
                call["result"] = {"status": "pending_url_confirmation",
                                  "reason": "url_not_from_search_result"}
                candidate_trace.append({
                    "round": rnd, "tool": "read_page", "url": action["url"],
                    "basis": "", "confirmed": False, "eligible": False,
                    "attempted": False, "succeeded": False,
                    "failure_reason": "url_not_from_search_result"})
                unread_now = _rank_unread(
                    [u for u in confirmed if u not in read_pages and u not in entry_exclusions],
                    goal_terms, confirmed_basis)[:5]
                observations.append(
                    f"round {rnd}: read rejected: {action['url']} was never discovered by a search "
                    "result or a followed page; guessing a URL is not evidence. Read one of the "
                    "confirmed, not-yet-read candidates instead"
                    + (": " + "; ".join(f"{row['url']} ({row['basis']})" for row in unread_now)
                       if unread_now else " (none left - search for a missing term)."))
                calls.append(call)
                continue
            # Slice-1 accounting: one row per read ATTEMPT, split into the distinct
            # states so "found / eligible / tried / succeeded" cannot be conflated.
            read_row: dict[str, Any] = {
                "round": rnd, "tool": "read_page", "url": action["url"],
                "basis": confirmed_basis.get(action["url"], ""),
                "confirmed": True, "eligible": True,
                "attempted": False, "succeeded": False, "failure_reason": "",
            }
            candidate_trace.append(read_row)
            if action["url"] in read_pages:
                # Already read successfully: refuse WITHOUT spending read quota, and say so,
                # so the previous audit's "same page read three times" cannot happen again.
                read_row["failure_reason"] = "page_read_before"
                call["result"] = {"status": "already_read", "reason": "page_read_before",
                                  "chars": read_pages[action["url"]]}
                if action["url"] in navigation_urls:
                    observations.append(
                        f"round {rnd}: '{action['url']}' is a KNOWN navigation page you already "
                        "read; reading it again cannot help. NEXT ACTION: follow it to obtain its "
                        "chapter links, then read_page the specific chapter."
                    )
                else:
                    observations.append(
                        f"round {rnd}: read skipped: {action['url']} was already read successfully "
                        f"({read_pages[action['url']]} chars) and did not spend read quota; reuse "
                        "that body or pick an unread target."
                    )
                calls.append(call)
                continue
            if reads >= max_reads:
                read_row["failure_reason"] = "read_quota"
                call["result"] = {"status": "quota_exceeded", "reason": "read_quota"}
                observations.append(f"round {rnd}: read quota reached.")
                calls.append(call)
                continue
            if not host_resolves_public(urlsplit(action["url"]).hostname or ""):
                read_row["failure_reason"] = "host_not_public"
                call["result"] = {"status": "blocked_unsafe_target", "reason": "host_not_public"}
                observations.append(
                    f"round {rnd}: read rejected: {action['url']} resolves to a non-public address."
                )
                calls.append(call)
                continue
            reads += 1
            read_row["attempted"] = True
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
            read_row["succeeded"] = bool(body.get("ok"))
            if not body.get("ok"):
                read_row["failure_reason"] = str(
                    body.get("error") or body.get("error_code") or "read_failed")
            # Content-level index detection: a navigation-shaped page is not mechanism
            # text, so say so instead of letting it pass as an answer.
            if body.get("ok") and looks_like_navigation(content):
                call["page_kind"] = "navigation"
                navigation_urls.add(action["url"])
                read_row["page_kind"] = "navigation"
                productive_events += 1           # navigation discovery is its own progress
                observations.append(
                    f"round {rnd}: '{action['url']}' returned navigation/index content "
                    f"({len(content)} chars), not mechanism text - it is a list of links, not "
                    f"an answer. NEXT ACTION: follow {action['url']} (a confirmed URL) to get "
                    "its chapter links, then read_page the specific chapter. Do not read this "
                    "page again."
                )
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
                # A navigation/index page must not contribute keyword coverage: its terms
                # are links, not mechanism evidence (negative control from review).
                if not duplicate_body and call.get("page_kind") != "navigation":
                    contributed = [term for term in goal_terms if term in content.lower()]
                    covered_terms.update(contributed)
                    if contributed:
                        productive_events += 1   # a genuine body that extended coverage
                    coverage_log.append({"url": final_url, "chars": len(content),
                                         "contributed": sorted(contributed)})
                    # Targeted sub-goal tracking: a term hit is only a clue that this body
                    # may address the sub-goal; status stays "explored (unverified)".
                    for label, terms in goal_specs.items():
                        state = sub_goal_state[label]
                        if state["status"] == "supported":
                            continue          # a settled goal is not re-derived
                        status, evidence = verify_goal_evidence(terms, content)
                        if status == "missing":
                            continue          # this body carries none of the goal's terms
                        goal_evidence.setdefault(label, []).append({
                            "url": final_url,
                            "host": urlsplit(final_url).hostname or "",
                            "status": status,
                            "verified_by": "terms+relation" if status == "supported"
                            else "terms_only",
                            **evidence,
                        })
                        if status == "supported":
                            state.update({"status": "supported", "url": final_url,
                                          "excerpt": evidence["excerpt"]})
                        elif state["status"] != "explored":
                            state.update({"status": "explored", "url": final_url,
                                          "excerpt": evidence["excerpt"] or ""})
                        notebook.record(action["url"], final_url, content,
                                        goals=[label])
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
                                  if st["status"] != "supported"],
            "complete": bool(read_pages)
            and not [label for label, st in sub_goal_state.items()
                     if st["status"] != "supported"]
            and not [t for t in goal_terms if t not in covered_terms],
        },
        "coverage_log": coverage_log,
        "bodies": bodies,
        "calls": calls,
        "registry_sources": list(reliable_sources),
        "escalated": escalated,
        "escalations": escalations_applied,
        # C3 provenance: which goals were derived from the question itself (empty when the
        # caller supplied them explicitly).
        "derived_sub_goals": [label for label, _terms in derived_goals],
        "goal_evidence": goal_evidence,
        "notebook_digests": {url: body.digest for url, body in notebook.bodies.items()},
        # Observability for the action-optimisation audit: wasted repeats are counted,
        # not hidden, and each escalation records the round limit it moved to.
        "repeat_actions": {
            "search": sum(1 for c in calls
                          if (c.get("result") or {}).get("status") == "duplicate_search"),
            "read": sum(1 for c in calls
                        if (c.get("result") or {}).get("status") == "already_read"),
        },
        # C1 cost accounting: model calls vs research rounds vs free corrections vs real
        # network requests vs wasted rounds. A refused decision is free only up to
        # MAX_CORRECTIONS; the model-call cap bounds the total either way.
        "cost": {
            "model_calls": model_calls,
            "research_decisions": rnd + 1,
            "corrections": corrections,
            "network_requests": sum(
                1 for c in calls
                if c["action"].get("tool") in {"search", "follow", "read_page"}
                and (c.get("result") or {}).get("status") not in _REFUSED_OUTCOMES),
            "invalid_actions": sum(
                1 for c in calls
                if (c.get("result") or {}).get("status") in _REFUSED_OUTCOMES),
        },
        "source_chain": source_chain,
        "candidate_trace": candidate_trace,
        # What the model was actually told, kept for the action audit (review request).
        "observations": observations,
        "publication_authority": False,
    }
