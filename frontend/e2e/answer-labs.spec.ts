import { expect, test } from "@playwright/test";
import { installApiFixture, makeLearningSession, seedWorkspaceRecovery } from "./api-fixture";
import { noHorizontalOverflow } from "./journey-metrics";

const cards = [
  { type: "memory_lab", title: "Java内存实验室", initialName: "甲", updatedName: "乙" },
  { type: "performance_lab", title: "研究性能实验台", pages: 8, concurrency: 3, readSeconds: 4, summarySeconds: 6 },
  { type: "evidence_lab", title: "证据审查实验", mode: "simulation", sources: [{ label: "编码任务", kind: "measurement", aSeconds: 1.4, bSeconds: 2 }, { label: "检索任务", kind: "measurement", aSeconds: 2.6, bSeconds: 2.1 }, { label: "评论", kind: "opinion", text: "感觉A更快" }] },
];
test("answer applications synchronize state, preserve the draft and remain usable on narrow screens", async ({ page }) => {
  const session = makeLearningSession();
  const content = "以下为隔离教学实验。\n\n" + cards.map(card => "```study-ui\n" + JSON.stringify(card) + "\n```").join("\n\n");
  session.detail.messages[1].content = content;
  session.detail.turns[0].assistant_message = content;
  await installApiFixture(page, { session });
  await seedWorkspaceRecovery(page, session.row.session_id);
  await page.goto("/");
  const input = page.getByLabel("输入学习问题");
  await input.fill("保留这段草稿");
  const memory = page.getByRole("region", { name: "Java内存实验室", exact: true });
  await memory.getByRole("button", { name: "修改属性", exact: true }).click();
  await expect(memory.getByRole("region", { name: "堆上的对象" })).toContainText('name = "乙"');
  await memory.getByRole("button", { name: "重新赋值", exact: true }).click();
  await expect(memory.getByRole("region", { name: "局部变量与引用" })).toContainText("b→ #2");
  await memory.getByRole("button", { name: "置空 b", exact: true }).click();
  await memory.getByRole("button", { name: "修改属性", exact: true }).click();
  await expect(memory.getByRole("status")).toContainText("NullPointerException");
  await memory.getByRole("button", { name: "全部置空", exact: true }).click();
  await expect(memory.getByText("不可达 · 可被回收", { exact: true })).toHaveCount(2);
  await memory.getByRole("button", { name: "重置实验", exact: true }).click();
  const perf = page.getByRole("region", { name: "研究性能实验台", exact: true });
  await expect(perf.getByLabel("串行读取总耗时")).toHaveText("38s");
  await expect(perf.getByLabel("并发读取总耗时")).toHaveText("18s");
  await perf.getByRole("slider", { name: "允许同时读取的网页数" }).fill("1");
  await expect(perf.getByLabel("并发读取总耗时")).toHaveText("38s");
  await perf.getByRole("button", { name: "恢复默认参数", exact: true }).click();
  await expect(perf.getByRole("status", { name: "性能预测结论" })).toContainText("耗时降低 53%");
  const evidence = page.getByRole("region", { name: "证据审查实验", exact: true });
  await evidence.getByRole("checkbox", { name: /编码任务/ }).uncheck();
  await evidence.getByRole("checkbox", { name: /评论/ }).check();
  await expect(evidence.getByRole("status")).toContainText("证据不足");
  await evidence.getByRole("checkbox", { name: /检索任务/ }).check();
  await expect(evidence.getByRole("status")).toContainText("发现反例");
  await expect(evidence).toContainText("不改变正式研究");
  await expect(input).toHaveValue("保留这段草稿");
  if (page.viewportSize()!.width <= 900) await page.setViewportSize({ width: 320, height: 568 });
  expect(await noHorizontalOverflow(page)).toBe(true);
  for (const title of cards.map(c => c.title)) {
    const app = page.getByRole("region", { name: title, exact: true });
    await app.scrollIntoViewIfNeeded();
    const box = (await app.boundingBox())!;
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(page.viewportSize()!.width);
  }
});
