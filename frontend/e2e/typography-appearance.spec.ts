import { expect, test } from "@playwright/test";
import { installApiFixture } from "./api-fixture";

test("reading fonts switch immediately and persist without a settings API write", async ({ page }) => {
  await installApiFixture(page);
  const writes: string[] = [];
  page.on("request", request => {
    if (request.method() !== "GET" && /settings/.test(new URL(request.url()).pathname)) writes.push(request.url());
  });
  await page.goto("/");
  if (!(await page.getByLabel("打开更多学习工具").filter({visible:true}).isVisible())) await page.getByLabel("打开会话历史").click();
  await page.getByLabel("打开更多学习工具").filter({visible:true}).click();
  await page.getByRole("menuitem", { name: /设置/ }).click();
  const settings = page.getByRole("region", { name: "阅读外观" });
  await settings.getByRole("radio", { name: /统一黑体/ }).check();
  await expect(page.locator(".app-shell")).toHaveAttribute("data-typography", "sans");
  expect(await settings.locator(".typography-preview strong").evaluate(el => getComputedStyle(el).fontFamily)).toContain("Noto Sans SC");
  await settings.getByRole("radio", { name: /宋体阅读/ }).check();
  expect(await settings.locator(".typography-preview p").evaluate(el => getComputedStyle(el).fontFamily)).toContain("Noto Serif SC");
  await page.getByRole("button", { name: "关闭设置", exact: true }).click();
  await page.reload();
  await expect(page.locator(".app-shell")).toHaveAttribute("data-typography", "serif");
  expect(writes).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
  if (page.viewportSize()!.width > 1100) {
    expect((await page.locator(".session-sidebar").boundingBox())!.x).toBeGreaterThanOrEqual(24);
  }
});
