import { expect, test } from "@playwright/test";
import { installApiFixture, makeLearningSession, seedWorkspaceRecovery } from "./api-fixture";
import { noHorizontalOverflow } from "./journey-metrics";

test("panel widths can be dragged, restored and kept across reload without changing the draft", async ({ page }) => {
  const session = makeLearningSession();
  await installApiFixture(page, { session });
  await seedWorkspaceRecovery(page, session.row.session_id);
  const document = { document_id: "resize-sample", source_path: "ui-validation/resize.txt", title: "调整面板验收", file_type: "txt", evidence_status: "active", chunks: 1 };
  await page.route("**/knowledge-base/documents", r => r.fulfill({ json: {
    index_exists: true, documents: [document], chunks: 1, retrievable_documents: 1, retrievable_chunks: 1,
  } }));
  await page.route("**/knowledge-base/documents/resize-sample/reading?*", r => r.fulfill({ json: {
    ...document, schema_version: "document-reading-v1", representation: "indexed_text", scope: "knowledge",
    revision_id: "ui-v1", content_hash: "sample", parser_version: "fixture", start_line: 1, end_line: 2, total_lines: 2,
    text: "调整面板验收\n这是隔离 UI 验收资料。",
  } }));
  const openDocument = async () => {
    if (!(await page.getByLabel("管理阅读资料").filter({ visible: true }).isVisible())) await page.getByLabel("打开会话历史").click();
    await page.getByLabel("管理阅读资料").filter({ visible: true }).click();
    await page.getByRole("button", { name: "阅读正文", exact: true }).click();
    await expect(page.locator(".document-paper")).toBeVisible();
  };
  await page.goto("/");
  await expect(page.getByText("我们已经确认每轮会缩小搜索区间。", { exact: true })).toBeVisible();
  await openDocument();
  const sidebar = page.getByRole("separator", { name: "调整左侧导航宽度" });
  const reading = page.getByRole("separator", { name: "调整正文与对话宽度" });
  if (page.viewportSize()!.width <= 900) {
    await expect(sidebar).toBeHidden();
    await expect(reading).toBeHidden();
    await page.getByRole("navigation", { name: "阅读工作区" }).getByRole("button", { name: "对话", exact: true }).click();
    await expect(page.getByLabel("输入学习问题")).toBeVisible();
    expect(await noHorizontalOverflow(page)).toBe(true);
    return;
  }
  const width = async (selector: string) => (await page.locator(selector).boundingBox())!.width;
  const initialSidebar = await width(".session-sidebar");
  await page.getByLabel("输入学习问题").fill("调整宽度时保留这段草稿");
  const handle = (await sidebar.boundingBox())!;
  await page.mouse.move(handle.x + 6, handle.y + handle.height / 2);
  await page.mouse.down();
  await page.mouse.move(handle.x + 70, handle.y + handle.height / 2, { steps: 5 });
  await page.mouse.up();
  await expect.poll(() => width(".session-sidebar")).toBeCloseTo(initialSidebar + 64, 0);
  const savedSidebar = await width(".session-sidebar");
  const initialReading = await width(".document-reader");
  await reading.focus();
  await reading.press("ArrowLeft");
  await expect.poll(() => width(".document-reader")).toBeCloseTo(initialReading - 16, 0);
  const savedReading = await width(".document-reader");
  await expect(page.getByLabel("输入学习问题")).toHaveValue("调整宽度时保留这段草稿");
  await page.reload();
  await openDocument();
  await expect.poll(() => width(".session-sidebar")).toBeCloseTo(savedSidebar, 0);
  await expect.poll(() => width(".document-reader")).toBeCloseTo(savedReading, 0);
  await reading.press("End");
  expect(await width(".chat-column")).toBeGreaterThanOrEqual(359);
  await reading.press("Home");
  expect(await width(".document-reader")).toBeGreaterThanOrEqual(359);
  await page.setViewportSize({ width: 1101, height: 800 });
  await sidebar.press("End");
  expect(await width(".document-reader")).toBeGreaterThanOrEqual(359);
  expect(await width(".chat-column")).toBeGreaterThanOrEqual(359);
  expect(await noHorizontalOverflow(page)).toBe(true);
  await sidebar.dblclick();
  await reading.focus();
  await reading.press("Enter");
  await expect.poll(() => width(".session-sidebar")).toBeCloseTo(192, 0);
  expect(await page.evaluate(() => localStorage.getItem("study-agent:panel-width:sidebar:v1"))).toBeNull();
  expect(await page.evaluate(() => localStorage.getItem("study-agent:panel-width:reading:v1"))).toBeNull();
});
