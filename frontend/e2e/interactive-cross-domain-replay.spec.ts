/** Browser acceptance against saved real generations. No provider calls. */
import { expect, test, type Page, type Locator } from "@playwright/test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { installApiFixture, makeLearningSession, seedWorkspaceRecovery } from "./api-fixture";
import { noHorizontalOverflow } from "./journey-metrics";

const directory = process.env.INTERACTIVE_LIVE_REPLAY_DIR;
test.skip(!directory, "Requires explicitly selected, saved real model outputs.");

async function load(page: Page, stage: number) {
  const response = JSON.parse(readFileSync(join(directory!, `response-${stage}.json`), "utf8"));
  const card = JSON.parse(readFileSync(join(directory!, `card-${stage}.json`), "utf8"));
  const session = makeLearningSession();
  session.detail.messages[1].content = response.reply;
  session.detail.turns[0].assistant_message = response.reply;
  await installApiFixture(page, { session });
  await seedWorkspaceRecovery(page, session.row.session_id);
  await page.goto("/");
  const region = page.getByRole("region", { name: card.title, exact: true });
  return { region, frame: region.frameLocator("iframe").frameLocator("iframe") };
}

async function arrowsReachObjects(diagram: Locator) {
  const geometry = await diagram.evaluate(node => {
    const objects = Array.from(node.querySelectorAll(".obj"));
    return Array.from(node.querySelectorAll<SVGLineElement>("svg line")).map((line, index) => {
      const point = new DOMPoint(line.x2.baseVal.value, line.y2.baseVal.value).matrixTransform(line.getScreenCTM()!);
      const box = objects[Math.min(index, objects.length - 1)].getBoundingClientRect();
      return { gap: Math.abs(point.x - box.left), inside: point.y >= box.top && point.y <= box.bottom };
    });
  });
  expect(geometry.length).toBeGreaterThan(0);
  for (const arrow of geometry) {
    expect(arrow.gap).toBeLessThanOrEqual(8);
    expect(arrow.inside).toBe(true);
  }
}

test("generated reference story renders only created objects and rewinds the same state", async ({ page }, info) => {
  const stage = Number(process.env.INTERACTIVE_CODE_REPLAY_STAGE || 7);
  const { region, frame } = await load(page, stage);
  const diagram = frame.locator(stage >= 6 ? "#diagram" : "#canvas");
  await expect(frame.locator("#explain")).toContainText("执行前");
  await expect(diagram).not.toContainText(/对象1\s*CacheEntry/);
  await frame.getByRole("button", { name: "下一步", exact: true }).click();
  await expect(diagram).toContainText(/对象1\s*CacheEntry/);
  if (stage >= 6) {
    // HTML labels retain their physical font size instead of shrinking with SVG.
    const sizes = await diagram.locator(".title,.hits").evaluateAll(nodes => nodes.map(node => parseFloat(getComputedStyle(node).fontSize)));
    expect(sizes.length).toBeGreaterThan(0);
    expect(Math.min(...sizes)).toBeGreaterThanOrEqual(14);
    await arrowsReachObjects(diagram);
  }
  await frame.getByRole("button", { name: "下一步", exact: true }).click();
  await frame.getByRole("button", { name: "下一步", exact: true }).click();
  await expect(frame.locator("#values")).toContainText(/对象1[.:：]\s*hits = 3/);
  await expect(frame.locator("#explain")).toContainText("a.hits");
  await expect(diagram).not.toContainText(/对象2\s*CacheEntry/);
  await frame.getByRole("button", { name: "下一步", exact: true }).click();
  await frame.getByRole("button", { name: "下一步", exact: true }).click();
  await expect(frame.locator("#values")).toContainText(/对象1[.:：]\s*hits = 3/);
  await expect(frame.locator("#values")).toContainText("hits = 7");
  if (stage >= 6) await arrowsReachObjects(diagram);
  await expect(frame.getByRole("button", { name: "下一步", exact: true })).toBeDisabled();
  await frame.getByRole("button", { name: "上一步", exact: true }).click();
  await expect(frame.locator("#values")).toContainText("hits = 0");
  await region.scrollIntoViewIfNeeded();
  await page.screenshot({ path: join(directory!, `${info.project.name}-real-reference-story.png`) });
  await frame.getByRole("button", { name: "重置", exact: true }).click();
  await expect(diagram).not.toContainText(/对象1\s*CacheEntry/);
  if (info.project.name === "mobile-chromium") await page.setViewportSize({ width: 320, height: 700 });
  expect(await noHorizontalOverflow(page)).toBe(true);
});

test("generated Canvas obeys the equation, responds to animation controls and stays still in reduced motion", async ({ page }, info) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  const { region, frame } = await load(page, 4);
  await expect(region.locator(".interactive-source > pre")).toContainText('"playing"');
  const snapshot = async () => JSON.parse((await region.locator(".interactive-source > pre").textContent())!);
  await expect.poll(async () => (await snapshot()).playing).toBe(false);
  const inputs = frame.getByRole("slider");
  await inputs.nth(1).fill("1.57");
  await expect.poll(async () => (await snapshot()).x).toBeCloseTo(40, 1);
  await inputs.nth(0).fill("60");
  await expect.poll(async () => (await snapshot()).x).toBeCloseTo(60, 1);
  const imageBefore = await frame.locator("canvas").evaluate((node: HTMLCanvasElement) => node.toDataURL());
  await inputs.nth(1).fill("0");
  await expect.poll(async () => (await snapshot()).x).toBe(0);
  const imageAfter = await frame.locator("canvas").evaluate((node: HTMLCanvasElement) => node.toDataURL());
  expect(imageBefore).not.toBe(imageAfter);
  await frame.getByRole("button", { name: /播放/ }).click();
  await expect.poll(async () => (await snapshot()).phase).toBeGreaterThan(0);
  await frame.getByRole("button", { name: /暂停/ }).click();
  await expect.poll(async () => (await snapshot()).playing).toBe(false);
  const paused = (await snapshot()).phase;
  // Wait for an actual animation frame in the parent rather than a wall-clock sleep.
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  expect((await snapshot()).phase).toBe(paused);
  await frame.getByRole("button", { name: /重置/ }).click();
  await expect.poll(async () => (await snapshot()).A).toBe(40);
  await expect.poll(async () => (await snapshot()).phase).toBe(0);
  await region.scrollIntoViewIfNeeded();
  await page.screenshot({ path: join(directory!, `${info.project.name}-real-canvas.png`) });
  if (info.project.name === "mobile-chromium") await page.setViewportSize({ width: 320, height: 700 });
  expect(await noHorizontalOverflow(page)).toBe(true);
});
