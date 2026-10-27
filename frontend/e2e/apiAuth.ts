import type { Page } from "@playwright/test";

/**
 * The token the real-stack test server is started with.
 *
 * The browser needs it too (the app holds it in localStorage), so every
 * real-stack config also sends it as a context header for the fixture calls the
 * specs make directly with `request` / `page.request`.
 */
export const E2E_API_TOKEN = "e2e-api-token";

export const API_HEADERS: Record<string, string> = {
  "X-Study-Agent-Token": E2E_API_TOKEN,
};

export const APP_TOKEN_STORAGE_KEY = "study-agent-api-token";

/** Put the token where the app reads it, before any app code runs. */
export async function useAppToken(page: Page): Promise<void> {
  await page.addInitScript(
    ([key, token]) => {
      window.localStorage.setItem(String(key), String(token));
    },
    [APP_TOKEN_STORAGE_KEY, E2E_API_TOKEN] as const,
  );
}
