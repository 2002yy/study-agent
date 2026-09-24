# -*- coding: utf-8 -*-
"""§115 A3-2b: warm worker with real deadline cancellation.

Contract (unchanged): provider execution only - no routing, lifecycle, budget or
Evidence/Support/Gate authority. Every stdout line is flushed; run with -u.

Cancellation semantics
----------------------
Each request runs as its own task. On deadline expiry the task is cancelled and
given a short, bounded grace to unwind. A request that had to be cancelled is
treated as **potentially contaminated**: its ``(session, mode)`` crawler is
discarded rather than reused, because a half-cancelled Playwright context can
poison every later request. Boundedness beats session continuity, and the
invalidation is reported instead of hidden.

Ops
---
  {"op":"stats"}                       -> {"event":"STATS", ...}
  {"op":"shutdown"}                    -> {"event":"BYE"}
  {url, mode, timeout_ms, ...}         -> provider observation + cancellation fields
"""
import asyncio
import json
import sys
import time

T0 = time.perf_counter()
CANCEL_GRACE_MS = 800


class PdfDownloadDeadline(RuntimeError):
    """The absolute download budget expired mid-transfer."""


#: Hard cap so a hostile server cannot stream forever inside the budget.
MAX_PDF_BYTES = 100 * 1024 * 1024

#: I/O polling granularity. NOT a budget: it only bounds how long one blocking
#: read may hold the loop before the absolute deadline is re-checked.
IO_QUANTUM_SECONDS = 0.25

#: Set to log per-chunk timing (diagnostics only, never used for control).
DIAG_ENV = "CRAWL4AI_PDF_DIAG"


def _bounded_pdf_fetch(url: str, timeout_ms: int) -> str:
    """Download a PDF under an **absolute** deadline; return a local path.

    The budget is ``deadline_at = monotonic() + timeout_ms`` and is the single
    authority. Every iteration re-checks it, pins the socket timeout to
    ``min(remaining, IO_QUANTUM_SECONDS)`` and reads a *partial* chunk, so a
    slow-but-steady or fully stalled peer cannot outlive the budget.

    Raises :class:`PdfDownloadDeadline` on expiry, after removing the partial
    file and closing the response, so nothing downstream can consume it.
    """

    if not url.startswith(("http://", "https://")):
        return url
    import os as _os
    import tempfile
    import time as _time
    import urllib.error
    import urllib.request

    deadline_at = _time.monotonic() + max(0.5, timeout_ms / 1000.0)
    diag = bool(_os.getenv(DIAG_ENV))
    started = _time.monotonic()

    def _remaining() -> float:
        return deadline_at - _time.monotonic()

    handle = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    path = handle.name
    response = None
    total = 0
    try:
        try:
            request = urllib.request.Request(url)
            response = urllib.request.urlopen(  # noqa: S310
                request, timeout=max(0.5, _remaining())
            )
            expected = 0
            try:
                expected = int(response.headers.get("Content-Length") or 0)
            except Exception:
                expected = 0
            if diag:
                print(
                    f"[pdf] start remaining={_remaining() * 1000:.0f}ms "
                    f"content_length={expected}",
                    file=sys.stderr,
                    flush=True,
                )
            while True:
                remaining = _remaining()
                if remaining <= 0:
                    raise PdfDownloadDeadline("pdf_download_deadline")
                quantum = min(remaining, IO_QUANTUM_SECONDS)
                try:
                    response.fp.raw._sock.settimeout(quantum)  # type: ignore[union-attr]
                except Exception:
                    pass
                try:
                    chunk = response.read1(4096)
                except (TimeoutError, OSError) as exc:
                    # a quantum expiry is the polling mechanism working, not a
                    # transport failure: loop and re-check the ABSOLUTE deadline
                    if _remaining() <= 0:
                        raise PdfDownloadDeadline('pdf_download_deadline') from exc
                    continue
                if diag:
                    print(
                        f"[pdf] t={(_time.monotonic() - started) * 1000:.0f}ms "
                        f"remaining={_remaining() * 1000:.0f}ms got={len(chunk)}",
                        file=sys.stderr,
                        flush=True,
                    )
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_PDF_BYTES:
                    raise PdfDownloadDeadline("pdf_download_too_large")
                handle.write(chunk)
                if _remaining() <= 0:
                    raise PdfDownloadDeadline("pdf_download_deadline")
        except PdfDownloadDeadline:
            raise
        except (urllib.error.URLError, TimeoutError, OSError):
            # a transport failure is the provider strategy's business - but the
            # partial file is ours and must not be left behind
            handle.close()
            try:
                _os.unlink(path)
            except Exception:
                pass
            return url
    except PdfDownloadDeadline:
        if response is not None:
            try:
                response.close()
            except Exception:
                pass
        handle.close()
        try:
            _os.unlink(path)
        except Exception:
            pass
        raise
    finally:
        if response is not None:
            try:
                response.close()
            except Exception:
                pass
    handle.close()
    return path



DIAG_ENV = "CRAWL4AI_TIMEOUT_DIAG"
_TL: dict[str, float] = {}


def _tl(mark: str) -> None:
    """Record a monotonic timeline mark (diagnostics only)."""

    import os as _os
    import time as _t

    if _os.getenv(DIAG_ENV):
        _TL[mark] = _t.monotonic()
        base = _TL.get("T0_request_begin", _TL[mark])
        # print EVERY mark immediately, to stderr (stdout is the JSON IPC channel)
        print(f"[tl] {mark}=+{(_TL[mark] - base) * 1000:.0f}ms", file=sys.stderr, flush=True)


def emit(payload):
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()
    if payload.get("request_id"):
        print(f"[W] W5_response_written rid={payload.get('request_id')}",
              file=sys.stderr, flush=True)


class Worker:
    def __init__(self):
        self.crawlers = {}        # (session, mode) -> started AsyncWebCrawler
        self.timeouts = 0
        self.invalidations = 0
        self.completed = 0

    def key_for(self, session_id, mode):
        base = f"session:{session_id}" if session_id else "anon"
        return f"{base}|{mode}"

    async def crawler_for(self, key, mode):
        crawler = self.crawlers.get(key)
        if crawler is not None:
            return crawler
        from crawl4ai import AsyncWebCrawler

        if mode == "pdf":
            from crawl4ai.processors.pdf import PDFCrawlerStrategy

            crawler = AsyncWebCrawler(crawler_strategy=PDFCrawlerStrategy(), verbose=False)
        else:
            crawler = AsyncWebCrawler(verbose=False)
        await crawler.start()
        self.crawlers[key] = crawler
        return crawler

    async def invalidate(self, key):
        """Drop a potentially contaminated crawler; it is rebuilt on demand."""

        crawler = self.crawlers.pop(key, None)
        self.invalidations += 1
        if crawler is None:
            return False
        try:
            await asyncio.wait_for(crawler.close(), timeout=CANCEL_GRACE_MS / 1000.0)
        except Exception:
            pass
        return True

    async def execute(self, request):
        from crawl4ai import CrawlerRunConfig, CacheMode

        url = str(request.get("url") or "")
        mode = str(request.get("mode") or "browser")
        timeout_ms = int(request.get("timeout_ms") or 30000)
        max_chars = int(request.get("max_chars") or 20000)
        cache_mode = str(request.get("cache_mode") or "BYPASS")
        session_id = request.get("session_id") or None
        key = self.key_for(session_id, mode)
        crawler = await self.crawler_for(key, mode)

        if mode == "pdf":
            from crawl4ai.processors.pdf import PDFContentScrapingStrategy

            # §119 4: the provider's PDF strategy downloads inside a blocking
            # thread whose cancellation does not stop the socket, so the worker
            # fetches with its own deadline-bounded client first and hands the
            # strategy a local path. Provider-native extraction is unchanged.
            try:
                local = await asyncio.to_thread(_bounded_pdf_fetch, url, timeout_ms)
            except PdfDownloadDeadline as exc:
                _tl("T2_pdf_deadline_raised")
                return {
                    "provider_success": False,
                    "status_code": None,
                    "content": "",
                    "content_chars": 0,
                    "error_message": str(exc),
                    "session_key": key,
                    "deadline_hit": True,
                }
            config = CrawlerRunConfig(
                scraping_strategy=PDFContentScrapingStrategy(),
                cache_mode=getattr(CacheMode, cache_mode),
                page_timeout=timeout_ms,
            )
            url = local
        else:
            kwargs = {
                "cache_mode": getattr(CacheMode, cache_mode),
                "page_timeout": timeout_ms,
            }
            if session_id:
                kwargs["session_id"] = session_id
            if request.get("delay_ms"):
                kwargs["delay_before_return_html"] = float(request["delay_ms"]) / 1000.0
            config = CrawlerRunConfig(**kwargs)

        result = await crawler.arun(url=url, config=config)
        content = result.markdown or ""
        return {
            "provider_success": bool(result.success),
            "status_code": result.status_code,
            "content": content[:max_chars],
            "content_chars": len(content),
            "error_message": str(getattr(result, "error_message", "") or "")[:200],
            "session_key": key,
        }

    async def handle(self, request):
        timeout_ms = int(request.get("timeout_ms") or 30000)
        request_id = str(request.get("request_id") or "")
        session_id = request.get("session_id") or None
        mode = str(request.get("mode") or "browser")
        key = self.key_for(session_id, mode)

        started = time.perf_counter()
        _TL.clear()
        _tl("T0_request_begin")
        _tl("T0b_worker_deadline_armed")
        task = asyncio.create_task(self.execute(request))
        _tl("T1_task_created")
        provider_cancelled = False
        crawler_invalidated = False
        provider_stopped = True

        try:
            payload = await asyncio.wait_for(asyncio.shield(task), timeout_ms / 1000.0)
            payload["deadline_hit"] = False
        except asyncio.TimeoutError:
            _tl("T1_worker_deadline_fired")
            self.timeouts += 1
            task.cancel()
            _tl("T2_task_cancel_requested")
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=CANCEL_GRACE_MS / 1000.0)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                pass
            _tl("T4_task_cancelled_or_done")
            provider_cancelled = True
            provider_stopped = task.done()
            # potentially contaminated: never reuse this crawler
            _tl("T3_invalidate_enter")
            crawler_invalidated = await self.invalidate(key)
            _tl("T4_invalidate_exit")
            payload = {
                "provider_success": False,
                "status_code": None,
                "content": "",
                "content_chars": 0,
                "error_message": "deadline_expired",
                "session_key": key,
                "deadline_hit": True,
            }
        except Exception as exc:  # noqa: BLE001
            payload = {
                "provider_success": False,
                "status_code": None,
                "content": "",
                "content_chars": 0,
                "error_message": f"{type(exc).__name__}: {exc}"[:200],
                "session_key": key,
                "deadline_hit": False,
            }

        self.completed += 1
        actual_ms = round((time.perf_counter() - started) * 1000.0, 1)
        # §123: echo the correlation id so the bridge never pairs by line order
        payload["request_id"] = request_id
        _tl("T7_response_written")
        payload["cancellation"] = {
            "requested_deadline_ms": timeout_ms,
            "cancel_grace_ms": CANCEL_GRACE_MS,
            "actual_return_ms": actual_ms,
            "provider_cancelled": provider_cancelled,
            "provider_task_done": bool(provider_stopped),
            "crawler_invalidated": crawler_invalidated,
        }
        return payload


async def main():
    worker = Worker()
    import crawl4ai  # noqa: F401  (warm the import before READY)

    await worker.crawler_for("warmup|browser", "browser")

    # §127: only crawl execution is serialized; the control plane stays live.
    crawl_slot = asyncio.Semaphore(1)
    stdout_lock = asyncio.Lock()
    tasks: set = set()
    counters = {"active_crawls": 0, "max_active_crawls": 0, "responses": 0}

    async def emit_response(payload):
        """Serialized stdout emission (mirror of the bridge's stdin lock)."""

        payload.setdefault("request_id", "")
        line = json.dumps(payload)
        async with stdout_lock:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()
            counters["responses"] += 1
        rid = payload.get("request_id")
        if rid:
            print(f"[W] W5_response_written rid={rid}", file=sys.stderr, flush=True)

    async def handle_task(request):
        """One request's whole lifecycle; never raises into the dispatcher."""

        rid = str(request.get("request_id") or "")
        try:
            op = request.get("op")
            if op == "stats":
                await emit_response({
                    "event": "STATS",
                    "request_id": rid,
                    "completed": worker.completed,
                    "timeouts": worker.timeouts,
                    "invalidations": worker.invalidations,
                    "live_crawlers": sorted(worker.crawlers),
                    "active_crawls": counters["active_crawls"],
                    "max_active_crawls": counters["max_active_crawls"],
                })
                return
            # crawl: the ONLY serialized section
            print(f"[C] C0_accepted rid={rid}", file=sys.stderr, flush=True)
            queued_at = time.monotonic()
            print(f"[C] C1_wait_slot rid={rid}", file=sys.stderr, flush=True)
            async with crawl_slot:
                queue_wait_ms = round((time.monotonic() - queued_at) * 1000.0, 1)
                print(f"[C] C2_acquired_slot rid={rid} queue_wait_ms={queue_wait_ms}",
                      file=sys.stderr, flush=True)
                counters["active_crawls"] += 1
                counters["max_active_crawls"] = max(
                    counters["max_active_crawls"], counters["active_crawls"]
                )
                try:
                    print(f"[C] C3_execute_enter rid={rid}", file=sys.stderr, flush=True)
                    payload = await worker.handle(request)
                    print(f"[C] C4_execute_exit rid={rid}", file=sys.stderr, flush=True)
                finally:
                    counters["active_crawls"] -= 1
            print(f"[C] C5_released_slot rid={rid}", file=sys.stderr, flush=True)
            payload["request_id"] = rid
            payload["queue_wait_ms"] = queue_wait_ms
            await emit_response(payload)
            print(f"[C] C6_response_emitted rid={rid}", file=sys.stderr, flush=True)
        except Exception as exc:  # noqa: BLE001 - always answer with the id
            await emit_response({
                "provider_success": False,
                "error_message": f"{type(exc).__name__}: {exc}"[:200],
                "request_id": rid,
            })

    print("[W] W0_ready_written", file=sys.stderr, flush=True)
    emit({
        "event": "READY",
        "startup_ms": round((time.perf_counter() - T0) * 1000.0, 1),
        "cancel_grace_ms": CANCEL_GRACE_MS,
    })

    print("[W] W1_request_loop_entered", file=sys.stderr, flush=True)
    try:
        while True:
            print("[W] W2_before_readline", file=sys.stderr, flush=True)
            line = await asyncio.to_thread(sys.stdin.readline)
            print(f"[W] W3_after_readline bytes={len(line or '')}",
                  file=sys.stderr, flush=True)
            if not line:
                break
            if not line.strip():
                continue
            try:
                request = json.loads(line)
            except Exception as exc:  # noqa: BLE001
                await emit_response({"error": f"bad_json: {exc}"})
                continue
            print(f"[W] W4_parsed rid={request.get('request_id')} op={request.get('op')}",
                  file=sys.stderr, flush=True)
            if request.get("op") == "shutdown":
                # stop accepting, let outstanding work finish (bounded), then close
                if tasks:
                    await asyncio.wait(set(tasks), timeout=CANCEL_GRACE_MS / 1000.0)
                await worker.close_all()
                await emit_response({"event": "BYE", "request_id": str(request.get("request_id") or "")})
                break
            task = asyncio.create_task(handle_task(request))
            tasks.add(task)
            task.add_done_callback(tasks.discard)
            # dispatcher returns to readline immediately: no head-of-line block
    finally:
        for task in list(tasks):
            task.cancel()
        await worker.close_all()


if __name__ == "__main__":
    asyncio.run(main())
