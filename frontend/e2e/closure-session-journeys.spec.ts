import { expect, test } from "@playwright/test";

import {
  installApiFixture,
  makeLearningSession,
  seedWorkspaceRecovery,
} from "./api-fixture";
import { noHorizontalOverflow } from "./journey-metrics";

test("learning closure reviews evidence before saving and can archive into a fresh session", async ({
  page,
}) => {
  const session = makeLearningSession();
  const fixture = await installApiFixture(page, { session });
  await seedWorkspaceRecovery(page, session.row.session_id);
  await page.goto("/");

  if (!(await page.getByRole("button", { name: "整理学习" }).isVisible())) await page.getByLabel("打开会话历史").click();
  await page.getByRole("button", { name: "整理学习" }).click();

  const review = page.getByTestId("learning-closure-review");
  await expect(review.getByRole("heading", { name: "回顾这次学习" })).toBeVisible();
  await expect(review.getByText("已确认：每轮会缩小搜索区间")).toBeVisible();
  await expect(review.getByText("还需解释左右边界更新时机")).toBeVisible();
  await expect(review.getByText("下一步完成一次边界迁移练习")).toBeVisible();
  await expect(review.getByText("已经确认的学习进展")).toBeVisible();
  await expect(review.getByText("仍需补强的内容")).toBeVisible();
  await expect(review.getByText("下一次继续学习的重点")).toBeVisible();
  await expect(page.getByText("current_focus")).toHaveCount(0);
  await expect(page.getByText("revision_notes")).toHaveCount(0);
  await expect(page.locator("details.memory-advanced")).not.toHaveAttribute("open");
  expect(await noHorizontalOverflow(page)).toBe(true);

  await review.getByRole("button", { name: "确认并保存学习成果" }).click();
  const resultsDialog = page.getByRole("dialog", { name: "学习成果" });
  await expect(resultsDialog.getByText("本次已整理")).toBeVisible();
  await resultsDialog.getByRole("button", { name: "归档并新建" }).click();
  await expect(resultsDialog).toBeHidden();
  const transitionDialog = page.getByRole("dialog", { name: "归档当前会话前确认未完成工作" });
  await expect(transitionDialog).toBeVisible();
  await expect(transitionDialog.getByText("当前会话将进入历史记录")).toBeVisible();
  await transitionDialog.getByRole("button", { name: "仍然归档并新建" }).click();
  await expect(transitionDialog).toBeHidden();
  await expect(
    page.getByText("我们已经确认每轮会缩小搜索区间。", { exact: true }),
  ).toHaveCount(0);

  expect(fixture.sessions.some((row) => row.kind === "archived")).toBe(true);
  expect(fixture.unexpectedApiPaths).toEqual([]);
});

test("the shared session navigator is usable from desktop sidebar and mobile drawer", async ({
  page,
}, testInfo) => {
  const session = makeLearningSession();
  const fixture = await installApiFixture(page, { session });
  await seedWorkspaceRecovery(page, session.row.session_id);
  await page.goto("/");

  if (testInfo.project.name === "mobile-chromium") {
    await page.getByRole("button", { name: "打开会话历史" }).click();
    await expect(page.getByRole("heading", { name: "会话历史" })).toBeVisible();
  } else {
    await expect(page.getByText("学习会话", { exact: true })).toBeVisible();
  }

  const navigator = page.getByRole("navigation", { name: "学习会话" }).last();
  await expect(navigator).toBeVisible();
  const search = page.getByLabel("搜索学习会话").last();
  await search.fill("二分查找");
  await expect(navigator.getByText("二分查找", { exact: true })).toBeVisible();
  await search.fill("不存在的会话");
  await expect(navigator.getByText("没有匹配的会话。")).toBeVisible();
  expect(await noHorizontalOverflow(page)).toBe(true);
  expect(fixture.unexpectedApiPaths).toEqual([]);
});
