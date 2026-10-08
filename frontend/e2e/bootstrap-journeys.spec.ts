import { expect, test, type Page } from "@playwright/test";

import { installApiFixture } from "./api-fixture";

const CORE_REQUESTS = [
  "GET /health",
  "GET /runtime/settings",
  "GET /sessions",
];

const HIDDEN_PATHS = [
  "/rag/status",
  "/knowledge-base/documents",
  "/tools",
  "/workflows/runs",
  "/memory",
  "/wechat",
];

function observeApiRequests(page: Page) {
  const requests: string[] = [];
  page.on("request", (request) => {
    if (!["fetch", "xhr"].includes(request.resourceType())) return;
    const path = new URL(request.url()).pathname;
    requests.push(`${request.method()} ${path}`);
  });
  return requests;
}

function requestCount(requests: string[], path: string) {
  return requests.filter((request) => request.endsWith(` ${path}`)).length;
}

async function expectCoreOnly(requests: string[]) {
  await expect.poll(() => CORE_REQUESTS.every((request) => requests.includes(request))).toBe(true);
  for (const path of HIDDEN_PATHS) {
    expect(requestCount(requests, path)).toBe(0);
  }
}

async function openMoreDrawer(page: Page, menuName: RegExp, title: string) {
  if (!(await page.getByLabel("打开更多学习工具").filter({visible:true}).isVisible())) await page.getByLabel("打开会话历史").click();
  await page.getByLabel("打开更多学习工具").filter({visible:true}).click();
  await page.getByRole("menuitem", { name: menuName }).click();
  const dialog = page.getByRole("dialog", { name: title });
  await expect(dialog).toBeVisible();
  return dialog;
}

async function openLabCapability(page: Page, capabilityName: RegExp, title: string) {
  const laboratory = await openMoreDrawer(page, /实验室/, "实验室");
  await laboratory.getByRole("button", { name: capabilityName }).click();
  const dialog = page.getByRole("dialog", { name: title });
  await expect(dialog).toBeVisible();
  return dialog;
}

async function closeDrawer(page: Page, title: string) {
  const dialog = page.getByRole("dialog", { name: title });
  await dialog.getByRole("button", { name: `关闭${title}` }).last().click();
  await expect(dialog).toHaveCount(0);
}

async function installHiddenFeatureOutages(page: Page) {
  const hiddenPaths = new Set(HIDDEN_PATHS);
  await page.route("**/*", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (
      ["fetch", "xhr"].includes(request.resourceType())
      && hiddenPaths.has(path)
    ) {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "simulated hidden feature outage" }),
      });
      return;
    }
    await route.fallback();
  });
}

test("hidden feature outages do not pollute the core bootstrap", async ({ page }) => {
  const requests = observeApiRequests(page);
  await installApiFixture(page);
  await installHiddenFeatureOutages(page);

  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "对话" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
  await expectCoreOnly(requests);
  await expect(page.getByText(/部分功能暂不可用/)).toHaveCount(0);
  await expect(page.getByText(/API 未连接/)).toHaveCount(0);
});

test("feature drawers load only their own data on demand", async ({ page }) => {
  const requests = observeApiRequests(page);
  await installApiFixture(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "对话" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
  await expectCoreOnly(requests);

  await openMoreDrawer(page, /资料与来源/, "资料与来源");
  await expect.poll(() => requestCount(requests, "/rag/status")).toBe(1);
  await expect.poll(() => requestCount(requests, "/knowledge-base/documents")).toBe(1);
  expect(requestCount(requests, "/tools")).toBe(0);
  expect(requestCount(requests, "/workflows/runs")).toBe(0);
  expect(requestCount(requests, "/memory")).toBe(0);
  expect(requestCount(requests, "/wechat")).toBe(0);
  await closeDrawer(page, "资料与来源");

  await openLabCapability(page, /群聊讨论/, "群聊");
  await expect.poll(() => requestCount(requests, "/wechat")).toBe(1);
  expect(requestCount(requests, "/tools")).toBe(0);
  expect(requestCount(requests, "/workflows/runs")).toBe(0);
  expect(requestCount(requests, "/memory")).toBe(0);
  await closeDrawer(page, "群聊");

  await openLabCapability(page, /受控工具/, "工具");
  await expect.poll(() => requestCount(requests, "/tools")).toBe(1);
  expect(requestCount(requests, "/workflows/runs")).toBe(0);
  expect(requestCount(requests, "/memory")).toBe(0);
  await closeDrawer(page, "工具");

  await openLabCapability(page, /开发者诊断/, "开发者诊断");
  await expect.poll(() => requestCount(requests, "/workflows/runs")).toBe(1);
  expect(requestCount(requests, "/memory")).toBe(0);
  await closeDrawer(page, "开发者诊断");

  await openMoreDrawer(page, /学习成果/, "学习成果");
  await expect.poll(() => requestCount(requests, "/memory")).toBe(1);
  await expect(page.getByText(/部分功能暂不可用/)).toHaveCount(0);
});
