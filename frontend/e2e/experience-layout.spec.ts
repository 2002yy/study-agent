import { expect, test } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { installApiFixture, makeLearningSession, seedWorkspaceRecovery } from "./api-fixture";
import { noHorizontalOverflow } from "./journey-metrics";

test("A+C keeps the conversation, draft and source reading usable", async ({ page }, info) => {
  if (info.project.name === "mobile-chromium") await page.setViewportSize({ width: 375, height: 812 });
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  const session = makeLearningSession();
  const answer = [
    "## 先理解不变量，再写边界",
    "每次迭代都保留可能包含答案的区间。检查中点后，排除已经确认不可能包含答案的一半。",
    "### 左闭右开区间",
    "使用 `[left, right)` 时，右边界不属于候选区间。空区间对应 `left === right`。",
    "### 为什么一定会结束",
    "每次更新都必须让区间严格缩小。把更新规则和区间定义放在一起检查，比记住一段模板更可靠。",
    ...Array.from({ length: 6 }, (_, index) => `### 核对步骤 ${index + 1}\n先观察候选范围，再检查中点和边界。这是离线 UI 验证文本。`),
  ].join("\n\n");
  session.detail.messages[1].content = answer;
  session.detail.turns[0].assistant_message = answer;
  await installApiFixture(page, { session });
  await seedWorkspaceRecovery(page, session.row.session_id);
  const document = { document_id: "experience-source", source_path: "fixture/reading.txt", title: "区间不变量 · 验证资料", file_type: "txt", evidence_status: "active", chunks: 1 };
  await page.route("**/knowledge-base/documents", route => route.fulfill({ json: {
    index_exists: true, documents: [document], chunks: 1, retrievable_documents: 1, retrievable_chunks: 1,
  } }));
  await page.route("**/knowledge-base/documents/experience-source/reading?*", route => route.fulfill({ json: {
    ...document, schema_version: "document-reading-v1", representation: "indexed_text", scope: "knowledge",
    revision_id: "fixture-v1", content_hash: "fixture", parser_version: "fixture", start_line: 1, end_line: 5, total_lines: 5,
    text: "区间不变量\n每轮迭代都保留可能包含答案的范围。\n左闭右开区间的右端点不参与比较。\n区间严格缩小，算法才能结束。\n此文档仅用于离线界面验证。",
  } }));
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "先理解不变量，再写边界" })).toBeAttached();
  await expect(page.locator("vite-error-overlay")).toHaveCount(0);
  const conversation = page.locator(".conversation");
  // The real observer follows delayed layout growth while already at the end.
  await expect.poll(() => conversation.evaluate(el => el.scrollHeight - el.scrollTop - el.clientHeight)).toBeLessThan(2);
  await page.locator(".message.assistant .message-bubble").evaluate(el => {
    const delayed = document.createElement("div");
    delayed.style.height = "240px";
    el.append(delayed);
  });
  await expect.poll(() => conversation.evaluate(el => el.scrollHeight - el.scrollTop - el.clientHeight)).toBeLessThan(2);
  await conversation.evaluate(el => { el.scrollTop = 80; });
  await expect(page.locator(".back-to-latest")).toBeVisible();
  const draft = page.getByLabel("输入学习问题");
  await draft.fill("请结合这段来源继续解释");
  const composer = (await page.locator(".composer-main").boundingBox())!;
  expect(composer.y + composer.height).toBeLessThanOrEqual(page.viewportSize()!.height);
  const before = await conversation.evaluate(el => el.scrollTop);
  // A later layout growth must not pull a reader away from an earlier paragraph.
  await page.locator(".message.assistant .message-bubble").evaluate(el => {
    const delayed = document.createElement("div");
    delayed.style.height = "240px";
    el.append(delayed);
  });
  await page.waitForTimeout(100);
  expect(await conversation.evaluate(el => el.scrollTop)).toBeCloseTo(before, 0);
  const screenshot = async (state: string) => {
    if (!process.env.UI_EVIDENCE_DIR) return;
    mkdirSync(process.env.UI_EVIDENCE_DIR, { recursive: true });
    await page.screenshot({ path: join(process.env.UI_EVIDENCE_DIR, `${info.project.name}-${state}.png`), animations: "disabled" });
  };
  await screenshot("chat");
  if (!(await page.getByLabel("管理阅读资料").filter({ visible: true }).isVisible())) await page.getByLabel("打开会话历史").click();
  await page.getByLabel("管理阅读资料").filter({ visible: true }).click();
  await page.getByRole("button", { name: "阅读正文", exact: true }).click();
  await expect(page.locator(".document-paper")).toBeVisible();
  await screenshot("sources");
  if (page.viewportSize()!.width > 900) {
    const chat = (await page.locator(".chat-column").boundingBox())!;
    const source = (await page.locator(".document-reader").boundingBox())!;
    expect(source.x).toBeGreaterThanOrEqual(chat.x + chat.width - 1);
  } else {
    await page.getByRole("navigation", { name: "阅读工作区" }).getByRole("button", { name: "对话", exact: true }).click();
  }
  await expect(draft).toHaveValue("请结合这段来源继续解释");
  expect(await conversation.evaluate(el => el.scrollTop)).toBeCloseTo(before, 0);
  expect(await noHorizontalOverflow(page)).toBe(true);
  expect(errors).toEqual([]);
});
