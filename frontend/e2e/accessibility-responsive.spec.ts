import { expect, test } from "@playwright/test";

import {
  installApiFixture,
  makeLearningSession,
  seedWorkspaceRecovery,
} from "./api-fixture";
import {
  noHorizontalOverflow,
  recordMetric,
  visibleProductSurfaces,
} from "./journey-metrics";

test("slide-over traps keyboard focus and restores the launcher", async ({ page }, testInfo) => {
  const fixture = await installApiFixture(page);
  await page.goto("/");

  if (!(await page.getByLabel("打开更多学习工具").filter({visible:true}).isVisible())) await page.getByLabel("打开会话历史").click();
  const launcher = page.getByLabel("打开更多学习工具").filter({visible:true});
  await launcher.focus();
  await launcher.press("Enter");
  const settingsItem = page.getByRole("menuitem", { name: /设置/ });
  await settingsItem.focus();
  await settingsItem.press("Enter");

  const dialog = page.getByRole("dialog", { name: "设置" });
  const close = page.getByRole("button", { name: "关闭设置", exact: true });
  await expect(dialog).toBeVisible();
  await expect(close).toBeFocused();

  await page.keyboard.press("Shift+Tab");
  expect(await dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true);
  for (let index = 0; index < 20; index += 1) {
    await page.keyboard.press("Tab");
    expect(await dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true);
  }

  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(await launcher.count() ? launcher : page.getByLabel("打开会话历史")).toBeFocused();
  expect(fixture.unexpectedApiPaths).toEqual([]);

  const noOverflow = await noHorizontalOverflow(page);
  expect(noOverflow).toBe(true);
  await recordMetric(testInfo, {
    journey: "slide_over_keyboard",
    project: testInfo.project.name,
    viewport: page.viewportSize(),
    required_clicks: 0,
    required_decisions: 0,
    product_surfaces: await visibleProductSurfaces(page),
    recovery_clicks: 0,
    has_actionable_failure: false,
    keyboard_only: true,
    refresh_restore: false,
    no_horizontal_overflow: noOverflow,
  });
});

test("invalid upload is explained and never reaches the upload endpoint", async ({ page }, testInfo) => {
  const fixture = await installApiFixture(page);
  await page.goto("/");

  const input = page.getByLabel("上传资料");
  await expect(input).toHaveAttribute("accept", ".md,.markdown,.txt,.pdf,.docx");
  await input.setInputFiles({
    name: "unsupported.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("a,b\n1,2"),
  });

  const prompt = page.locator(".upload-learning-prompt");
  await expect(prompt.getByText("资料未上传，请修正文件后重新选择。")).toBeVisible();
  await expect(prompt.getByText(/unsupported\.csv：不支持该文件类型/)).toBeVisible();
  expect(fixture.unexpectedApiPaths).toEqual([]);

  const noOverflow = await noHorizontalOverflow(page);
  expect(noOverflow).toBe(true);
  await recordMetric(testInfo, {
    journey: "upload_validation_feedback",
    project: testInfo.project.name,
    viewport: page.viewportSize(),
    required_clicks: 0,
    required_decisions: 0,
    product_surfaces: await visibleProductSurfaces(page),
    recovery_clicks: 1,
    has_actionable_failure: true,
    keyboard_only: false,
    refresh_restore: false,
    no_horizontal_overflow: noOverflow,
  });
});

test("clipboard denial remains visible on a recovered answer", async ({ page }, testInfo) => {
  const session = makeLearningSession();
  const fixture = await installApiFixture(page, { session });
  await seedWorkspaceRecovery(page, session.row.session_id);
  await page.addInitScript(() => {
    Object.defineProperty(Navigator.prototype, "clipboard", {
      configurable: true,
      get: () => ({ writeText: () => Promise.reject(new Error("denied")) }),
    });
  });
  await page.goto("/");

  const copy = page.getByRole("button", { name: "复制回答正文" });
  await expect(copy).toBeVisible();
  await copy.click();
  await expect(copy).toContainText("复制失败");
  await expect(page.locator("main#chat [role='status']")).toContainText("复制失败");
  expect(fixture.unexpectedApiPaths).toEqual([]);

  const noOverflow = await noHorizontalOverflow(page);
  expect(noOverflow).toBe(true);
  await recordMetric(testInfo, {
    journey: "clipboard_failure_feedback",
    project: testInfo.project.name,
    viewport: page.viewportSize(),
    required_clicks: 1,
    required_decisions: 0,
    product_surfaces: await visibleProductSurfaces(page),
    recovery_clicks: 1,
    has_actionable_failure: true,
    keyboard_only: false,
    refresh_restore: true,
    no_horizontal_overflow: noOverflow,
  });
});

test("composer remains reachable after the visual viewport shrinks", async ({ page }, testInfo) => {
  const fixture = await installApiFixture(page);
  await page.goto("/");
  await page.setViewportSize({ width: 390, height: 520 });

  const composer = page.getByLabel("输入学习问题");
  await composer.focus();
  await composer.fill("继续学习边界条件");
  const send = page.getByRole("button", { name: "发送" });
  await expect(composer).toBeInViewport();
  await expect(send).toBeInViewport();
  await expect(send).toBeEnabled();

  for (const control of [
    page.getByLabel("打开会话历史"),
    page.getByRole("group",{name:"输入方式"}).getByRole("button",{name:"搜索"}),
    send,
  ]) {
    const box = await control.boundingBox();
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
  }

  expect(fixture.unexpectedApiPaths).toEqual([]);
  const noOverflow = await noHorizontalOverflow(page);
  expect(noOverflow).toBe(true);
  await recordMetric(testInfo, {
    journey: "mobile_composer_viewport",
    project: testInfo.project.name,
    viewport: page.viewportSize(),
    required_clicks: 0,
    required_decisions: 0,
    product_surfaces: await visibleProductSurfaces(page),
    recovery_clicks: 0,
    has_actionable_failure: false,
    keyboard_only: false,
    refresh_restore: false,
    no_horizontal_overflow: noOverflow,
  });
});
