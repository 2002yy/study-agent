import { expect, test } from "@playwright/test";
import { FIRST_REPLY, installApiFixture } from "./api-fixture";

for (const [role, label] of [["march7", "三月七"], ["keqing", "刻晴"], ["nahida", "纳西妲"], ["firefly", "流萤"]]) {
  test(`internal conversation setting sends the selected ${label} role without covering input`, async ({ page }) => {
    await installApiFixture(page);
    await page.goto("/");
    const input = page.getByLabel("输入学习问题");
    await input.fill("保留的学习问题");
    const toggle = page.getByRole("button", { name: "对话设置", exact: true });
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await toggle.click();
    const settings = page.getByRole("region", { name: "对话角色设置" });
    await expect(settings.getByRole("group", { name: "选择对话角色" }).getByRole("button")).toHaveCount(4);
    await expect(input).toHaveValue("保留的学习问题");
    await expect(input).toBeInViewport();
    await expect(page.getByRole("button", { name: "发送", exact: true })).toBeInViewport();
    const panelBox = await settings.boundingBox();
    const inputBox = await input.boundingBox();
    expect(panelBox!.y + panelBox!.height).toBeLessThanOrEqual(inputBox!.y);
    await settings.getByRole("button", { name: label, exact: true }).click();
    await expect(settings).toHaveCount(0);
    await expect(input).toBeFocused();
    const request = page.waitForRequest(request => request.method() === "POST" && /\/chat(?:\/stream)?$/.test(new URL(request.url()).pathname));
    await input.press("Enter");
    expect((await request).postDataJSON()).toMatchObject({ selected_role: role, user_input: "保留的学习问题" });
    await expect(page.getByText(FIRST_REPLY, { exact: true })).toBeVisible();
  });
}
