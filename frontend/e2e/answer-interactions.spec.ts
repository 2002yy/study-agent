import { expect, test } from "@playwright/test";
import { installApiFixture, makeLearningSession, seedWorkspaceRecovery } from "./api-fixture";
import { noHorizontalOverflow } from "./journey-metrics";

const block = (c: unknown) => "```study-ui\n" + JSON.stringify(c) + "\n```";
const plot = { type: "plot", title: "探索二次函数", fn: "quadratic", a: 1, b: 0 };
const tail = "\n\n改变系数后，观察曲线如何变化。\n\n" + block({ type: "chart", title: "教学样例数据", points: [{ label: "甲", value: -2 }, { label: "乙", value: 3 }] })
  + "\n\n" + block({ type: "actions", title: "接下来", items: [{ label: "给我练习", prompt: "请给我一道二次函数练习题" }] })
  + "\n\n" + block({ type: "image", title: "示例图片", src: "/assets/avatars/nahida.png", alt: "头像验收样例" });

test("useful text and an interactive curve arrive before completion and draft actions never send automatically", async ({ page }) => {
  const session = makeLearningSession();
  await installApiFixture(page, { session });
  await seedWorkspaceRecovery(page, session.row.session_id);
  await page.addInitScript(({ card, tail, sessionId }) => {
    const nativeFetch = window.fetch.bind(window);
    const qa = window as unknown as { advanceAnswer?: () => void; answerRequest?: Record<string, unknown> };
    window.fetch = async (input, init) => {
      const url = String(input instanceof Request ? input.url : input);
      if (!url.endsWith("/chat/stream") || init?.method !== "POST") return nativeFetch(input, init);
      qa.answerRequest = JSON.parse(String(init.body));
      const encoder = new TextEncoder();
      let resume: (() => void) | undefined;
      const wait = () => new Promise<void>(resolve => { resume = resolve; });
      qa.advanceAnswer = () => resume?.();
      const reply = "先用图观察 y = x²。\n\n```study-ui\n" + JSON.stringify(card) + "\n```" + tail;
      return new Response(new ReadableStream({ async start(controller) {
        const emit = (event: string, data: unknown) => controller.enqueue(encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`));
        emit("session", { session_id: sessionId, turn_id: "interactive-turn" });
        emit("route", { role: "nahida" });
        emit("token", { text: "先用图观察 y = x²。\n\n```study-ui\n" + JSON.stringify(card) });
        await wait();
        emit("token", { text: "\n```" });
        await wait();
        emit("token", { text: tail });
        emit("done", { session_id: sessionId, turn_id: "interactive-turn", reply });
        controller.close();
      } }), { headers: { "Content-Type": "text/event-stream" } });
    };
  }, { card: plot, tail, sessionId: session.row.session_id });
  await page.goto("/");
  await expect(page.getByText("我们已经确认每轮会缩小搜索区间。", { exact: true })).toBeVisible();
  const input = page.getByLabel("输入学习问题");
  await input.fill("用可调图解释二次函数");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.getByText("先用图观察 y = x²。", { exact: true })).toBeVisible();
  await expect(page.getByText("正在准备交互内容…")).toBeVisible();
  await expect(page.getByRole("slider")).toHaveCount(0);
  const envelope = await page.evaluate(() => (window as unknown as { answerRequest: { conversation_instruction: string } }).answerRequest.conversation_instruction);
  expect(JSON.parse(envelope.replace("__STUDY_AGENT_TURN_CONTEXT_V1__", "")).turn_context).toContain("study-ui");
  await page.evaluate(() => (window as unknown as { advanceAnswer: () => void }).advanceAnswer());
  const slider = page.getByRole("slider", { name: "探索二次函数 系数 a" });
  await expect(slider).toBeVisible();
  await expect(page.getByRole("button", { name: "停止", exact: true })).toBeVisible();
  await slider.fill("2");
  await page.evaluate(() => (window as unknown as { advanceAnswer: () => void }).advanceAnswer());
  await expect(page.getByRole("button", { name: "停止", exact: true })).toHaveCount(0);
  await expect(slider).toHaveValue("2");
  await page.getByRole("button", { name: "折线图", exact: true }).click();
  await expect(page.getByRole("img", { name: /教学样例数据，折线图/ })).toBeVisible();
  await input.fill("我的原有草稿");
  let sent = 0;
  page.on("request", req => { if (new URL(req.url()).pathname === "/chat/stream") sent++; });
  await page.getByRole("button", { name: "给我练习", exact: true }).click();
  await expect(input).toHaveValue("我的原有草稿\n\n请给我一道二次函数练习题");
  await expect(input).toBeFocused();
  expect(sent).toBe(0);
  if (page.viewportSize()!.width <= 900) await page.setViewportSize({ width: 320, height: 568 });
  expect(await noHorizontalOverflow(page)).toBe(true);
});

test("structured answers restore from saved text and maps load only on explicit request", async ({ page }) => {
  const session = makeLearningSession();
  const content = block({ type: "map", title: "地点验收样例", points: [{ label: "杭州", lat: 30.25, lon: 120.15 }, { label: "北京", lat: 39.9, lon: 116.4 }] });
  session.detail.messages[1].content = content;
  session.detail.turns[0].assistant_message = content;
  await installApiFixture(page, { session });
  await seedWorkspaceRecovery(page, session.row.session_id);
  await page.route(/https:\/\/www\.openstreetmap\.org\/export\/embed\.html\?/, r => r.fulfill({ contentType: "text/html; charset=utf-8", body: "<p>地图验收底图</p>" }));
  await page.goto("/");
  await expect(page.getByRole("region", { name: "地点验收样例" })).toBeVisible();
  await expect(page.locator(".answer-card iframe")).toHaveCount(0);
  await page.getByRole("button", { name: "北京", exact: true }).click();
  await page.getByRole("button", { name: "显示地图", exact: true }).click();
  await expect(page.getByTitle("北京 地图")).toHaveAttribute("src", /marker=39.9%2C116.4/);
  await page.getByTitle("北京 地图").scrollIntoViewIfNeeded();
  await expect(page.frameLocator('iframe[title="北京 地图"]').getByText("地图验收底图")).toBeVisible();
  await page.getByRole("button", { name: "收起地图", exact: true }).click();
  await expect(page.locator(".answer-card iframe")).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("region", { name: "地点验收样例" })).toBeVisible();
  expect(await noHorizontalOverflow(page)).toBe(true);
});
