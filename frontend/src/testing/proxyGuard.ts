/**
 * Preflight guard for the browser test server.
 *
 * Why this exists: with `HTTP_PROXY` / `HTTPS_PROXY` (or their lowercase twins) pointing at
 * a local proxy, Firefox and WebKit send requests for `127.0.0.1` through that proxy while
 * Chromium bypasses loopback by default. The proxy answers the dev-server module requests
 * with a MIME-less 404, the browser's ES-module MIME check rejects every module, React never
 * mounts, and the suite reports a blank page plus a seven second visibility timeout. None of
 * that points at the real cause.
 *
 * So the cause is checked before a browser is launched, and the run fails with one readable
 * sentence instead of a render timeout.
 *
 * Deliberately pure: no Playwright import, no network, no writes. It reads an environment
 * mapping and a list of URLs and returns a verdict, which is what makes it testable.
 */

export type ProxyVerdict = "ok" | "blocked" | "unknown";

export interface ProxyAssessment {
  verdict: ProxyVerdict;
  /** Human-readable lines for the failure message. Never contains a proxy value. */
  detail: string[];
}

export const PROXY_ENV_KEYS = [
  "HTTP_PROXY",
  "HTTPS_PROXY",
  "ALL_PROXY",
  "http_proxy",
  "https_proxy",
  "all_proxy",
] as const;

export const NO_PROXY_ENV_KEYS = ["NO_PROXY", "no_proxy"] as const;

export const PROXY_BLOCKED_MESSAGE =
  "本地 E2E 服务器可能被 HTTP 代理拦截。请为测试目标配置代理排除规则，或在本次测试进程中移除代理环境变量。";

/** Hosts that the test suite boots itself and must therefore reach directly. */
const LOOPBACK_HOSTS = new Set(["127.0.0.1", "localhost", "::1", "0.0.0.0"]);

type Env = Record<string, string | undefined>;

type Match = true | false | "unknown";

interface HostPort {
  host: string;
  port: string;
}

function splitTarget(target: string): HostPort {
  const colon = target.lastIndexOf(":");
  return { host: target.slice(0, colon), port: target.slice(colon + 1) };
}

/** Split a `NO_PROXY` entry into host + optional port, or report that we cannot. */
function splitEntry(entry: string): HostPort | null {
  const bracket = entry.match(/^\[([^\]]+)\](?::(\d+))?$/);
  if (bracket) return { host: bracket[1], port: bracket[2] ?? "" };

  const colons = (entry.match(/:/g) ?? []).length;
  if (colons === 0) return { host: entry, port: "" };
  // More than one colon outside brackets means a bare IPv6 literal, which we do not
  // pretend to interpret.
  if (colons > 1) return null;
  const { host, port } = splitTarget(entry);
  return { host, port };
}

function entryMatches(target: string, entry: string): Match {
  const normalised = entry.trim().toLowerCase();
  if (!normalised) return false;
  if (normalised === "*") return true;
  // CIDR blocks and other range syntax are outside what this guard can judge honestly.
  if (normalised.includes("/")) return "unknown";

  const { host: targetHost, port: targetPort } = splitTarget(target);
  const parsed = splitEntry(normalised);
  if (!parsed) return "unknown";
  if (parsed.port && parsed.port !== targetPort) return false;

  const host = parsed.host;
  if (host.startsWith(".")) {
    const bare = host.slice(1);
    return targetHost === bare || targetHost.endsWith(host);
  }
  if (host === targetHost) return true;
  // `example.com` also covers `a.example.com`, matching common proxy behaviour.
  return targetHost.endsWith(`.${host}`);
}

/** Keep only the loopback URLs this run actually talks to, deduplicated as `host:port`. */
export function localTestTargets(urls: readonly (string | null | undefined)[]): string[] {
  const targets = new Set<string>();
  for (const raw of urls) {
    if (!raw) continue;
    let parsed: URL;
    try {
      parsed = new URL(raw);
    } catch {
      continue;
    }
    const host = parsed.hostname.replace(/^\[|\]$/g, "").toLowerCase();
    if (!LOOPBACK_HOSTS.has(host)) continue;
    const port = parsed.port || (parsed.protocol === "https:" ? "443" : "80");
    targets.add(`${host}:${port}`);
  }
  return [...targets];
}

/** True when at least one proxy variable is set to a non-empty value. */
export function hasActiveProxy(env: Env): boolean {
  return PROXY_ENV_KEYS.some((key) => (env[key] ?? "").trim() !== "");
}

/**
 * Decide whether the ambient proxy configuration can reach the local test servers.
 *
 * `ok`      straight through: no proxy set, no local target, or every target is excluded
 * `blocked` a proxy is set and at least one local target is not excluded by `NO_PROXY`
 * `unknown` a proxy is set and the exclusion rules cannot be interpreted reliably
 */
export function assessProxyEnvironment(
  env: Env,
  urls: readonly (string | null | undefined)[],
): ProxyAssessment {
  const activeKeys = PROXY_ENV_KEYS.filter((key) => (env[key] ?? "").trim() !== "");
  if (activeKeys.length === 0) {
    return { verdict: "ok", detail: ["没有设置代理环境变量。"] };
  }

  const targets = localTestTargets(urls);
  if (targets.length === 0) {
    return { verdict: "ok", detail: ["本次运行没有本地回环目标，代理检查不适用。"] };
  }

  const rawExclusions = NO_PROXY_ENV_KEYS.map((key) => (env[key] ?? "").trim())
    .filter(Boolean)
    .join(",");
  const entries = rawExclusions ? rawExclusions.split(/[\s,]+/).filter(Boolean) : [];

  const blocked: string[] = [];
  const unknown: string[] = [];
  for (const target of targets) {
    let excluded = false;
    let undecidable = false;
    for (const entry of entries) {
      const match = entryMatches(target, entry);
      if (match === true) {
        excluded = true;
        break;
      }
      if (match === "unknown") undecidable = true;
    }
    if (excluded) continue;
    if (undecidable) unknown.push(target);
    else blocked.push(target);
  }

  const base = [
    `生效的代理变量: ${activeKeys.join(", ")}`,
    `本地目标: ${targets.join(", ")}`,
  ];
  if (blocked.length > 0) {
    return {
      verdict: "blocked",
      detail: [...base, `未被代理排除规则覆盖: ${blocked.join(", ")}`],
    };
  }
  if (unknown.length > 0) {
    return {
      verdict: "unknown",
      detail: [...base, `无法可靠判断是否被排除: ${unknown.join(", ")}`],
    };
  }
  return { verdict: "ok", detail: [...base, "全部本地目标已被 NO_PROXY 覆盖。"] };
}

/** Throw a single readable failure instead of letting the browsers hit a proxy. */
export function assertLocalProxyIsBypassed(
  env: Env,
  urls: readonly (string | null | undefined)[],
): void {
  const assessment = assessProxyEnvironment(env, urls);
  if (assessment.verdict === "ok") return;
  throw new Error([PROXY_BLOCKED_MESSAGE, ...assessment.detail].join("\n"));
}
