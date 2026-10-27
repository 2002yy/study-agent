/**
 * The browser's API token.
 *
 * The token must never be compiled into the bundle: a build-time value is a
 * public credential, and the server rejects every private request without it.
 * The operator pastes the server's `STUDY_AGENT_API_TOKEN` once in the app's
 * settings; it is kept in this browser only and sent as a request header.
 *
 * One module owns that resolution so the ten call sites cannot drift into
 * reading a build-time environment variable again.
 */

const STORAGE_KEY = "study-agent-api-token";

// Browsers with storage disabled, and test environments without a DOM, still
// need a working session: the token then lives for this process only.
let sessionToken = "";

function storage(): Storage | null {
  try {
    const candidate = (globalThis as { localStorage?: Storage }).localStorage;
    return candidate ?? null;
  } catch {
    return null;
  }
}

export function apiToken(): string {
  try {
    const stored = storage()?.getItem(STORAGE_KEY);
    if (typeof stored === "string" && stored.trim()) return stored.trim();
  } catch {
    // Fall through to the session value.
  }
  return sessionToken;
}

export function setApiToken(token: string): void {
  const value = token.trim();
  sessionToken = value;
  try {
    const target = storage();
    if (!target) return;
    if (value) target.setItem(STORAGE_KEY, value);
    else target.removeItem(STORAGE_KEY);
  } catch {
    // Storage can be unavailable (private mode, disabled cookies). The session
    // value above still works until this page is closed.
  }
}

export function authHeaders(): Record<string, string> {
  const token = apiToken();
  return token ? { "X-Study-Agent-Token": token } : {};
}
