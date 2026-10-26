import { expect, test } from "@playwright/test";

import { APP_TOKEN_STORAGE_KEY, E2E_API_TOKEN } from "./apiAuth";

/**
 * A2: the token is mandatory, and the browser is a first-class client of it.
 *
 * The other real-stack specs run with a context header so their fixture calls
 * work; this one deliberately runs without one, to prove both halves of the
 * contract:
 *
 * 1. without a token the API refuses, directly and through the dev proxy;
 * 2. with the token the operator pasted into the app, the real app loads its
 *    data - the client path, not just the HTTP status.
 */

const APP = "http://127.0.0.1:5173/";
const API = "http://127.0.0.1:8000";

test("without a token every private request is refused", async () => {
  // Plain fetch, not a Playwright context: no config header can apply here.
  const direct = await fetch(`${API}/sessions`);
  expect(direct.status).toBe(401);
  expect((await direct.json()).code).toBe("api_token_required");

  // The dev proxy must not be a way around the check.
  const throughProxy = await fetch("http://127.0.0.1:5173/sessions");
  expect(throughProxy.status).toBe(401);
});

test("a token pasted into the app makes the same browser load real data", async ({
  browser,
}) => {
  // Explicit empty headers: this context must not carry the fixture token, or
  // the assertion below would prove nothing about the app's own client.
  const context = await browser.newContext({ extraHTTPHeaders: {} });
  const page = await context.newPage();
  await page.addInitScript(
    ([key, token]) => window.localStorage.setItem(String(key), String(token)),
    [APP_TOKEN_STORAGE_KEY, E2E_API_TOKEN] as const,
  );

  const sessionStatuses: number[] = [];
  page.on("response", (response) => {
    if (response.url().includes("/sessions")) sessionStatuses.push(response.status());
  });

  await page.goto(APP);

  await expect(page.getByLabel("输入学习问题")).toBeVisible();
  // Self-check: a bare fetch from this same page carries no token, so the 200s
  // below can only come from the app's own header.
  expect(await page.evaluate(async () => (await fetch("/sessions")).status)).toBe(401);
  await expect
    .poll(() => sessionStatuses.filter((status) => status === 200).length)
    .toBeGreaterThan(0);

  await context.close();
});
