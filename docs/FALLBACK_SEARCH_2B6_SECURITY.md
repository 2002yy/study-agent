# B-Search-2B6 (part 1) — SSRF: pin the connection to the validated IP

Base `95f211d2`. Security-only slice. RP-1 NO-GO.

## The gap (user-identified)
`safe_fetch` resolved the host with `getaddrinfo`, checked it was public, then let
`urllib` **re-resolve and connect** — so a DNS change between the check and the
connection (rebinding) was not covered. `read_page` only checked the host string
before `gateway.read` (which may follow its own redirects).

## Fix
- `_resolve_public_ips(host)`: resolve once, require **every** address to be a global
  IP; return the validated IPs.
- `_http_get_pinned(url, host, ip)`: connect **to the validated IP** (no
  re-resolution), keeping the real host for the `Host` header and TLS SNI/cert via
  `ssl.wrap_socket(server_hostname=host)`.
- `safe_fetch`: for **every** redirect hop, validate scheme + `_public_url` +
  resolve+validate IP **before** connecting, and connect to that pinned IP. A hop to a
  private target is rejected **without being contacted**.
- `read_page` keeps the `host_resolves_public` guard before `gateway.read`.

## Tests (11 PASS; ruff PASS; mypy file Success)
- `test_safe_fetch_rejects_private_dns_without_requesting` — resolution failure ⇒
  `_http_get_pinned` never called.
- `test_safe_fetch_never_contacts_private_redirect_target` — a 302 to
  `http://127.0.0.1/...` ⇒ only the first (public) hop is requested.
- `test_read_page_blocked_when_host_not_public` — read of a non-public host ⇒
  `blocked_unsafe_target`, `gateway.read` never called.

This narrows the check→connect race but is a prototype; a full SSRF review is still
open (see below).

## Still open from the 2B6 contract (not done here)
1. `gateway.read`'s own redirect handling is outside this change → add a redirect
   guard there before production.
2. Identity chain `source_id → feed → entry → read_page` (and
   `registry_seed`/`initial_urls`/`search_result`) not yet preserved end-to-end.
3. Exp3 (registry source unreachable/invalid): `unavailable` vs `empty` distinction
   and failure recording still to add.

## Superseding direction (registry scale)
The earlier “≤3 curated feeds” plan is **superseded**: build a **scalable source
directory**, not hardcoded feeds:
- reuse external OPML/RSSHub directories (catalog candidates, don’t scrape all),
- local index (themes/language/url/availability), recall 1–3 per question,
- four separated states: `cataloged / verified_available / read / evidence_trusted`,
- model picks from a **small recalled set**, never thousands in the prompt,
- no increase to per-run model/network/read budgets.

That is a separate, larger slice; part 1 here is only the security fix.
