import { expect, test } from "@playwright/test";
import { installApiFixture, makeLearningSession, seedWorkspaceRecovery } from "./api-fixture";
import { researchFixture } from "../src/features/answer-ui/researchPresentation.fixture";
import { noHorizontalOverflow } from "./journey-metrics";

const AVATAR_DIR = "D:/study-agent-validation/conversation-first-ui/assets/avatars";
const LONG_BODY = [
  "## 先明确研究范围\n\n这是阅读布局示意，尚无配队结论。我们会区分历史版本与目标版本，再比较机制、替代方案和投入条件。",
  "## 历史版本回顾\n\n早期版本对击破特攻与速度阈值更敏感，配队往往围绕单一核心展开；后期版本引入新的辅助与遗器后，收益曲线整体上移，单纯堆叠单一属性的边际收益下降。",
  "## 机制对比\n\n我们需要比较三种常见机制：直接增伤、行动提前与击破结算。它们在短轴与长轴下的收益并不一致，因此不能只看一次极限爆发就下结论。",
  "## 替代方案\n\n如果没有目标角色，退化方案通常保留主输出，用通用辅助与治疗补足生存；这会牺牲一部分上限，但能保证流程稳定、资源投入可控。",
  "## 投入条件\n\n遗器词条、速度档位与技能等级共同决定实际收益。建议先满足速度阈值，再追求双暴与击破特攻的平衡，避免为了极限词条牺牲循环。",
  "## 下一步核对\n\n先核对每个时期可用的角色与机制；尚未获准发布的研究不会作为建议。\n\n查看[来源 1](https://example.com/a)，可以继续追问其中一个研究问题。",
].join("\n\n");

const scenes = [
  { id: "firefly", title: "流萤：版本配队研究", role: "firefly", withResearch: true, question: "帮我按版本梳理流萤配队与投入选择。", body: LONG_BODY },
  { id: "go", title: "围棋：从规则开始", role: "keqing", withResearch: false, question: "系统教我围棋，边解释边让我练习。", body: "## 从一个小问题开始\n\n这是教学阅读布局示意，不记录真实学习结果。我们会先解释一个概念，再让你尝试，最后根据实际作答继续。\n\n## 你的下一步\n\n告诉我你已经了解哪些规则；棋盘和测验可以嵌入后续回答，不必切换到研究控制台。\n\n继续讨论课程安排即可。" },
];

for (const scene of scenes) test(`${scene.id}: answer canvas, citation and recoverable research`, async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  const session = makeLearningSession();
  session.row.title = scene.title;
  session.detail.messages[0].content = scene.question;
  session.detail.messages[1].content = scene.body;
  session.detail.messages[1].avatarRole = scene.role;
  session.detail.turns[0].user_message = scene.question;
  session.detail.turns[0].assistant_message = scene.body;
  const snapshot = researchFixture();
  snapshot.session_id = session.row.session_id; snapshot.turn_id = "turn-returning-1";
  snapshot.blocks[0].tier = "deep"; snapshot.blocks[0].research_status = "partial";
  snapshot.blocks[0].stop_reason = "evidence_saturated";
  snapshot.audit_status = "audited"; snapshot.audit_integrity = "valid"; snapshot.watch = false;
  await installApiFixture(page, { session });
  await seedWorkspaceRecovery(page, session.row.session_id);
  // Visual acceptance uses the real role portraits, not the gray test stub.
  await page.route("**/assets/avatars/*.png", route => {
    const name = new URL(route.request().url()).pathname.split("/").pop() ?? "";
    return route.fulfill({ path: `${AVATAR_DIR}/${name}` });
  });
  if (scene.withResearch) await page.route("**/research-presentation", route => route.fulfill({json: snapshot}));
  await page.goto("/");
  const answer = page.locator(".message.assistant .markdown-message").last();
  await expect(answer).toContainText("布局示意");

  // Real role portrait is rendered for the assistant message.
  const avatarImg = page.locator(".message.assistant > .avatar img").last();
  await expect(avatarImg).toHaveAttribute("src", `/assets/avatars/${scene.role}.png`);
  await expect(avatarImg).toBeVisible();
  // P1: on desktop the large portrait sits in the left gutter, never overlapping the answer text.
  if (!testInfo.project.name.includes("mobile")) {
    const avatarBox = (await avatarImg.boundingBox())!;
    const bodyBox = (await answer.boundingBox())!;
    expect(avatarBox.x + avatarBox.width).toBeLessThanOrEqual(bodyBox.x + 1);
  }

  // P0-2: the user message must never render as an empty bubble.
  await expect(page.locator(".message.user .message-bubble").last()).toContainText(scene.question);

  if (!scene.withResearch) {
    // P0-1: a plain teaching turn with no server research run shows no research status at all.
    await expect(page.locator(".research-status-row")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "研究资料", exact: true })).toHaveCount(0);
    expect(await noHorizontalOverflow(page)).toBe(true);
    await page.screenshot({path: `D:/study-agent-validation/reading-notebook-ui-evidence/conversation-${scene.id}-${testInfo.project.name}.png`});
    expect(errors).toEqual([]);
    return;
  }

  // P0-1: the research status lives *inside* the assistant message, not as a session banner.
  const row = page.locator(".message.assistant .research-status-row");
  await expect(row).toContainText("仍有待确认问题");
  await expect(page.locator(".conversation > .research-status-row")).toHaveCount(0);
  await expect(page.locator(".conversation-shell > .research-status-row")).toHaveCount(0);
  await expect(page.locator(".research-tier-list")).toHaveCount(0);
  // Long answers scroll; the research status stays bound to this message while scrolling.
  await page.locator(".conversation").evaluate(el => { el.scrollTop = el.scrollHeight; });
  await expect(page.locator(".message.assistant .research-status-row")).toContainText("仍有待确认问题");
  await page.locator(".conversation").evaluate(el => { el.scrollTop = 0; });
  const prose = await answer.innerText();
  const metrics = await answer.evaluate(element => ({size: parseFloat(getComputedStyle(element).fontSize), lineHeight: parseFloat(getComputedStyle(element).lineHeight), width: element.getBoundingClientRect().width}));
  expect(metrics.size).toBeGreaterThanOrEqual(15);
  expect(metrics.width).toBeLessThanOrEqual(820);
  expect(metrics.lineHeight / metrics.size).toBeCloseTo(1.7, 1);
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
  await expect(page.locator(".message.assistant .research-status-row")).toContainText("仍有待确认问题");
  await expect(page.locator(".research-tier-list")).toHaveCount(0);
  await page.screenshot({path: `D:/study-agent-validation/reading-notebook-ui-evidence/conversation-${scene.id}-${testInfo.project.name}-answer.png`, fullPage: true});
  expect(errors).toEqual([]);
});
