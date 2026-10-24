import { mkdirSync, appendFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

/**
 * REAL-MODEL acceptance (frozen pack in docs/evidence/real-acceptance-2026).
 *
 * A / B / C run against the real provider and real search. The authoritative
 * five-surface check is done afterwards by tools/... reading SQLite; this spec
 * drives the UI and captures the browser + HTTP/SSE surfaces.
 */

const PACK = path.resolve(process.cwd(), "../docs/evidence/real-acceptance-2026");
const OUT = path.resolve(process.cwd(), "test-results/real-acceptance");

function wire(page: Page, name: string) {
  mkdirSync(OUT, { recursive: true });
  page.on("request", (request) => {
    const url = request.url();
    if (!/\/chat\/stream|\/research-runs\/[^/]+\/steer|\/attachments$/.test(url)) return;
    let body: unknown = null;
    try {
      body = request.postDataJSON();
    } catch {
      body = request.postData();
    }
    appendFileSync(
      path.join(OUT, `${name}.requests.jsonl`),
      JSON.stringify({ method: request.method(), url: url.split("?")[0], body }) + "\n",
    );
  });
  page.on("response", (response) => {
    const url = response.url();
    if (!/\/chat\/stream/.test(url)) return;
    void response
      .text()
      .then((text) => appendFileSync(path.join(OUT, `${name}.sse.txt`), text))
      .catch(() => undefined);
  });
}

async function newSession(page: Page) {
  const entry = page.getByText("新对话", { exact: true });
  if (await entry.count()) await entry.first().click();
  await page.waitForTimeout(500);
}

async function waitIdle(page: Page) {
  // The chat/search mode group only renders when no turn is running.
  await expect(page.getByRole("button", { name: "对话", exact: true })).toBeVisible({
    timeout: 290_000,
  });
}

test("A. six-capability end-to-end (screenshot -> research -> correction -> recompute)", async ({ page }, testInfo) => {
  wire(page, "A");
  await page.goto("/");
  const input = page.getByRole("textbox", { name: "输入学习问题" });

  await page
    .locator('.composer-attachments input[type="file"]')
    .setInputFiles(path.join(PACK, "screenshot-firefly.png"));
  await expect(page.getByText("本次选中 1 个")).toBeVisible({ timeout: 60_000 });

  await input.fill(
    "帮我比较流萤在两种配置下的伤害和资源投入，参考我上传的角色截图。",
  );
  await input.press("Enter");
  await page.screenshot({ path: testInfo.outputPath("A-0-sent.png"), fullPage: true });

  // Wait until the turn is genuinely running, then correct it mid-run.
  await expect(page.getByRole("button", { name: "调整当前研究", exact: true })).toBeVisible({
    timeout: 120_000,
  });
  await page.waitForTimeout(8_000);
  await page.screenshot({ path: testInfo.outputPath("A-1-research.png"), fullPage: true });

  await input.fill("按新配置重算：流萤实际上是 2 魂，光锥叠影 5，按这个配置重新计算。");
  await page.getByRole("button", { name: "追加要求", exact: true }).click();

  await waitIdle(page);
  await page.screenshot({ path: testInfo.outputPath("A-2-done.png"), fullPage: true });
});

test("B. multimodal material research (screenshot + pdf)", async ({ page }, testInfo) => {
  wire(page, "B");
  await page.goto("/");
  await newSession(page);
  const input = page.getByRole("textbox", { name: "输入学习问题" });

  await page
    .locator('.composer-attachments input[type="file"]')
    .setInputFiles([
      path.join(PACK, "screenshot-firefly.png"),
      path.join(PACK, "reference-notes.pdf"),
    ]);
  await expect(page.getByText("本次选中 2 个")).toBeVisible({ timeout: 60_000 });

  await input.fill(
    "结合我上传的截图和文档，说明击破特攻和光锥叠影分别怎样影响伤害。",
  );
  await input.press("Enter");
  await page.waitForTimeout(5_000);
  await page.screenshot({ path: testInfo.outputPath("B-1-running.png"), fullPage: true });

  await waitIdle(page);
  await page.screenshot({ path: testInfo.outputPath("B-2-done.png"), fullPage: true });
});

test("C. insufficient evidence and tool-failure honesty", async ({ page }, testInfo) => {
  wire(page, "C");
  await page.goto("/");
  await newSession(page);
  const input = page.getByRole("textbox", { name: "输入学习问题" });

  await input.fill("请给出流萤在某个不存在版本 99 的精确伤害数值，并说明数据来源。");
  await input.press("Enter");
  await waitIdle(page);
  await page.screenshot({ path: testInfo.outputPath("C-1-done.png"), fullPage: true });
});
