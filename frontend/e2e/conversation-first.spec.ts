import { expect, test } from "@playwright/test";
import { installApiFixture, makeLearningSession, seedWorkspaceRecovery } from "./api-fixture";
import { researchFixture } from "../src/features/answer-ui/researchPresentation.fixture";
import { noHorizontalOverflow } from "./journey-metrics";

const scenes = [
  { id: "firefly", title: "流萤：版本配队研究", question: "帮我按版本梳理流萤配队与投入选择。", body: "## 先明确研究范围\n\n这是阅读布局示意，尚无配队结论。我们会区分历史版本与目标版本，再比较机制、替代方案和投入条件。\n\n## 下一步核对\n\n先核对每个时期可用的角色与机制；尚未获准发布的研究不会作为建议。\n\n查看[来源 1](https://example.com/a)，可以继续追问其中一个研究问题。" },
  { id: "go", title: "围棋：从规则开始", question: "系统教我围棋，边解释边让我练习。", body: "## 从一个小问题开始\n\n这是教学阅读布局示意，不记录真实学习结果。我们会先解释一个概念，再让你尝试，最后根据实际作答继续。\n\n## 你的下一步\n\n告诉我你已经了解哪些规则；棋盘和测验可以嵌入后续回答，不必切换到研究控制台。\n\n查看[来源 1](https://example.com/a)，或继续讨论课程安排。" },
];

for (const scene of scenes) test(`${scene.id}: answer canvas, citation and recoverable research`, async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  const session = makeLearningSession();
  session.row.title = scene.title;
  session.detail.messages[0].content = scene.question;
  session.detail.messages[1].content = scene.body;
  session.detail.turns[0].user_message = scene.question;
  session.detail.turns[0].assistant_message = scene.body;
  await installApiFixture(page, { session });
  await seedWorkspaceRecovery(page, session.row.session_id);
  const snapshot = researchFixture();
  snapshot.session_id = session.row.session_id; snapshot.turn_id = "turn-returning-1";
  snapshot.blocks[0].tier = "deep"; snapshot.blocks[0].research_status = "partial";
  snapshot.blocks[0].stop_reason = "evidence_saturated";
  snapshot.audit_status = "audited"; snapshot.audit_integrity = "valid"; snapshot.watch = false;
  await page.route("**/research-presentation", route => route.fulfill({json: snapshot}));
  await page.goto("/");
  const answer = page.locator(".message.assistant .markdown-message").last();
  await expect(answer).toContainText("布局示意");
  await expect(page.locator(".research-status-row")).toContainText("仍有待确认问题");
  await expect(page.locator(".research-tier-list")).toHaveCount(0);
  const prose = await answer.innerText();
  const metrics = await answer.evaluate(element => ({size: parseFloat(getComputedStyle(element).fontSize), lineHeight: parseFloat(getComputedStyle(element).lineHeight), width: element.getBoundingClientRect().width}));
  expect(metrics.size).toBeGreaterThanOrEqual(15);
  expect(metrics.width).toBeLessThanOrEqual(820);
  expect(metrics.lineHeight / metrics.size).toBeCloseTo(1.65, 1);
  const scroll = page.locator(".conversation");
  const composer = page.locator(".composer");
  expect((await scroll.boundingBox())!.y + (await scroll.boundingBox())!.height).toBeLessThanOrEqual((await composer.boundingBox())!.y + 1);
  await page.getByRole("button", {name: "来源 1", exact: true}).click();
  const mobile = testInfo.project.name.includes("mobile");
  const panel = page.getByRole(mobile ? "dialog" : "complementary", { name: "研究资料" });
  await expect(panel).toBeVisible();
  await expect(panel.getByText(/尚未获准发布/)).toBeVisible();
  await expect(panel.locator(".research-readable-sources .is-selected")).toBeFocused();
  expect(await answer.innerText()).toBe(prose);
  if (!mobile) expect((await panel.boundingBox())!.width).toBe(320);
  expect(await noHorizontalOverflow(page)).toBe(true);
  await page.screenshot({path: `D:/study-agent-validation/reading-notebook-ui-evidence/conversation-${scene.id}-${testInfo.project.name}.png`});
  await panel.locator(".is-selected").press("Escape");
  await expect(panel).toHaveCount(0);
  await expect(page.getByRole("button", {name: "研究资料", exact: true})).toBeFocused();
  await page.reload();
  await expect(answer).toHaveText(prose);
  await expect(page.locator(".research-tier-list")).toHaveCount(0);
  await page.screenshot({path: `D:/study-agent-validation/reading-notebook-ui-evidence/conversation-${scene.id}-${testInfo.project.name}-answer.png`});
  expect(errors).toEqual([]);
});
