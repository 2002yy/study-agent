import { expect, test } from "@playwright/test";

import {
  FIRST_REPLY,
  installApiFixture,
  makeLearningSession,
  seedWorkspaceRecovery,
} from "./api-fixture";
import { captureComplexSuccessStep } from "./complex-content-evidence";
import {
  installJourneyRecorder,
  journeyActionSummary,
  noHorizontalOverflow,
  recordObservedMetric,
  requiredComposerDecisions,
} from "./journey-metrics";

const JOURNEY = "complex_content_narrow";
const COMPOSED_QUESTION = "输入法组合结束后，请继续解释二分查找边界。";
const LONG_URL = `https://example.com/knowledge/${"boundary-proof-without-break-point".repeat(7)}?source=${"narrow-screen-evidence".repeat(6)}`;
const LONG_IDENTIFIER = "extremelyLongBoundaryInvariantIdentifierWithoutNaturalBreakPoint".repeat(6);
const LONG_CHINESE = "这是一段用于验证窄屏自动换行的连续中文说明，强调候选区间、左右边界、中点排除和终止条件之间的因果关系。".repeat(9);
const COMPLEX_REPLY = [
  "# 二分查找窄屏复杂内容验证",
  "",
  LONG_CHINESE,
  "",
  "## 超长链接",
  "",
  `<${LONG_URL}>`,
  "",
  "## 宽代码块",
  "",
  "```typescript",
  `const ${LONG_IDENTIFIER} = candidates.filter((item) => item.leftBoundary <= item.rightBoundary && item.middleIndex !== item.discardedIndex);`,
  "function updateBoundary(target: number, middle: number) {",
  "  return target > middle ? { left: middle + 1 } : { right: middle - 1 };",
  "}",
  "```",
  "",
  "## 多段检查清单",
  "",
  "1. 先确认数组有序。",
  "2. 再比较目标值与中点值。",
  "3. 排除已经比较过的中点。",
  "4. 当左边界超过右边界时停止。",
  "",
  ...Array.from({ length: 12 }, (_, index) =>
    `- 第 ${index + 1} 轮练习：说明为什么边界更新后仍保持“目标若存在则一定留在候选区间”这一不变量。`,
  ),
].join("\n");

function complexSession() {
  const session = makeLearningSession();
  session.row.title = "二分查找复杂内容与窄屏恢复";
  session.row.objective = "验证复杂学习内容在窄屏下仍可阅读与恢复";
  session.detail.messages = [
    {
      role: "user",
      content: "请展示一份包含长中文、长链接、宽代码和多段列表的学习材料。",
      turnId: "turn-complex-content",
      turnStatus: "completed",
    },
    {
      role: "assistant",
      content: COMPLEX_REPLY,
      avatarRole: "nahida",
      turnId: "turn-complex-content",
      turnStatus: "completed",
    },
  ];
  session.detail.turns = [
    {
      ...session.detail.turns[0],
      turn_id: "turn-complex-content",
      user_message: "请展示一份包含长中文、长链接、宽代码和多段列表的学习材料。",
      assistant_message: COMPLEX_REPLY,
    },
  ];
  return session;
}

test("360x520 keeps complex content, IME input and real scroll recovery usable", async ({
  page,
}, testInfo) => {
  expect(testInfo.project.name).toBe("narrow-chromium");
  const session = complexSession();
  const fixture = await installApiFixture(page, { session });
  await seedWorkspaceRecovery(page, session.row.session_id);
  await installJourneyRecorder(page);
  await page.goto("/");

  const successArtifacts: string[] = [];
  const conversation = page.getByRole("region", { name: "学习对话" });
  const composer = page.getByLabel("输入学习问题");
  const longLink = conversation.locator(
    '.markdown-message a[href^="https://example.com/knowledge/"]',
  );
  const codeBlock = conversation.locator(".markdown-message pre").first();

  await expect(page.getByRole("heading", { level: 1, name: "对话" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
  await expect(longLink).toHaveText(LONG_URL);
  await expect(longLink).toBeVisible();
  await expect(codeBlock).toBeVisible();
  expect(await noHorizontalOverflow(page)).toBe(true);

  const conversationBounds = await conversation.boundingBox();
  expect(conversationBounds).not.toBeNull();
  expect(conversationBounds!.x).toBeGreaterThanOrEqual(0);
  expect(conversationBounds!.x + conversationBounds!.width).toBeLessThanOrEqual(360.5);

  // Session restoration can replace the rendered text node during layout measurement.
  // Retry the full measurement together; keep all wrapping and bounds assertions.
  await expect(async () => {
    await longLink.scrollIntoViewIfNeeded();
    const linkMetrics = await longLink.evaluate((element) => {
      const messageBody = element.closest(".message-body") as HTMLElement | null;
      const bodyRect = messageBody?.getBoundingClientRect();
      const range = document.createRange();
      range.selectNodeContents(element);
      const textRects = Array.from(range.getClientRects()).filter(
        (rect) => rect.width > 0 && rect.height > 0,
      );
      const lineTops = new Set(textRects.map((rect) => Math.round(rect.top)));
      return {
        linkLeft: textRects.length > 0 ? Math.min(...textRects.map((rect) => rect.left)) : 0,
        linkRight: textRects.length > 0 ? Math.max(...textRects.map((rect) => rect.right)) : 0,
        bodyLeft: bodyRect?.left ?? 0,
        bodyRight: bodyRect?.right ?? 0,
        bodyScrollWidth: messageBody?.scrollWidth ?? 0,
        bodyClientWidth: messageBody?.clientWidth ?? 0,
        linkRectCount: textRects.length,
        linkLineCount: lineTops.size,
      };
    });
    expect(linkMetrics.linkRectCount).toBeGreaterThan(0);
    expect(linkMetrics.linkLineCount).toBeGreaterThan(1);
    expect(linkMetrics.bodyScrollWidth).toBeLessThanOrEqual(linkMetrics.bodyClientWidth + 1);
    expect(linkMetrics.linkLeft).toBeGreaterThanOrEqual(linkMetrics.bodyLeft - 1);
    expect(linkMetrics.linkRight).toBeLessThanOrEqual(linkMetrics.bodyRight + 1);
  }).toPass({ timeout: 5_000 });
  successArtifacts.push(
    await captureComplexSuccessStep(page, testInfo, JOURNEY, "long-text-and-url"),
  );

  await codeBlock.scrollIntoViewIfNeeded();
  const codeMetrics = await codeBlock.evaluate((element) => ({
    scrollWidth: element.scrollWidth,
    clientWidth: element.clientWidth,
    overflowX: getComputedStyle(element).overflowX,
  }));
  expect(codeMetrics.scrollWidth).toBeGreaterThan(codeMetrics.clientWidth);
  expect(["auto", "scroll"]).toContain(codeMetrics.overflowX);
  expect(await noHorizontalOverflow(page)).toBe(true);
  successArtifacts.push(
    await captureComplexSuccessStep(page, testInfo, JOURNEY, "wide-code"),
  );

  const composerDecisions = await requiredComposerDecisions(page);
  await composer.focus();
  await composer.dispatchEvent("compositionstart", { data: "二分" });
  await composer.fill(COMPOSED_QUESTION);
  await composer.dispatchEvent("compositionupdate", { data: COMPOSED_QUESTION });
  await composer.evaluate((element) => {
    element.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "Enter",
        bubbles: true,
        cancelable: true,
        isComposing: true,
      }),
    );
  });
  await page.waitForTimeout(120);
  expect(fixture.chatAttempts).toBe(0);
  await expect(composer).toHaveValue(COMPOSED_QUESTION);

  await composer.dispatchEvent("compositionend", { data: COMPOSED_QUESTION });
  await composer.press("Enter");
  const latestReply = page.getByText(FIRST_REPLY, { exact: true });
  await expect(latestReply).toBeVisible();
  expect(fixture.chatAttempts).toBe(1);

  const initialScroll = await conversation.evaluate((element) => ({
    top: element.scrollTop,
    max: element.scrollHeight - element.clientHeight,
    scrollHeight: element.scrollHeight,
    clientHeight: element.clientHeight,
  }));
  expect(initialScroll.scrollHeight).toBeGreaterThan(initialScroll.clientHeight + 300);
  expect(initialScroll.top).toBeGreaterThan(initialScroll.max - 100);

  await latestReply.hover();
  await page.mouse.wheel(0, -700);
  await expect
    .poll(() => conversation.evaluate((element) => element.scrollTop))
    .toBeLessThan(initialScroll.top - 80);
  await expect(page.getByRole("button", { name: "回到最新" })).toBeVisible();
  const scrollSummary = await journeyActionSummary(page);
  expect(scrollSummary.scrolls).toBeGreaterThan(0);
  successArtifacts.push(
    await captureComplexSuccessStep(page, testInfo, JOURNEY, "user-scrolled"),
  );

  await page.getByRole("button", { name: "回到最新" }).click();
  await expect
    .poll(() =>
      conversation.evaluate(
        (element) => element.scrollHeight - element.scrollTop - element.clientHeight,
      ),
    )
    .toBeLessThan(80);
  successArtifacts.push(
    await captureComplexSuccessStep(page, testInfo, JOURNEY, "back-to-latest"),
  );

  await page.reload();
  await expect(longLink).toHaveText(LONG_URL);
  await expect(page.getByText(FIRST_REPLY, { exact: true })).toBeVisible();
  await expect(composer).toBeVisible();
  const composerBox = await composer.boundingBox();
  const sendBox = await page.getByRole("button", { name: "发送" }).boundingBox();
  expect(composerBox).not.toBeNull();
  expect(sendBox).not.toBeNull();
  expect(composerBox!.y).toBeGreaterThanOrEqual(0);
  expect(composerBox!.y + composerBox!.height).toBeLessThanOrEqual(520.5);
  expect(sendBox!.y + sendBox!.height).toBeLessThanOrEqual(520.5);
  expect(await noHorizontalOverflow(page)).toBe(true);
  successArtifacts.push(
    await captureComplexSuccessStep(page, testInfo, JOURNEY, "restored"),
  );

  expect(fixture.unexpectedApiPaths).toEqual([]);
  await recordObservedMetric(page, testInfo, {
    journey: JOURNEY,
    composer_decisions: composerDecisions,
    refresh_restore: true,
    has_actionable_failure: false,
    success_artifacts: successArtifacts,
  });
});
