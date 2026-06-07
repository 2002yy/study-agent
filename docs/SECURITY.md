# Security

## FastAPI Local Access Guard

`src/api.py` provides a local-first API guard for the FastAPI service:

- `STUDY_AGENT_API_TOKEN` is optional. When unset, local development behavior is unchanged.
- When `STUDY_AGENT_API_TOKEN` is set, every route except `GET /health` and CORS preflight requires either `Authorization: Bearer <token>` or `X-Study-Agent-Token: <token>`.
- `STUDY_AGENT_CORS_ORIGINS` is an explicit comma-separated allowlist for browser origins such as `http://localhost:5173`.
- CORS is not opened by default. Disallowed preflight requests return `403`.
- `VITE_STUDY_AGENT_API_TOKEN` lets the React console call a protected API, but because `VITE_*` values are visible in the browser bundle, this is only a local/LAN gate, not a public internet security boundary.

## SSRF Protection

`src/news/article_fetcher.py` implements defense-in-depth against Server-Side Request Forgery on the article-fetching network path:

1. **DNS resolution check**: Resolves hostname at fetch time, rejects private/reserved IPs
2. **Redirect validation**: Custom `_SafeHTTPRedirectHandler` validates every redirect hop (max 3 hops)
3. **Blocked targets**:
   - Private IP ranges (127.0.0.0/8, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)
   - Link-local (169.254.0.0/16) and loopback (::1)
   - Internal hostnames (localhost, localhost.localdomain)
4. **Protocol restriction**: HTTP(S) only

`src/news/link_resolver.py` performs lightweight public-URL preflight checks and records blocked redirect targets, but it intentionally does not do DNS resolution because URL normalization is kept network-free. DNS/IP validation happens before real article fetches.

`src/news/url_normalizer.py` rejects parser-ambiguous or unsafe URL forms before metadata is attached:

- non-HTTP(S) schemes
- credentialed URLs
- localhost names and `.localhost`
- private, loopback, link-local, multicast, reserved, and unspecified IP literals
- short / integer / octal-looking / hex-looking IPv4 forms
- percent-encoded hostnames
- backslashes, control characters, spaces, and invalid ports
- repeated-encoded redirect targets that decode to unsafe URLs

## Secret Scanning

CI pipeline runs `detect-secrets` and fails if the scan JSON contains any unallowlisted finding under `results`. The workflow disables `KeywordDetector` to reduce noisy generic key-name matches, while retaining detector plugins such as:

- GitHub personal access tokens (classic and fine-grained)
- OpenAI-style API keys
- Cloud, package-registry, chat-service, and payment-provider tokens
- Private key markers

The intentional Basic Auth-shaped URL fixture in `tests/test_url_normalizer.py` is marked with an inline allowlist comment. Local tracked-file verification on 2026-06-03 produced empty scan `results`.

## Configuration Safety

- `.env` files excluded from git via `.gitignore`
- `config/runtime_state.yaml` excluded from git (contains runtime paths)
- `memory/` excluded from git (contains learner data)
- `.env.example` serves as the single canonical config template with placeholder values only

## Safe Writer

`src/safe_writer.py` ensures file write safety:

| Mechanism | Detail |
|---|---|
| **Atomic writes** | Write to `.tmp` → replace target with retry |
| **Backup** | Automatic timestamped backup before overwrite |
| **File locking** | Retry on `PermissionError` (up to 8 attempts) |
| **Cleanup** | `try/finally` guarantees temp file cleanup |
