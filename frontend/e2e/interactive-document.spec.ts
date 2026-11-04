import { expect, test } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { installApiFixture, makeLearningSession, seedWorkspaceRecovery } from "./api-fixture";
import { noHorizontalOverflow } from "./journey-metrics";
import { explorer } from "./fixtures/interactive-document";

const block = (card: unknown) => "```study-ui\n" + JSON.stringify(card) + "\n```";

test("free HTML/SVG interaction carries state into a draft, resets and reconstructs after reload", async ({ page }, info) => {
  const session = makeLearningSession();
  const content = "下单时先锁定库存，支付成功后再扣减。我们把这两个动作拆开来看。\n\n" + block(explorer);
  session.detail.messages[0].content = "订单系统里，锁定库存和扣减库存有什么区别？可以拖动试试吗？";
  session.detail.messages[1].content = content;
  session.detail.turns[0].assistant_message = content;
  await installApiFixture(page, { session });
  await seedWorkspaceRecovery(page, session.row.session_id);
  await page.goto("/");
  const card = page.getByRole("region", { name: explorer.title, exact: true });
  const frame = card.frameLocator("iframe").frameLocator("iframe");
  await expect(frame.locator("#available")).toHaveText("32");
  await frame.getByRole("slider", { name: "锁定数量", exact: true }).fill("12");
  await expect(frame.locator("#available")).toHaveText("25");
  await expect(frame.locator("#free-bar")).toHaveAttribute("width", "250");
  await expect(frame.locator("#explanation")).toContainText("37 − 12 = 25");
  await page.getByLabel("输入学习问题").fill("如果支付失败呢？");
  await card.getByRole("button", { name: "带着当前状态继续问" }).click();
  await expect(page.getByLabel("输入学习问题")).toHaveValue(/如果支付失败呢？[\s\S]*"锁定":12[\s\S]*"可售":25/);
  await expect(page.getByLabel("输入学习问题")).toBeFocused();
  await card.getByRole("button", { name: "展开", exact: true }).click();
  await expect(frame.locator("#available")).toHaveText("25");
  await card.getByRole("button", { name: "收起", exact: true }).click();
  await page.getByLabel("输入学习问题").fill("");
  await page.getByLabel("输入学习问题").blur();
  if (info.project.name === "mobile-chromium") await page.setViewportSize({ width: 375, height: 1100 });
  await card.scrollIntoViewIfNeeded();
  if (process.env.UI_EVIDENCE_DIR) {
    mkdirSync(process.env.UI_EVIDENCE_DIR, { recursive: true });
    await page.screenshot({ path: join(process.env.UI_EVIDENCE_DIR, `${info.project.name}-interactive.png`), animations: "disabled" });
    await card.screenshot({ path: join(process.env.UI_EVIDENCE_DIR, `${info.project.name}-interactive-card.png`) });
  }
  if (info.project.name === "mobile-chromium") {
    await page.setViewportSize({ width: 320, height: 700 });
    expect(await noHorizontalOverflow(page)).toBe(true);
    const box = (await card.boundingBox())!;
    expect(box.x + box.width).toBeLessThanOrEqual(320);
  }
  await card.getByRole("button", { name: "停止", exact: true }).click();
  await expect(card.locator("iframe")).toHaveCount(0);
  await card.getByRole("button", { name: "运行", exact: true }).click();
  await expect(frame.locator("#available")).toHaveText("32");
  await frame.getByRole("button", { name: "释放所有锁定" }).click();
  await expect(frame.locator("#available")).toHaveText("37");
  await card.getByRole("button", { name: "重置", exact: true }).click();
  await expect(frame.locator("#available")).toHaveText("32");
  await page.reload();
  await expect(frame.locator("#available")).toHaveText("32");
});

test("generated Canvas works while parent secrets, network fetch, popups and nested frames are blocked", async ({ page }) => {
  const session = makeLearningSession();
  const probe = { ...explorer, id: "isolation", title: "隔离与Canvas", html: `<canvas width="100" height="60" aria-label="绿色画布"></canvas><output id="result"></output><iframe src="/api/sessions"></iframe><script>
    const result = {};
    try { result.secret = parent.localStorage.getItem('private-test'); } catch { result.parent = 'blocked'; }
    try { result.storage = localStorage.getItem('private-test'); } catch { result.storage = 'blocked'; }
    const canvas = document.querySelector('canvas'); const ctx = canvas.getContext('2d'); ctx.fillStyle = '#39765d'; ctx.fillRect(0,0,100,60); result.pixel = ctx.getImageData(1,1,1,1).data[1];
    result.popup = window.open('about:blank') === null ? 'blocked' : 'opened';
    fetch('https://artifact-invalid.example/attempt').then(() => { result.network = 'opened'; }).catch(() => { result.network = 'blocked'; }).finally(() => { document.getElementById('result').textContent = JSON.stringify(result); });
    const navigate = document.createElement('button'); navigate.textContent = '尝试跳转';
    navigate.addEventListener('click', () => { location.href = 'https://artifact-invalid.example/leak'; }); document.body.append(navigate);
  </script>` };
  session.detail.messages[1].content = block(probe);
  session.detail.turns[0].assistant_message = block(probe);
  await installApiFixture(page, { session });
  await seedWorkspaceRecovery(page, session.row.session_id);
  await page.addInitScript(() => localStorage.setItem("private-test", "private-sentinel"));
  const externalRequests: string[] = [];
  await page.route("https://artifact-invalid.example/**", route => { externalRequests.push(route.request().url()); return route.abort(); });
  await page.goto("/");
  const frame = page.getByRole("region", { name: probe.title, exact: true }).frameLocator("iframe").frameLocator("iframe");
  await expect(frame.locator("#result")).toContainText('"network":"blocked"');
  const result = JSON.parse((await frame.locator("#result").textContent())!);
  expect(result).toEqual({ parent: "blocked", storage: "blocked", pixel: 118, popup: "blocked", network: "blocked" });
  await expect(frame.locator("iframe")).toHaveCount(0);
  expect(await page.evaluate(() => localStorage.getItem("private-test"))).toBe("private-sentinel");
  const blocked = page.waitForEvent("console", message => message.text().includes("artifact-invalid.example/") && message.text().includes("frame-src"));
  await frame.getByRole("button", { name: "尝试跳转" }).click();
  await blocked;
  expect(externalRequests).toEqual([]);
});

test("runtime failure leaves summary readable and repair is a draft action", async ({ page }) => {
  const session = makeLearningSession();
  const broken = { ...explorer, html: '<script>throw new Error("drawScene is missing")</script>' };
  session.detail.messages[1].content = block(broken);
  session.detail.turns[0].assistant_message = block(broken);
  await installApiFixture(page, { session });
  await seedWorkspaceRecovery(page, session.row.session_id);
  await page.goto("/");
  const card = page.getByRole("region", { name: explorer.title, exact: true });
  await expect(card.getByRole("alert")).toContainText("drawScene is missing");
  await expect(card).toContainText(explorer.summary);
  await card.getByRole("button", { name: "请模型修复" }).click();
  await expect(page.getByLabel("输入学习问题")).toHaveValue(/请修复这个界面/);
});
