import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { installApiFixture, makeLearningSession, seedWorkspaceRecovery } from "./api-fixture";
import { noHorizontalOverflow } from "./journey-metrics";

for (const [status, text] of [
  ["output_limit", "本次回答达到输出长度上限"],
  ["completed", "模型已结束回答，但交互格式不完整"],
  ["timeout", "生成请求超时"],
]) {
  test(`saved ${status} has an accurate recovery message after reload`, async ({ page }) => {
    const session = makeLearningSession();
    const content = '前面的说明仍可阅读。\n\n```study-ui\n{"type":"interactive","html":"';
    session.detail.messages[1].content = content;
    session.detail.turns[0].assistant_message = content;
    session.detail.turns[0].route_snapshot = { role: "nahida", generation: { status } };
    await installApiFixture(page, { session });
    await seedWorkspaceRecovery(page, session.row.session_id);
    await page.goto("/");
    await expect(page.getByText(new RegExp(text))).toBeVisible();
    await expect(page.getByText("前面的说明仍可阅读。")).toBeVisible();
    await expect(page.locator(".interactive-document iframe")).toHaveCount(0);
    await page.reload();
    await expect(page.getByText(new RegExp(text))).toBeVisible();
    await page.getByRole("button", { name: "生成完整界面", exact: true }).click();
    await expect(page.getByLabel("输入学习问题")).toHaveValue(/精简、自包含的完整版本/);
  });
}

const liveDirectory = process.env.INTERACTIVE_BUDGET_REPLAY_DIR;
test("a real provider length stop offers a manual continuation after reload", async ({ page }) => {
  test.skip(!liveDirectory, "Requires saved provider termination evidence.");
  const receipt = JSON.parse(readFileSync(join(liveDirectory!, "limit-receipt.json"), "utf8"));
  const content = readFileSync(join(liveDirectory!, "limit-reply.txt"), "utf8");
  const session = makeLearningSession();
  session.detail.messages[1].content = content;
  session.detail.turns[0].assistant_message = content;
  session.detail.turns[0].route_snapshot = { role: "nahida", generation: receipt.cases[0].generation };
  await installApiFixture(page, { session });
  await seedWorkspaceRecovery(page, session.row.session_id);
  await page.goto("/");
  await expect(page.getByText(/本次回答达到输出长度上限/)).toBeVisible();
  await page.getByRole("button", { name: "继续未完成的说明", exact: true }).click();
  await expect(page.getByLabel("输入学习问题")).toHaveValue(/只用文字继续/);
});

for (const name of ["simple", "complex"]) {
  test(`saved real ${name} generation retains working controls`, async ({ page }, info) => {
    test.skip(!liveDirectory, "Opt-in saved provider output; never makes model calls.");
    const content = readFileSync(join(liveDirectory!, `${name}-reply.txt`), "utf8");
    const card = JSON.parse(content.match(/```study-ui\s*([\s\S]*?)```/)![1]);
    const session = makeLearningSession();
    session.detail.messages[1].content = content;
    session.detail.turns[0].assistant_message = content;
    await installApiFixture(page, { session });
    await seedWorkspaceRecovery(page, session.row.session_id);
    await page.goto("/");
    const region = page.getByRole("region", { name: card.title, exact: true });
    const frame = region.frameLocator("iframe").frameLocator("iframe");
    const available = frame.locator(name === "simple" ? "#availNum" : "#availVal");
    await expect(available).toHaveText("32");
    await frame.getByRole("slider").fill("12");
    await expect(available).toHaveText("25");
    await frame.getByRole("button", { name: /重置/ }).click();
    await expect(available).toHaveText("32");
    if (info.project.name === "mobile-chromium") await page.setViewportSize({ width: 320, height: 700 });
    expect(await noHorizontalOverflow(page)).toBe(true);
    await region.scrollIntoViewIfNeeded();
    await page.screenshot({ path: join(liveDirectory!, `${info.project.name}-${name}.png`) });
  });
}
