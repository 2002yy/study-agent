"""Known-source routing and bounded, source-anchored metadata reads.

Registry URLs are addresses to try, not fabricated search results or evidence.
Only fields actually parsed from a successful official response are publishable.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from src.news.article_extractor import decompress_transport_payload
from src.web.research.identity import resolve_identity
from src.web.research.evidence_binding import document_from_read
from src.web.research.release_date import extract_release_date


@dataclass(frozen=True)
class OfficialPlan:
    entity: str
    version: str
    urls: tuple[str, ...]


def official_plan(query: str) -> OfficialPlan | None:
    versions = re.findall(r"(?<!\d)\d+\.\d+(?:\.\d+)?(?!\d)", query)
    version = versions[0] if len(versions) == 1 else ""
    release = bool(re.search(r"发布|版本|最新|更新|变化|release|version|changelog", query, re.I))
    entities = [name for name in ("fastapi", "sqlite", "python", "opus") if re.search(rf"(?<![A-Za-z]){name}(?![A-Za-z])", query, re.I)]
    # Multi-project comparisons stay on the generic scheduler; never guess identity.
    if len(entities) == 1 and (release or entities[0] == "opus"):
        entity = entities[0]
        if entity == "fastapi":
            suffix = f"/{version}" if version else ""
            return OfficialPlan(entity, version, (f"https://pypi.org/pypi/fastapi{suffix}/json", "https://fastapi.tiangolo.com/release-notes/"))
        if entity == "sqlite":
            url = f"https://sqlite.org/releaselog/{version.replace('.', '_')}.html" if version else "https://sqlite.org/changes.html"
            return OfficialPlan(entity, version, (url,))
        if entity == "python" and version:
            # A family/latest or prerelease request cannot silently become the
            # initial stable release. Those intents require a separate planner.
            if (version.count(".") == 1 and re.search(r"最新|最近|latest|newest", query, re.I)
                    or re.search(re.escape(version) + r"(?:\.x|(?:a|b|rc)\d+)", query, re.I)):
                return None
            identity = resolve_identity(entity, version)
            if identity is None:
                return None
            exact = identity.version
            return OfficialPlan(entity, exact, (f"https://www.python.org/downloads/release/python-{exact.replace('.', '')}/",))
        if entity == "opus" and version:
            return OfficialPlan(entity, version, ("https://platform.claude.com/docs/en/models/overview",))
    identifier = re.search(r"(?:arxiv[:\s/]+|arxiv\.org/(?:abs|pdf)/)(\d{4}\.\d{4,5})(?:v\d+)?", query, re.I)
    if identifier or "attention is all you need" in query.casefold():
        paper_id = identifier.group(1) if identifier else "1706.03762"
        return OfficialPlan("arxiv", paper_id, (f"https://arxiv.org/abs/{paper_id}",))
    return None


def valid_candidate(query: str, url: str) -> bool:
    plan = official_plan(query)
    return bool(plan and url in plan.urls)


def _supported_url(url: str) -> bool:
    return bool(re.fullmatch(r"https://pypi\.org/pypi/fastapi(?:/\d+\.\d+(?:\.\d+)?)?/json", url)
                or url == "https://sqlite.org/changes.html"
                or re.fullmatch(r"https://sqlite\.org/releaselog/\d+_\d+_\d+\.html", url)
                or re.fullmatch(r"https://www\.python\.org/downloads/release/python-\d+/", url)
                or re.fullmatch(r"https://arxiv\.org/abs/\d{4}\.\d{4,5}", url)
                or url == "https://platform.claude.com/docs/en/models/overview")


class _OfficialRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).scheme != "https" or urlsplit(newurl).hostname != urlsplit(req.full_url).hostname:
            raise ValueError("official_redirect_outside_source")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _fields(url: str, payload: bytes, *, source_bindings: dict[str, Any] | None = None) -> dict[str, str]:
    if "pypi.org" in url:
        value = json.loads(payload)
        info = value.get("info") or {}
        if str(info.get("name") or "").casefold() != "fastapi":
            raise ValueError("project_identity_mismatch")
        version = str(info.get("version") or "")
        if not re.fullmatch(r"\d+\.\d+\.\d+", version):
            raise ValueError("invalid_release_version")
        rows = (value.get("releases") or {}).get(version) or value.get("urls") or []
        dates = sorted(str(row.get("upload_time_iso_8601") or "") for row in rows
                       if not row.get("yanked") and row.get("upload_time_iso_8601"))
        fields = {"project": "FastAPI", "version": version}
        if dates:
            fields["distribution_uploaded_at"] = dates[0]  # package upload, not a fabricated release announcement
        return fields
    from lxml import html  # type: ignore[import-untyped]

    document = html.fromstring(payload)
    if "sqlite.org" in url:
        headings = document.xpath("//h3" if url.endswith("changes.html") else "//h2")
        if not headings:
            raise ValueError("missing_release_heading")
        heading = headings[0]
        match = re.search(r"(\d{4}-\d{2}-\d{2})\s*\((\d+\.\d+\.\d+)\)", heading.text_content())
        if not match:
            explicit = re.search(r"SQLite Release (\d+\.\d+\.\d+) On (\d{4}-\d{2}-\d{2})", heading.text_content())
            if explicit:
                match = re.match(r"(.+)\|(.+)", explicit[2] + "|" + explicit[1])
        if not match:
            raise ValueError("invalid_release_heading")
        changes: list[str] = []
        for sibling in heading.itersiblings():
            if sibling.tag in {"h2", "h3"}:
                break
            if sibling.tag == "ol":
                changes.extend(" ".join(item.text_content().split()) for item in sibling.xpath("./li"))
                break  # don't include the following hashes/previous release
        fields = {"project": "SQLite", "version": match[2], "release_date": match[1]}
        if changes:
            fields["changes"] = "\n".join(changes)
        return fields
    if "python.org" in url:
        titles = document.xpath("//h1")
        match = re.search(r"Python (\d+\.\d+\.\d+)", titles[0].text_content() if titles else "")
        if not match or urlsplit(url).path != f"/downloads/release/python-{match[1].replace('.', '')}/":
            raise ValueError("python_release_identity_mismatch")
        fields = {"project": "Python", "version": match[1]}
        identity = resolve_identity("python", match[1])
        if identity is None:
            raise ValueError("python_release_identity_mismatch")
        read_document = document_from_read(hashlib.sha256(payload).hexdigest(), url, payload)
        bound_date = extract_release_date(read_document, identity)
        if bound_date:
            fields["release_date"] = bound_date.value
            if source_bindings is not None:
                proposal = bound_date.binding.proposal
                start, end = proposal.heading_span
                source_bindings["release_date"] = {
                    "kind": "verified_version_heading", "product": identity.product, "version": identity.version,
                    "url": url, "read_id": proposal.read_id,
                    "source_content_sha256": proposal.content_sha256,
                    "decoded_payload_sha256": bound_date.binding.payload_sha256,
                    "heading_span": list(proposal.heading_span), "heading_quote": read_document.text[start:end],
                    "source_span": list(proposal.evidence_span), "quote": proposal.quote,
                }
        return fields
    if "arxiv.org" in url:
        def meta(name: str) -> list[str]:
            return [str(tag.get("content") or "").strip() for tag in document.xpath(f"//meta[@name='{name}']")
                    if tag.get("content")]
        titles, authors, dates = meta("citation_title"), meta("citation_author"), meta("citation_date")
        if not titles:
            raise ValueError("paper_metadata_missing")
        paper_ids = meta("citation_arxiv_id")
        if paper_ids and paper_ids[0].split("v", 1)[0] != url.rsplit("/", 1)[1]:
            raise ValueError("paper_identity_mismatch")
        fields = {"paper_id": url.rsplit("/", 1)[1], "title": titles[0]}
        if authors:
            fields["authors"] = "; ".join(authors)
        # First submission comes from the submission-history record, not an update date.
        history = document.xpath("//*[contains(concat(' ', normalize-space(@class), ' '), ' submission-history ')]")
        first = re.search(r"\[v1\]\s*([^\n]+)", history[0].text_content() if history else "")
        if first:
            fields["first_submission"] = first[1].strip()
        elif dates:
            fields["citation_date"] = dates[0]
        return fields
    # A models overview may contain many versions. It is never an exact-version payload.
    raise ValueError("model_overview_requires_version_scoped_reader")


def verified_python_identity(plan: OfficialPlan, url: str, result: dict[str, Any]) -> bool:
    """Reader-owned official fields, not a candidate/LLM identity flag."""
    if plan.entity != "python" or url not in plan.urls or result.get("method") != "official_metadata_http_v2":
        return False
    if urlsplit(str(result.get("url") or "")).hostname != "www.python.org":
        return False
    body = str(result.get("content") or "")
    if hashlib.sha256(body.encode()).hexdigest() != result.get("content_sha256"):
        return False
    fields = {item.get("field"): item.get("value") for item in result.get("official_fields") or []
              if type(item.get("start")) is int and type(item.get("end")) is int
              and 0 <= item["start"] < item["end"] <= len(body)
              and body[item["start"]:item["end"]] == f"{item.get('field')}: {item.get('value')}"}
    requested = resolve_identity(plan.entity, plan.version)
    observed = resolve_identity(str(fields.get("project") or ""), str(fields.get("version") or ""))
    return requested is not None and observed == requested and result.get("source_version") == observed.version


def read_official_metadata(url: str, *, timeout: float, max_chars: int) -> dict[str, Any] | None:
    if not _supported_url(url):
        return None
    try:
        opener = build_opener(_OfficialRedirect())
        with opener.open(Request(url, headers={"User-Agent": "StudyAgent/official-metadata-v2", "Accept-Encoding": "identity"}), timeout=max(0.1, min(timeout, 10))) as response:
            payload = response.read(2_000_001)
            if len(payload) > 2_000_000:
                raise ValueError("official_payload_limit")
            final_url = response.url
            raw_digest = hashlib.sha256(payload).hexdigest()
            payload = decompress_transport_payload(payload, response.headers.get("Content-Encoding", ""))
        source_bindings: dict[str, Any] = {}
        fields = _fields(url, payload, source_bindings=source_bindings)
        content = "\n".join(f"{key}: {value}" for key, value in fields.items())
        if len(content) > max_chars:
            raise ValueError("official_normalized_body_limit")
        spans = []
        for key, value in fields.items():
            quote = f"{key}: {value}"
            start = content.index(quote)
            spans.append({"field": key, "value": value, "start": start, "end": start + len(quote)})
            if key in source_bindings:
                spans[-1]["source_binding"] = source_bindings[key]
        return {"ok": True, "url": final_url, "method": "official_metadata_http_v2", "content": content,
                "content_sha256": hashlib.sha256(content.encode()).hexdigest(), "transport_sha256": raw_digest,
                "official_fields": spans, "source_version": fields.get("version") or fields.get("paper_id") or ""}
    except Exception as exc:
        return {"ok": False, "url": url, "error": "official_metadata_unavailable", "error_code": type(exc).__name__}
