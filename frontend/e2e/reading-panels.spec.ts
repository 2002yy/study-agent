import { expect, test } from "@playwright/test";
import { installApiFixture, makeLearningSession, seedWorkspaceRecovery } from "./api-fixture";
import { noHorizontalOverflow } from "./journey-metrics";

test("separate reading and chat panels keep the draft, evidence and focus controls usable", async ({ page }) => {
  const session = makeLearningSession();
  await installApiFixture(page, { session });
  await seedWorkspaceRecovery(page, session.row.session_id);
  const document = { document_id: "panel-sample", source_path: "ui-validation/panels.txt", title: "面板验收样例", file_type: "txt", evidence_status: "active", chunks: 1 };
  await page.route("**/knowledge-base/documents", route => route.fulfill({ json: {
    index_exists: true, documents: [document], chunks: 1, retrievable_documents: 1, retrievable_chunks: 1,
  } }));
  await page.route("**/knowledge-base/documents/panel-sample/reading?*", route => route.fulfill({ json: {
    ...document, schema_version: "document-reading-v1", representation: "indexed_text", scope: "knowledge",
    revision_id: "ui-v1", content_hash: "sample", parser_version: "fixture", start_line: 1, end_line: 3, total_lines: 3,
    text: "面板验收样例\n这是隔离 UI 验收资料。\n阅读正文时也可以继续对话。",
  } }));
  await page.goto("/");
  await expect(page.getByText("我们已经确认每轮会缩小搜索区间。", { exact: true })).toBeVisible();
  const draft = page.locator(".composer textarea");
  await draft.fill("保留我正在写的问题");
  if (!(await page.getByLabel("管理阅读资料").filter({ visible: true }).isVisible())) await page.getByLabel("打开会话历史").click();
  await page.getByLabel("管理阅读资料").filter({ visible: true }).click();
  await page.getByRole("button", { name: "阅读正文", exact: true }).click();
  await expect(page.locator(".document-paper")).toBeVisible();
  if (page.viewportSize()!.width > 900) {
    const reader = (await page.locator(".document-reader").boundingBox())!;
    const chat = (await page.locator(".chat-column").boundingBox())!;
    expect(chat.x - reader.x - reader.width).toBeGreaterThanOrEqual(15.5);
    await page.getByRole("button", { name: "专注", exact: true }).click();
    await expect(page.locator(".chat-column")).toBeHidden();
    await page.getByRole("button", { name: "恢复并排", exact: true }).click();
  } else {
    await page.getByRole("navigation", { name: "阅读工作区" }).getByRole("button", { name: "对话", exact: true }).click();
  }
  await expect(draft).toHaveValue("保留我正在写的问题");
  const answer = page.locator(".message.assistant");
  await expect(answer.locator(".message-bubble")).toContainText("我们已经确认每轮会缩小搜索区间。");
  await expect(answer.getByRole("button", { name: "复制回答正文" })).toBeVisible();
  await expect(answer.locator(".message-bubble .evidence-trail")).toHaveCount(0);
  await answer.getByRole("button", { name: "证据轨迹" }).click();
  expect(await noHorizontalOverflow(page)).toBe(true);
});
