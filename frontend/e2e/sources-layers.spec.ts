import { expect, test } from "@playwright/test";

import { seedWorkspaceRecovery } from "./api-fixture";
import {
  SOURCE_CANDIDATE_TITLE,
  SOURCE_REPLY,
  SOURCE_SELECTED_TITLE,
  installEvidenceApiFixture,
  makeSourceCodeSession,
} from "./evidence-fixture";
import { noHorizontalOverflow } from "./journey-metrics";

test("sources drawer separates adopted evidence, documents, and diagnostics", async ({ page }) => {
  const session = makeSourceCodeSession();
  const fixture = await installEvidenceApiFixture(page, { sourceSession: session });
  await page.route("**/knowledge-base/documents", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        index_path: "browser-fixture",
        index_exists: true,
        index_version: 4,
        chunks: 5,
        retrievable_documents: 1,
        retrievable_chunks: 3,
        documents: [
          {
            document_id: "source-notes-current",
            revision_id: "source-notes-rev-1",
            title: "FastAPI source notes",
            source_path: "notes/fastapi-source.md",
            file_type: "md",
            content_hash: "source-notes-current",
            chunks: 3,
            metadata: {},
            evidence_status: "active",
          },
          {
            document_id: "source-notes-old",
            revision_id: "source-notes-rev-0",
            title: "Old FastAPI notes",
            source_path: "notes/fastapi-old.md",
            file_type: "md",
            content_hash: "source-notes-old",
            chunks: 2,
            metadata: {},
            evidence_status: "superseded",
          },
        ],
      }),
    });
  });
  await seedWorkspaceRecovery(page, session.row.session_id);
  await page.goto("/");
  await expect(page.getByText(SOURCE_REPLY, { exact: true })).toBeVisible();

  await page.getByLabel("打开更多学习工具").click();
  await page.getByRole("menuitem", { name: /资料与来源/ }).click();
  const dialog = page.getByRole("dialog", { name: "资料与来源" });
  await expect(dialog).toBeVisible();

  const answerTab = dialog.getByRole("tab", { name: "本次回答依据" });
  await expect(answerTab).toHaveAttribute("aria-selected", "true");
  let panel = dialog.getByRole("tabpanel");
  await expect(panel.getByText(SOURCE_SELECTED_TITLE, { exact: true })).toBeVisible();
  await expect(panel.getByText("教学明确引用", { exact: true })).toBeVisible();
  await expect(panel.getByText(SOURCE_CANDIDATE_TITLE, { exact: true })).toHaveCount(0);
  await expect(panel.getByText(/分数：/)).toHaveCount(0);
  await expect(panel.getByText("FastAPI source notes", { exact: true })).toHaveCount(0);

  await dialog.getByRole("tab", { name: "检索诊断" }).click();
  panel = dialog.getByRole("tabpanel");
  await expect(panel.getByRole("heading", { name: "证据生命周期" })).toBeVisible();
  await expect(panel.getByText(SOURCE_CANDIDATE_TITLE, { exact: true })).toBeVisible();
  await expect(panel.getByText("分数：0.370", { exact: true })).toBeVisible();
  await expect(panel.getByText("生命周期：候选", { exact: true })).toBeVisible();
  await expect(panel.getByText("FastAPI source notes", { exact: true })).toHaveCount(0);

  await dialog.getByRole("tab", { name: "我的资料" }).click();
  panel = dialog.getByRole("tabpanel");
  await expect(panel.getByText("FastAPI source notes", { exact: true })).toBeVisible();
  await expect(panel.getByText("Old FastAPI notes", { exact: true })).toBeVisible();
  await expect(panel.getByText("当前资料 · 会参与回答", { exact: true })).toBeVisible();
  await expect(panel.getByText("旧版本 · 不参与回答", { exact: true })).toBeVisible();
  await expect(panel.getByText(SOURCE_CANDIDATE_TITLE, { exact: true })).toHaveCount(0);
  await expect(panel.getByText(/分数：/)).toHaveCount(0);

  // The reading launcher opens the library; More -> sources keeps its answer
  // evidence entry point, including after returning from the reading launcher.
  await dialog.getByRole("button", { name: "关闭资料与来源", exact: true }).click();
  await page.getByRole("button", { name: "阅读资料", exact: true }).click();
  await expect(dialog.getByRole("tab", { name: "我的资料" })).toHaveAttribute("aria-selected", "true");
  await dialog.getByRole("button", { name: "关闭资料与来源", exact: true }).click();
  await page.getByLabel("打开更多学习工具").click();
  await page.getByRole("menuitem", { name: /资料与来源/ }).click();
  await expect(dialog.getByRole("tab", { name: "本次回答依据" })).toHaveAttribute("aria-selected", "true");

  expect(await noHorizontalOverflow(page)).toBe(true);
  expect(fixture.base.unexpectedApiPaths).toEqual([]);
});
