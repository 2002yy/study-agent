import { expect, test } from "@playwright/test";
import { installApiFixture } from "../api-fixture";
import { noHorizontalOverflow } from "../journey-metrics";

test("memory scope survives settings roundtrip without changing the selected model or speed", async ({ page }, info) => {
  await installApiFixture(page);
  const firstSettings = page.waitForResponse(response => new URL(response.url()).pathname === "/runtime/settings");
  await page.goto("/");
  const runtime = await (await firstSettings).json();
  const writes: Record<string, unknown>[] = [];
  await page.route("**/runtime/settings", async route => {
    if (route.request().method() === "PATCH") {
      const patch = route.request().postDataJSON();
      writes.push(patch);
      Object.assign(runtime.settings, patch);
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(runtime) });
  });
  const openSettings = async () => {
    const more = page.getByLabel("打开更多学习工具").filter({ visible: true });
    if (!(await more.isVisible())) await page.getByLabel("打开会话历史").click();
    await more.click();
    await page.getByRole("menuitem", { name: /设置/ }).click();
    await page.getByRole("region", { name: "学习设置" }).getByText("高级设置", { exact: true }).click();
  };
  await openSettings();
  const settings = page.getByRole("region", { name: "学习设置" });
  const model = settings.getByRole("combobox", { name: "模型档位", exact: true });
  const scope = settings.getByRole("combobox", { name: "个人记忆读取范围", exact: true });
  await model.selectOption("pro");
  await scope.selectOption("deep");
  await expect(model).toHaveValue("pro");
  await scope.selectOption("none");
  await expect(model).toHaveValue("pro");
  await settings.getByRole("button", { name: "设为全局默认", exact: true }).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0].context_mode).toBe("none");
  expect(writes[0].selected_model).toBe("pro");
  expect(writes[0]).not.toHaveProperty("performance_mode");
  await page.reload();
  await openSettings();
  await expect(scope).toHaveValue("none");
  await expect(model).toHaveValue("pro");
  await scope.scrollIntoViewIfNeeded();
  expect(await noHorizontalOverflow(page)).toBe(true);
  await page.screenshot({ path: info.outputPath("none-settings-restored.png"), fullPage: true });
  await page.getByRole("button", { name: "关闭设置", exact: true }).click();
  const sent = page.waitForRequest(request => new URL(request.url()).pathname === "/chat/stream" && request.method() === "POST");
  await page.getByLabel("输入学习问题").fill("请直接回答：2加3是多少？");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  const payload = (await sent).postDataJSON();
  expect(payload.context_mode).toBe("none");
  expect(payload.performance_mode).toBeNull();
  expect(payload.selected_model).toBe("pro");
  expect(await noHorizontalOverflow(page)).toBe(true);
  await page.screenshot({ path: info.outputPath("none-chat-payload.png"), fullPage: true });
});
