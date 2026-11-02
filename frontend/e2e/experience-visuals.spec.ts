import { expect, test } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { installApiFixture, makeLearningSession, seedWorkspaceRecovery } from "./api-fixture";
import { noHorizontalOverflow } from "./journey-metrics";

test("expressive portrait and readable chart share the conversation width", async ({ page }, info) => {
  if (info.project.name === "mobile-chromium") await page.setViewportSize({ width: 375, height: 812 });
  const session = makeLearningSession();
  const answer = [
    "把每天的阅读量放在一起，就能看清差别。",
    "```study-ui",
    JSON.stringify({ type: "chart", title: "示意：三天的阅读记录", unit: "页", points: [
      { label: "星期一", value: 12 }, { label: "星期二", value: 20 }, { label: "星期三", value: 16 },
    ] }),
    "```",
    "以上是演示数据，用来说明比较方法，不是你的真实学习记录。",
  ].join("\n\n");
  session.detail.messages[0].content = "阅读记录怎样展示更清楚？";
  session.detail.messages[1].content = answer;
  session.detail.turns[0].assistant_message = answer;
  await installApiFixture(page, { session });
  await seedWorkspaceRecovery(page, session.row.session_id);
  await page.goto("/");
  const portrait = page.locator(".message.assistant > .avatar img");
  await expect.poll(() => portrait.evaluate(img => (img as HTMLImageElement).naturalWidth)).toBe(512);
  const avatar = (await portrait.boundingBox())!;
  expect(avatar.width).toBe(page.viewportSize()!.width <= 600 ? 70 : 86); // 1px frame on each side
  const card = page.getByRole("region", { name: "示意：三天的阅读记录", exact: true });
  await expect(card.getByText("星期二", { exact: true }).first()).toBeVisible();
  await expect(card.getByText("单位：页")).toBeVisible();
  await expect(card.locator(".answer-bar-value").nth(1)).toHaveText("20");
  await expect(card.locator(".answer-bar-label").first()).toHaveCSS("font-size", "14px");
  await page.locator(".conversation").evaluate(el => {
    const message = el.querySelector(".message.assistant")!;
    el.scrollTop += message.getBoundingClientRect().top - el.getBoundingClientRect().top - 24;
  });
  if (process.env.UI_EVIDENCE_DIR) {
    mkdirSync(process.env.UI_EVIDENCE_DIR, { recursive: true });
    await page.screenshot({ path: join(process.env.UI_EVIDENCE_DIR, `${info.project.name}-portrait-chart.png`), animations: "disabled" });
  }
  await card.getByRole("button", { name: "折线图" }).click();
  await expect(card.getByRole("img")).toHaveAccessibleName(/折线图/);
  await card.getByText("查看完整数据").click();
  await expect(card.getByRole("table")).toContainText("20");
  await expect(card.getByRole("columnheader", { name: "数值（页）" })).toBeVisible();
  if (page.viewportSize()!.width < 600) await page.setViewportSize({ width: 320, height: 568 });
  expect(await noHorizontalOverflow(page)).toBe(true);
});
