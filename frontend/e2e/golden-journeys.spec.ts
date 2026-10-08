import { expect, test } from "@playwright/test";

import {
  CONTINUE_REPLY,
  FIRST_QUESTION,
  FIRST_REPLY,
  RETRY_REPLY,
  installApiFixture,
  makeLearningSession,
  makeStaleLearningResume,
  seedWorkspaceRecovery,
} from "./api-fixture";
import {
  captureSuccessStep,
  focusComposerWithKeyboard,
  installJourneyRecorder,
  recordObservedMetric,
  requiredComposerDecisions,
} from "./journey-metrics";

test("first answer needs no configuration decision and survives refresh", async ({ page }, testInfo) => {
  const fixture = await installApiFixture(page);
  await installJourneyRecorder(page);
  await page.goto("/");

  const successArtifacts: string[] = [];
  await expect(page.getByRole("heading", { name: "学习工作台" })).toBeVisible();
  successArtifacts.push(
    await captureSuccessStep(page, testInfo, "first_answer", "ready"),
  );
  const composerDecisions = await requiredComposerDecisions(page);
  const tabPresses = await focusComposerWithKeyboard(page);
  expect(tabPresses).toBeLessThan(40);
  await page.keyboard.type(FIRST_QUESTION);
  await page.keyboard.press("Enter");

  await expect(page.getByText(FIRST_REPLY, { exact: true })).toBeVisible();
  successArtifacts.push(
    await captureSuccessStep(page, testInfo, "first_answer", "completed"),
  );
  await page.waitForTimeout(350);
  await page.reload();
  await expect(page.getByText(FIRST_REPLY, { exact: true })).toBeVisible();
  successArtifacts.push(
    await captureSuccessStep(page, testInfo, "first_answer", "restored"),
  );

  expect(fixture.chatAttempts).toBe(1);
  expect(fixture.unexpectedApiPaths).toEqual([]);
  await recordObservedMetric(page, testInfo, {
    journey: "first_answer",
    composer_decisions: composerDecisions,
    refresh_restore: true,
    has_actionable_failure: false,
    success_artifacts: successArtifacts,
  });
});

test("returning learner restores context and continues in one explicit choice", async ({ page }, testInfo) => {
  const session = makeLearningSession();
  const fixture = await installApiFixture(page, { session });
  await seedWorkspaceRecovery(page, session.row.session_id);
  await installJourneyRecorder(page);
  await page.goto("/");

  const successArtifacts: string[] = [];
  await page.getByText("本会话学习上下文", {exact:true}).click();
  const restoreCard = page.getByRole("region", { name: "继续当前任务" });
  await expect(restoreCard).toBeVisible();
  await expect(
    restoreCard.getByText("理解二分查找边界条件", { exact: true }),
  ).toBeVisible();
  await expect(
    restoreCard.getByText("每轮缩小搜索区间", { exact: true }),
  ).toBeVisible();
  await expect(
    restoreCard.getByText("左右边界更新时机", { exact: true }),
  ).toBeVisible();
  await expect(
    restoreCard.getByText("完成一次边界迁移练习", { exact: true }),
  ).toBeVisible();
  successArtifacts.push(
    await captureSuccessStep(page, testInfo, "returning_learning", "restored-context"),
  );

  const composerDecisions = await requiredComposerDecisions(page);
  await restoreCard.getByRole("button", { name: "继续这里" }).click();
  const composer = page.getByLabel("输入学习问题");
  await expect(composer).toHaveValue(/继续当前任务/);
  await composer.press("Enter");
  await expect(page.getByText(CONTINUE_REPLY, { exact: true })).toBeVisible();
  successArtifacts.push(
    await captureSuccessStep(page, testInfo, "returning_learning", "continued"),
  );

  await page.waitForTimeout(350);
  await page.reload();
  await expect(page.getByText(CONTINUE_REPLY, { exact: true })).toBeVisible();
  await page.getByText("本会话学习上下文", {exact:true}).click();
  const restoredCard = page.getByRole("region", { name: "继续当前任务" });
  await expect(
    restoredCard.getByText("理解二分查找边界条件", { exact: true }),
  ).toBeVisible();
  successArtifacts.push(
    await captureSuccessStep(page, testInfo, "returning_learning", "continued-restored"),
  );

  expect(fixture.chatAttempts).toBe(1);
  expect(fixture.unexpectedApiPaths).toEqual([]);
  await recordObservedMetric(page, testInfo, {
    journey: "returning_learning",
    composer_decisions: composerDecisions,
    refresh_restore: true,
    has_actionable_failure: false,
    success_artifacts: successArtifacts,
  });
});

test("chat failure exposes one-click retry and restores the answer", async ({ page }, testInfo) => {
  const fixture = await installApiFixture(page, { failNextChat: true });
  await installJourneyRecorder(page);
  await page.goto("/");

  const successArtifacts: string[] = [];
  const composerDecisions = await requiredComposerDecisions(page);
  const composer = page.getByLabel("输入学习问题");
  await composer.fill(FIRST_QUESTION);
  await composer.press("Enter");

  await expect(page.getByText("生成中断：本次回答未能完成，请稍后重试。", { exact: true })).toBeVisible();
  await expect(page.getByText(/聊天请求失败：503/)).toHaveCount(0);
  const retry = page.getByRole("button", { name: "重新生成" });
  await expect(retry).toBeVisible();
  successArtifacts.push(
    await captureSuccessStep(page, testInfo, "chat_failure_recovery", "failure-visible"),
  );
  await retry.click();
  await expect(page.getByText(RETRY_REPLY, { exact: true })).toBeVisible();
  successArtifacts.push(
    await captureSuccessStep(page, testInfo, "chat_failure_recovery", "recovered"),
  );

  await page.waitForTimeout(350);
  await page.reload();
  await expect(page.getByText(RETRY_REPLY, { exact: true })).toBeVisible();
  successArtifacts.push(
    await captureSuccessStep(page, testInfo, "chat_failure_recovery", "recovered-restored"),
  );

  expect(fixture.chatAttempts).toBe(2);
  expect(fixture.unexpectedApiPaths).toEqual([]);
  await recordObservedMetric(page, testInfo, {
    journey: "chat_failure_recovery",
    composer_decisions: composerDecisions,
    refresh_restore: true,
    has_actionable_failure: true,
    success_artifacts: successArtifacts,
  });
});

test("stale source claim surfaces and revalidates to current", async ({ page }, testInfo) => {
  const session = makeLearningSession();
  const fixture = await installApiFixture(page, {
    session,
    learningResume: makeStaleLearningResume(),
  });
  await seedWorkspaceRecovery(page, session.row.session_id);
  await installJourneyRecorder(page);
  await page.goto("/");

  const successArtifacts: string[] = [];
  await page.getByText("本会话学习上下文", {exact:true}).click();
  const restoreCard = page.getByRole("region", { name: "继续当前任务" });
  await expect(restoreCard).toBeVisible();
  await restoreCard.getByRole("button", { name: "继续这里" }).click();
  const composer = page.getByLabel("输入学习问题");
  await expect(composer).toHaveValue(/继续当前任务/);

  await page.locator(".workspace-learning-state > summary").click();
  const strip = page.getByRole("button", { name: /1 条源码已变动/ });
  await expect(strip).toBeVisible();
  successArtifacts.push(
    await captureSuccessStep(page, testInfo, "stale_revalidation", "stale-visible"),
  );

  const composerDecisions = await requiredComposerDecisions(page);
  await strip.click();
  const panel = page.locator("aside.learning-panel");
  await expect(panel).toBeVisible();
  await expect(panel.getByText("每轮循环会缩小搜索区间", { exact: true })).toBeVisible();
  await expect(
    panel.getByText("左右边界更新时机取决于中位数的取法", { exact: true }),
  ).toBeVisible();
  const revalidate = panel.getByRole("button", { name: /^重新验证 / }).first();
  await expect(revalidate).toBeVisible();
  await revalidate.click();
  await expect(
    page.getByRole("button", { name: /2 条已验证/ }),
  ).toBeVisible();
  successArtifacts.push(
    await captureSuccessStep(page, testInfo, "stale_revalidation", "revalidated-current"),
  );

  await page.waitForTimeout(350);
  await page.reload();
  await page.getByText("本会话学习上下文", {exact:true}).click();
  const restoredCard = page.getByRole("region", { name: "继续当前任务" });
  await expect(restoredCard).toBeVisible();
  await restoredCard.getByRole("button", { name: "继续这里" }).click();
  await page.locator(".workspace-learning-state > summary").click();
  await expect(
    page.getByRole("button", { name: /2 条已验证/ }),
  ).toBeVisible();
  successArtifacts.push(
    await captureSuccessStep(page, testInfo, "stale_revalidation", "revalidated-restored"),
  );

  expect(fixture.chatAttempts).toBe(0);
  expect(fixture.unexpectedApiPaths).toEqual([]);
  await recordObservedMetric(page, testInfo, {
    journey: "stale_revalidation",
    composer_decisions: composerDecisions,
    refresh_restore: true,
    has_actionable_failure: false,
    success_artifacts: successArtifacts,
  });
});
