import { mkdirSync, rmSync } from "node:fs";
import { dirname, resolve } from "node:path";

import {
  PROXY_BLOCKED_MESSAGE,
  assertLocalProxyIsBypassed,
  hasActiveProxy,
} from "../src/testing/proxyGuard";

export const GOLDEN_JOURNEY_METRICS_PATH = resolve(
  "test-results/golden-journey-metrics.json",
);
export const GOLDEN_JOURNEY_SUCCESS_DIR = resolve(
  "test-results/success-journeys",
);
export const GOLDEN_JOURNEY_SUCCESS_MANIFEST_PATH = resolve(
  GOLDEN_JOURNEY_SUCCESS_DIR,
  "manifest.json",
);

/** The slice of Playwright's `FullConfig` this preflight needs. */
type GuardConfig = {
  readonly projects?: readonly {
    readonly use?: { readonly baseURL?: string | undefined } | undefined;
  }[];
  readonly webServer?: unknown;
};

function webServerUrls(webServer: unknown): string[] {
  const entries = Array.isArray(webServer) ? webServer : webServer ? [webServer] : [];
  const urls: string[] = [];
  for (const entry of entries) {
    if (entry && typeof entry === "object") {
      const url = (entry as { url?: unknown }).url;
      if (typeof url === "string") urls.push(url);
    }
  }
  return urls;
}

function testServerUrls(config: GuardConfig | undefined): string[] {
  const urls = webServerUrls(config?.webServer);
  for (const project of config?.projects ?? []) {
    const baseURL = project?.use?.baseURL;
    if (typeof baseURL === "string") urls.push(baseURL);
  }
  return urls;
}

export default function globalSetup(config?: GuardConfig) {
  // Fail before a browser is launched rather than after seven seconds of blank page. The
  // ambient proxy makes Firefox and WebKit route loopback through it, the dev server's
  // modules come back MIME-less, and every ES module is rejected - which reads like a
  // product bug and is not one. See src/testing/proxyGuard.ts.
  const urls = testServerUrls(config);
  if (urls.length === 0 && hasActiveProxy(process.env)) {
    throw new Error(
      [
        PROXY_BLOCKED_MESSAGE,
        "无法从 Playwright 配置中确定本地测试地址，因此不能判断代理是否作用于目标。",
      ].join("\n"),
    );
  }
  assertLocalProxyIsBypassed(process.env, urls);

  rmSync(GOLDEN_JOURNEY_METRICS_PATH, { force: true });
  rmSync(GOLDEN_JOURNEY_SUCCESS_DIR, { recursive: true, force: true });
  mkdirSync(dirname(GOLDEN_JOURNEY_METRICS_PATH), { recursive: true });
  mkdirSync(GOLDEN_JOURNEY_SUCCESS_DIR, { recursive: true });
}
