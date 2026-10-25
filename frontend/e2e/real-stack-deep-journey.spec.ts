import { expect, test, type Page } from "@playwright/test";

/**
 * S2-C4: the deep-research user journey on the real stack.
 *
 * The backend is the production FastAPI app with real routes, services and
 * SQLite; only the model and the external gateway are deterministic. The
 * browser is the real React app. The journey must show progress, the answer and
 * the pages that were actually read, and a stop must survive a reload and be
 * retryable.
 */

const API = "http://127.0.0.1:8000";
const STORE = "study-agent-react-session";
const QUERY = "请深度研究：OMEGA protocol latency comparison";

type Attempt = { query: string; round?: number };

async function send(page: Page, text: string) {
  const composer = page.getByLabel("输入学习问题");
  await composer.fill(text);
  await page.getByRole("button", { name: "发送" }).click();
}

async function storedRunId(page: Page) {
  await page.waitForFunction((key) => {
    const raw = localStorage.getItem(key);
    if (!raw) return false;
    return Boolean(JSON.parse(raw).workspace?.webLookupRunId);
  }, STORE);
  return page.evaluate(
    (key) => JSON.parse(localStorage.getItem(key) ?? "{}").workspace.webLookupRunId,
    STORE,
  ) as Promise<string>;
}

async function run(page: Page, id: string) {
  const response = await page.request.get(`${API}/research-runs/${id}`);
  expect(response.ok()).toBe(true);
  return response.json();
}

async function latestRun(page: Page) {
  const response = await page.request.get(`${API}/research-runs`);
  expect(response.ok()).toBe(true);
  const payload = await response.json();
  return (payload.runs?.[0] ?? { id: "", status: "" }) as {
    id: string;
    status: string;
  };
}

test.beforeEach(async ({ request }) => {
  expect((await request.post(`${API}/__e2e__/reset`)).ok()).toBe(true);
});

test("deep research shows live progress, the answer, and its read sources", async ({
  page,
}) => {
  await page.goto("/");
  await send(page, QUERY);

  // Live progress is visible while the run is still working.
  await expect(
    page.getByRole("status").filter({ hasText: /研究|搜索|读取|整理/ }).first(),
  ).toBeVisible({ timeout: 15_000 });

  // The final research turn is evidence-only; its read pages are visible now.
  const findings = page.getByLabel("已读资料摘录");
  await expect(findings).toBeVisible({ timeout: 30_000 });
  await expect(findings).toContainText("DEEP-OBSERVATION-42");
  await expect(
    findings.getByRole("link", { name: /Baseline evidence/ }),
  ).toBeVisible();

  // The completed run is selected for the next chat turn.
  await expect(
    page.getByText("恢复结果已设为下一轮聊天资料。"),
  ).toBeVisible({ timeout: 30_000 });
  await send(page, "基于上面的资料，OMEGA 协议的延迟结论是什么？");
  await expect(
    page.getByText(/根据这次研究读取的正文：DEEP-ANSWER-OK/),
  ).toBeVisible({ timeout: 40_000 });

  const id = await storedRunId(page);
  const completed = await run(page, id);
  expect(completed.status).toBe("completed");
  expect(completed.research_context.research_mode).toBe("deep");
  const attempts = completed.query_attempts as Attempt[];
  const rounds = [...new Set(attempts.map((attempt) => attempt.round))].sort();
  expect(rounds).toEqual([1, 2]);
  expect(attempts.some((attempt) => attempt.query.includes("FOLLOWUP"))).toBe(true);
  const notes = completed.research_context.deep.notes as unknown[];
  expect(notes.length).toBeGreaterThanOrEqual(1);

  // The answer and the sources are durable: a refresh shows the same turn.
  await page.reload();
  await expect(
    page.getByText(/根据这次研究读取的正文：DEEP-ANSWER-OK/),
  ).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("研究已停止")).toHaveCount(0);
});

test("a stopped deep run survives reload and retry finishes the same run", async ({
  page,
}) => {
  await page.goto("/");
  await send(page, QUERY);
  await expect
    .poll(async () =>
      ["pending", "running"].includes((await latestRun(page)).status),
    )
    .toBe(true);
  await page.getByRole("button", { name: "停止" }).click();
  await expect.poll(async () => (await latestRun(page)).status).toBe("cancelled");
  const id = (await latestRun(page)).id;

  // A stopped run starts no more work: wait, then compare the durable attempts.
  const cancelled = await run(page, id);
  const attemptsAtStop = (cancelled.query_attempts as Attempt[]).length;
  await page.waitForTimeout(800);
  expect(((await run(page, id)).query_attempts as Attempt[]).length).toBe(
    attemptsAtStop,
  );

  await page.reload();
  await expect(page.getByText("研究已停止").first()).toBeVisible();
  expect(await storedRunId(page)).toBe(id);

  await page.getByRole("button", { name: "重试研究" }).click();
  await expect(
    page.getByText("恢复结果已设为下一轮聊天资料。"),
  ).toBeVisible({ timeout: 40_000 });
  await expect.poll(async () => (await run(page, id)).status).toBe("completed");

  const completed = await run(page, id);
  expect(completed.id).toBe(id);
  const rounds = [
    ...new Set((completed.query_attempts as Attempt[]).map((attempt) => attempt.round)),
  ].sort();
  expect(rounds).toEqual([1, 2]);
});
