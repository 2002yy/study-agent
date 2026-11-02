/** Replay saved REAL model answers; this file never calls a provider. */
import { expect, test } from "@playwright/test";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { installApiFixture, makeLearningSession, seedWorkspaceRecovery } from "./api-fixture";

const directory = process.env.INTERACTIVE_LIVE_REPLAY_DIR;
test.skip(!directory, "Set INTERACTIVE_LIVE_REPLAY_DIR to authorized saved model replies.");

test("saved model interface runs and supplies the actual exploration state for a follow-up", async ({ page }, info) => {
  const first = JSON.parse(readFileSync(join(directory!, "response-1.json"), "utf8"));
  const card = JSON.parse(readFileSync(join(directory!, "card-1.json"), "utf8"));
  const session = makeLearningSession();
  session.detail.messages[1].content = first.reply;
  session.detail.turns[0].assistant_message = first.reply;
  await installApiFixture(page, { session });
  await seedWorkspaceRecovery(page, session.row.session_id);
  await page.goto("/");
  const region = page.getByRole("region", { name: card.title, exact: true });
  const frame = region.frameLocator("iframe").frameLocator("iframe");
  await expect(frame.locator("#sellableNum")).toHaveText("32");
  await frame.getByRole("slider").fill("12");
  await expect(frame.locator("#sellableNum")).toHaveText("25");
  await expect(frame.locator("#explain")).toContainText("12");
  await region.getByRole("button", { name: "带着当前状态继续问" }).click();
  const draft = await page.getByLabel("输入学习问题").inputValue();
  expect(draft).toContain('"已锁定":12');
  expect(draft).toContain('"可售":25');
  writeFileSync(join(directory!, "followup.txt"), draft + "\n保留现在锁定12、可售25的状态，增加支付成功按钮：支付后总库存和锁定量同时减去已支付数量。给出同一界面的完整新版。", "utf8");
  await page.getByLabel("输入学习问题").fill("");
  await page.getByLabel("输入学习问题").blur();
  if (info.project.name === "mobile-chromium") await page.setViewportSize({ width: 375, height: 1100 });
  await region.scrollIntoViewIfNeeded();
  await page.screenshot({ path: join(directory!, `${info.project.name}-real-model.png`) });
  expect(await region.getByRole("alert").count()).toBe(0);
});

test("saved follow-up produces a new version while the earlier version remains usable", async ({ page }) => {
  test.skip(!existsSync(join(directory!, "response-2.json")), "Run the authorized follow-up first.");
  const first = JSON.parse(readFileSync(join(directory!, "response-1.json"), "utf8"));
  const second = JSON.parse(readFileSync(join(directory!, "response-2.json"), "utf8"));
  const c1 = JSON.parse(readFileSync(join(directory!, "card-1.json"), "utf8"));
  const c2 = JSON.parse(readFileSync(join(directory!, "card-2.json"), "utf8"));
  expect(c2.id).toBe(c1.id);
  expect(c2.revision).toBe(c1.revision + 1);
  const session = makeLearningSession();
  session.detail.messages[1].content = first.reply + "\n\n" + second.reply;
  session.detail.turns[0].assistant_message = session.detail.messages[1].content;
  await installApiFixture(page, { session });
  await seedWorkspaceRecovery(page, session.row.session_id);
  await page.goto("/");
  const cards = page.locator(".answer-card-interactive");
  await expect(cards).toHaveCount(2);
  const oldFrame = cards.nth(0).frameLocator("iframe").frameLocator("iframe");
  const nextFrame = cards.nth(1).frameLocator("iframe").frameLocator("iframe");
  await expect(oldFrame.locator("#sellableNum")).toHaveText("32");
  await expect(nextFrame.locator("#sellableNum")).toHaveText("25");
  await nextFrame.getByRole("button", { name: /支付成功/ }).click();
  await expect(nextFrame.locator("#sellableNum")).toHaveText("25");
  await expect(nextFrame.locator("#lockedNum")).toHaveText("0");
  await expect(oldFrame.locator("#sellableNum")).toHaveText("32");
});
