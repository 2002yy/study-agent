# Security

## SSRF Protection

`src/news/article_fetcher.py` implements defense-in-depth against Server-Side Request Forgery:

1. **DNS resolution check**: Resolves hostname at fetch time, rejects private/reserved IPs
2. **Redirect validation**: Custom `_SafeHTTPRedirectHandler` validates every redirect hop (max 3 hops)
3. **Blocked targets**:
   - Private IP ranges (127.0.0.0/8, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)
   - Link-local (169.254.0.0/16) and loopback (::1)
   - Internal hostnames (localhost, localhost.localdomain)
4. **Protocol restriction**: HTTP(S) only

## Secret Scanning

CI pipeline runs `detect-secrets` as a hard gate (fails on detection). Scans for:

- OpenAI / DeepSeek / OpenRouter / SiliconFlow API keys
- GitHub personal access tokens (classic and fine-grained)
- Generic `sk-`, `pk-` token patterns
- Private key markers (`.pem`, `-----BEGIN`)

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
