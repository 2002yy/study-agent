import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { installApiFixture, makeLearningSession, seedWorkspaceRecovery } from "../api-fixture";
import { noHorizontalOverflow } from "../journey-metrics";

for (const [task, status] of [["M01", "output_limit"], ["P01", "completed"]]) {
  test(`real ${task} source remains inert and offers a runnable-interface draft`, async ({ page }, info) => {
    const content = readFileSync(join(process.cwd(), `e2e/fixtures/m4c3-first/${task}.txt`), "utf-8");
    const session = makeLearningSession();
    session.detail.messages[1].content = content;
    session.detail.turns[0].assistant_message = content;
    session.detail.turns[0].route_snapshot = { role: "nahida", generation: { status } };
    await installApiFixture(page, { session });
    await seedWorkspaceRecovery(page, session.row.session_id);
    await page.goto("/");
    await expect(page.getByText("这段内容是网页源码，尚未作为交互界面运行。")).toBeVisible();
    await expect(page.locator(".interactive-document iframe")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "继续未完成的说明", exact: true })).toHaveCount(0);
    if (task === "M01") await expect(page.getByText(/本次回答达到输出长度上限/)).toBeVisible();
    await page.reload();
    await page.getByRole("button", { name: "生成可运行界面", exact: true }).click();
    await expect(page.getByLabel("输入学习问题")).toHaveValue(/study-ui/);
    expect(await noHorizontalOverflow(page)).toBe(true);
    await page.screenshot({ path: info.outputPath(`${task}.png`), fullPage: true });
  });
}
