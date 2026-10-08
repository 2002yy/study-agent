import { expect, test, type Page } from "@playwright/test";

const API = "http://127.0.0.1:8000";
const STORE = "study-agent-react-session";
const QUERY = "Python object construction boundaries";
const RESEARCH_QUERY = `请联网研究：${QUERY}`;

test.beforeEach(async ({ request }) => {
  expect((await request.post(`${API}/__e2e__/reset`)).ok()).toBe(true);
});

async function storedRunId(page: Page) {
  await page.waitForFunction((key) => {
    const raw = localStorage.getItem(key);
    if (!raw) return false;
    return Boolean(JSON.parse(raw).workspace?.webLookupRunId);
  }, STORE);
  return page.evaluate((key) => JSON.parse(localStorage.getItem(key) ?? "{}").workspace.webLookupRunId, STORE) as Promise<string>;
}

async function run(page: Page, id: string) {
  const response = await page.request.get(`${API}/research-runs/${id}`);
  expect(response.ok()).toBe(true);
  return response.json();
}

async function startResearchFromChat(page: Page) {
  const composer = page.getByLabel("输入学习问题");
  // Explicit chat search is the supported entry after simplifying the composer.
  await composer.fill(RESEARCH_QUERY);
  await page.getByRole("button", { name: "发送" }).click();
}

test("research stop survives refresh and retries the same run", async ({ page }) => {
  await page.goto("/");
  await startResearchFromChat(page);
  const id = await storedRunId(page);
  await page.getByRole("button", { name: "停止" }).click();

  await expect.poll(async () => (await run(page, id)).status).toBe("cancelled");
  const cancelled = await run(page, id);
  expect(cancelled).toMatchObject({
    id,
    query: RESEARCH_QUERY,
    stage: "cancelled",
    stop_reason: "user_cancelled",
  });
  expect(cancelled.cancel_requested_at).toBeTruthy();
  expect(cancelled.completed_at).toBeTruthy();
  expect(cancelled.query_attempts.length).toBeGreaterThanOrEqual(1);

  await page.reload();
  await expect(page.getByText("研究已停止", { exact: true })).toBeVisible();
  expect(await storedRunId(page)).toBe(id);

  await page.getByRole("button", { name: "重试研究" }).click();
  await expect.poll(async () => (await run(page, id)).status).toBe("completed");
  const completed = await run(page, id);
  expect(completed.id).toBe(id);
  expect(completed.query_attempts).toEqual(cancelled.query_attempts);
  expect(completed.source_block).not.toBe("");
  await expect(page.getByText("联网研究已恢复", { exact: true })).toBeVisible();
});
