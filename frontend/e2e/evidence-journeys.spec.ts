import { expect, test, type Page } from "@playwright/test";

import {
  MATERIAL_CANDIDATE_TITLE,
  MATERIAL_FILE,
  MATERIAL_REPLY,
  MATERIAL_SELECTED_TITLE,
  RESEARCH_CANDIDATE_TITLE,
  RESEARCH_REPLY,
  RESEARCH_RUN_ID,
  RESEARCH_SELECTED_TITLE,
  SOURCE_CANDIDATE_TITLE,
  SOURCE_REPLY,
  SOURCE_SELECTED_TITLE,
  installEvidenceApiFixture,
  makeSourceCodeSession,
} from "./evidence-fixture";
import {
  noHorizontalOverflow,
  recordMetric,
  requiredComposerDecisions,
  visibleProductSurfaces,
} from "./journey-metrics";

const STORAGE_KEY = "study-agent-react-session";

async function seedWorkspaceOnce(
  page: Page,
  options: { sessionId?: string; webLookupRunId?: string } = {},
) {
  await page.addInitScript(
    ({ key, workspace }) => {
      if (window.localStorage.getItem(key)) return;
      window.localStorage.setItem(
        key,
        JSON.stringify({
          schemaVersion: 3,
          savedAt: new Date().toISOString(),
          workspace,
        }),
      );
    },
    {
      key: STORAGE_KEY,
      workspace: {
        singleChatSessionId: options.sessionId,
        lastSessionId: options.sessionId,
        webLookupRunId: options.webLookupRunId,
        ragEnabled: true,
        chatSettings: {
          selectedRole: "auto",
          selectedMode: "苏格拉底",
          selectedModel: "auto",
          relationshipMode: "standard",
          contextMode: "light",
        },
        ragSettings: {
          retrievalMode: "hybrid",
          topK: 5,
          chatTopK: 3,
          minScore: 0.01,
        },
      },
    },
  );
}

async function installUploadRunRestoreFixture(page: Page) {
  await page.route("**/rag-runs/rag-upload-browser", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "rag-upload-browser",
        kind: "upload",
        status: "completed",
        request: { file_count: 1 },
        result: {
          documents: 1,
          chunks: 2,
          index_version: 2,
          stages: [
            { name: "parse", status: "completed" },
            { name: "index", status: "completed" },
          ],
        },
        error: "",
        index_version: 2,
        version: 1,
        created_at: "2026-07-27T10:00:00Z",
        updated_at: "2026-07-27T10:00:00Z",
        completed_at: "2026-07-27T10:00:00Z",
      }),
    });
  });
}

async function openEvidence(page: Page) {
  const toggle = page.getByRole("button", { name: /证据轨迹/ }).last();
  await expect(toggle).toBeVisible();
  await toggle.click();
  return page.getByRole("region", { name: "回答采用的证据" });
}

test("uploaded material becomes a learning choice with adopted local evidence", async ({ page }, testInfo) => {
  const fixture = await installEvidenceApiFixture(page);
  await installUploadRunRestoreFixture(page);
  await page.goto("/");

  let requiredClicks = 0;
  let requiredDecisions = 0;
  const chooserPromise = page.waitForEvent("filechooser");
  requiredClicks += 1;
  if (!(await page.getByLabel("上传学习资料").filter({visible:true}).isVisible())) await page.getByLabel("打开会话历史").click();
  await page.getByLabel("上传学习资料").filter({visible:true}).click();
  const chooser = await chooserPromise;
  await chooser.setFiles({
    name: MATERIAL_FILE,
    mimeType: "text/markdown",
    buffer: Buffer.from("# 二分查找\n每轮把候选区间缩小一半。"),
  });

  await expect(page.getByText("资料已准备好", { exact: true })).toBeVisible();
  await expect(page.getByText(/已索引 1 个文档、2 个片段/)).toBeVisible();
  expect(fixture.uploaded).toBe(true);

  requiredClicks += 1;
  requiredDecisions += 1;
  await page.getByRole("button", { name: "开始系统学习" }).click();
  const composer = page.getByLabel("输入学习问题");
  await expect(composer).toHaveValue(/请基于刚上传的资料开始系统学习/);
  expect(await requiredComposerDecisions(page)).toBe(0);
  await composer.press("Enter");
  await expect(page.getByText(MATERIAL_REPLY, { exact: true })).toBeVisible();

  requiredClicks += 1;
  const adopted = await openEvidence(page);
  await expect(adopted.getByText(MATERIAL_SELECTED_TITLE, { exact: true })).toBeVisible();
  await expect(page.getByText(MATERIAL_CANDIDATE_TITLE, { exact: true })).toHaveCount(0);

  await page.waitForTimeout(350);
  await page.reload();
  await expect(page.getByText(MATERIAL_REPLY, { exact: true })).toBeVisible();
  const restoredAdopted = await openEvidence(page);
  await expect(
    restoredAdopted.getByText(MATERIAL_SELECTED_TITLE, { exact: true }),
  ).toBeVisible();

  expect(fixture.base.chatAttempts).toBe(1);
  expect(fixture.base.unexpectedApiPaths).toEqual([]);
  await recordMetric(testInfo, {
    journey: "material_learning_evidence",
    project: testInfo.project.name,
    viewport: page.viewportSize(),
    required_clicks: requiredClicks,
    required_decisions: requiredDecisions,
    product_surfaces: await visibleProductSurfaces(page),
    recovery_clicks: 0,
    has_actionable_failure: false,
    keyboard_only: false,
    refresh_restore: true,
    no_horizontal_overflow: await noHorizontalOverflow(page),
  });
});

test("failed web research recovers in chat and grounds the next answer", async ({ page }, testInfo) => {
  const fixture = await installEvidenceApiFixture(page);
  await seedWorkspaceOnce(page, { webLookupRunId: RESEARCH_RUN_ID });
  await page.goto("/");

  const failedStatus = page.getByRole("status").filter({ hasText: "研究失败" });
  await expect(failedStatus).toBeVisible();
  await expect(failedStatus).toContainText(
    "联网研究工具链未完成；未把未经校验的结果当成结论。",
  );
  await expect(page.getByText(/provider timeout/)).toHaveCount(0);
  const retry = page.getByRole("button", { name: "重试研究" });
  await expect(retry).toBeVisible();
  await retry.click();

  await expect(page.getByText("联网研究已恢复", { exact: true })).toBeVisible();
  await expect(page.getByText("恢复结果已设为下一轮聊天资料。", { exact: true })).toBeVisible();

  const composer = page.getByLabel("输入学习问题");
  await composer.fill("基于恢复的研究资料解释依赖注入边界");
  await composer.press("Enter");
  await expect(page.getByText(RESEARCH_REPLY, { exact: true })).toBeVisible();

  const adopted = await openEvidence(page);
  await expect(adopted.getByText(RESEARCH_SELECTED_TITLE, { exact: true })).toBeVisible();
  await expect(page.getByText(RESEARCH_CANDIDATE_TITLE, { exact: true })).toHaveCount(0);
  expect(fixture.chatPayloads.at(-1)?.web_context_run_id).toBe(RESEARCH_RUN_ID);

  await page.waitForTimeout(350);
  await page.reload();
  await expect(page.getByText(RESEARCH_REPLY, { exact: true })).toBeVisible();
  await expect(page.getByText("联网研究已恢复", { exact: true })).toHaveCount(0);
  await expect(
    page.getByText("恢复结果已设为下一轮聊天资料。", { exact: true }),
  ).toHaveCount(0);
  const restoredAdopted = await openEvidence(page);
  await expect(
    restoredAdopted.getByText(RESEARCH_SELECTED_TITLE, { exact: true }),
  ).toBeVisible();

  expect(fixture.base.chatAttempts).toBe(1);
  expect(fixture.base.unexpectedApiPaths).toEqual([]);
  await recordMetric(testInfo, {
    journey: "web_research_recovery_evidence",
    project: testInfo.project.name,
    viewport: page.viewportSize(),
    required_clicks: 2,
    required_decisions: 0,
    product_surfaces: await visibleProductSurfaces(page),
    recovery_clicks: 1,
    has_actionable_failure: true,
    keyboard_only: false,
    refresh_restore: true,
    no_horizontal_overflow: await noHorizontalOverflow(page),
  });
});

test("source-code evidence remains inside the learning goal", async ({ page }, testInfo) => {
  const session = makeSourceCodeSession();
  const fixture = await installEvidenceApiFixture(page, { sourceSession: session });
  await seedWorkspaceOnce(page, { sessionId: session.row.session_id });
  await page.goto("/");

  await page.getByText("本会话学习上下文", {exact:true}).click();
  const restoreCard = page.getByRole("region", { name: "继续当前任务" });
  await expect(
    restoreCard.getByRole("heading", { name: "通过 FastAPI 源码理解依赖注入调用链" }),
  ).toBeVisible();
  await expect(
    restoreCard.getByText("用自己的话解释一次依赖解析调用链", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText(SOURCE_REPLY, { exact: true })).toBeVisible();

  const menuText = await page.locator(".workspace-menu-popover").textContent();
  expect(menuText).not.toContain("GitHub");

  const adopted = await openEvidence(page);
  await expect(adopted.getByText(SOURCE_SELECTED_TITLE, { exact: true })).toBeVisible();
  await expect(page.getByText(SOURCE_CANDIDATE_TITLE, { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: /证据轨迹/ }).last().click();

  await expect(
    restoreCard.getByRole("heading", { name: "通过 FastAPI 源码理解依赖注入调用链" }),
  ).toBeVisible();
  await expect(
    restoreCard.getByText("用自己的话解释一次依赖解析调用链", { exact: true }),
  ).toBeVisible();

  await page.reload();
  await expect(page.getByText(SOURCE_REPLY, { exact: true })).toBeVisible();
  const restoredAdopted = await openEvidence(page);
  await expect(
    restoredAdopted.getByText(SOURCE_SELECTED_TITLE, { exact: true }),
  ).toBeVisible();

  expect(fixture.base.unexpectedApiPaths).toEqual([]);
  await recordMetric(testInfo, {
    journey: "source_code_learning_evidence",
    project: testInfo.project.name,
    viewport: page.viewportSize(),
    required_clicks: 2,
    required_decisions: 0,
    product_surfaces: await visibleProductSurfaces(page),
    recovery_clicks: 0,
    has_actionable_failure: false,
    keyboard_only: false,
    refresh_restore: true,
    no_horizontal_overflow: await noHorizontalOverflow(page),
  });
});