import { createServer, type ServerResponse } from "node:http";
import { expect, test } from "@playwright/test";
import { installApiFixture } from "./api-fixture";

// Real incremental HTTP/SSE transport with scripted research facts. This is
// browser acceptance, not a provider-quality or live research qualification.
test("two supplements and one queued task stay in one continuous research conversation", async ({ page }, testInfo) => {
  let stream: ServerResponse | undefined;
  let streams = 0;
  let turnId = "";
  let operationId = "";
  const steering: Array<Record<string, unknown>> = [];
  const queue: Array<Record<string, unknown>> = [];
  const steeringState = (version: number) =>
    steering.map(entry => ({ id: entry.id, content: entry.content, status: version > 1 ? "executing" : "pending" }));
  const progress = (version: number, status = "running") => ({
    run_id: "run-live", status, stage: status === "running" ? "searching" : "completed",
    provider_status: "", stop_reason: "", error: "", query_attempt_count: version,
    selected_source_count: 1, version, steering_supported: true,
    approach: { status: "ready", summary: "我会先比较功能与 PSD 兼容性，再核对哪些操作能由 Agent 完成。", focus: [], origin: "model_plan", sequence: 1, mode: "deep" },
    steering: steeringState(version),
    narration: [{ block_id: "run-live:search:1", text: "已开始检索候选资料，接下来读取正文。" },
      ...steering.map((entry, index) => ({ block_id: `run-live:steer:${index + 1}`, text: `已纳入补充：${entry.content}` }))],
  });
  const emit = (event: string, data: unknown) => stream?.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
  const server = createServer(async (request, response) => {
    response.setHeader("Access-Control-Allow-Origin", "*");
    response.setHeader("Access-Control-Allow-Headers", "Content-Type, X-Study-Agent-Token");
    if (request.method === "OPTIONS") { response.end(); return; }
    let body = "";
    for await (const chunk of request) body += chunk;
    const input = body ? JSON.parse(body) : {};
    if (request.url === "/chat/stream") {
      streams += 1;
      turnId = input.turn_id;
      operationId = input.operation_id;
      stream = response;
      response.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache" });
      emit("session", { session_id: "chat-live", turn_id: turnId, operation_id: operationId });
      emit("route", { role: "nahida", mode: "normal" });
      emit("research", progress(1));
      return;
    }
    if (request.url?.endsWith("/steer")) {
      steering.push({ id: `s${steering.length + 1}`, request_id: input.request_id, content: input.content, incorporated_in_round: null });
      response.setHeader("Content-Type", "application/json");
      response.end(JSON.stringify({ id: "run-live", research_context: { deep: { steering } } }));
      emit("research", progress(steering.length + 1));
      emit("token", { text: "研究继续进行，正在核对新增的维度。" });
      return;
    }
    if (request.url?.endsWith("/queue")) queue.push({ id: input.request_id, content: input.content, status: "pending" });
    response.setHeader("Content-Type", "application/json");
    response.end(JSON.stringify({ id: "run-live", query: "compare", status: "running", stage: "searching", version: 1,
      research_context: { research_mode: "deep", deep: { steering }, conversation_queue: queue },
      query_attempts: [], selected_sources: [], rejected_sources: [], items: [], source_block: "", warnings: [], error: "" }));
  });
  await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("Test server did not bind");
  try {
    await installApiFixture(page);
    await page.route(/\/(?:chat\/stream|research-runs\/run-live(?:\/(?:steer|queue))?)$/, route =>
      route.continue({ url: `http://127.0.0.1:${address.port}${new URL(route.request().url()).pathname}` }));
    await page.goto("/");
    const input = page.getByRole("textbox", { name: "输入学习问题" });
    await input.fill("比较 Photoshop 和开源替代品，重点考虑自动化编辑");
    await input.press("Enter");
    // The research plan opening lives in the conversation, not a floating bar.
    await expect(page.getByText("我会先比较功能与 PSD 兼容性，再核对哪些操作能由 Agent 完成。")).toBeVisible();
    // No duplicated global status surface while the run is live.
    await expect(page.getByText(/已发起 \d+ 次查询/)).toHaveCount(0);
    await page.screenshot({ path: testInfo.outputPath("research-opening.png"), fullPage: true });

    // Supplement 1: adjust the current research.
    await input.fill("再考虑 Agent 自动编辑");
    await page.getByRole("button", { name: "追加要求", exact: true }).click();
    await expect(page.getByText("研究继续进行，正在核对新增的维度。")).toBeVisible();
    await expect(page.getByText("正在按补充要求执行研究")).toBeVisible();
    await expect(page.getByRole("button", { name: "停止", exact: true })).toBeVisible();

    // Supplement 2: still steers the same single HTTP stream.
    await input.fill("并补查脚本接口与图层控制");
    await page.getByRole("button", { name: "追加要求", exact: true }).click();
    await expect(page.getByText("正在按补充要求执行研究")).toHaveCount(2);

    // Queued task: a separate timeline card that never changes the search.
    await page.getByRole("button", { name: "完成后再做", exact: true }).click();
    await input.fill("回答完再解释得简单一点");
    await page.getByRole("button", { name: "加入下一轮", exact: true }).click();
    await expect(page.getByText("下一轮任务")).toBeVisible();
    await expect(page.getByText("不会修改当前研究的搜索条件。")).toBeVisible();

    expect(streams).toBe(1);
    expect(queue).toHaveLength(1);
    expect(steering.map(entry => entry.content)).toEqual(["再考虑 Agent 自动编辑", "并补查脚本接口与图层控制"]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath("continuous-research.png"), fullPage: true });

    emit("research", { ...progress(3, "completed"), steering: steering.map(entry => ({ id: entry.id, content: entry.content, status: "applied" })) });
    emit("done", { session_id: "chat-live", turn_id: turnId, reply: "已保留已有资料，并完成新增维度的补查。" });
    stream?.end();
    await expect(page.getByRole("button", { name: "发送排队问题", exact: true })).toBeVisible();
    await expect(page.getByText("研究过程已结束")).toBeVisible();
    // The search process is collapsed by default and only expands on request.
    const process = page.getByText("查看搜索过程与失败原因");
    await expect(process).toBeVisible();
    await process.click();
    await expect(page.getByText("已纳入补充：再考虑 Agent 自动编辑")).toBeVisible();
  } finally {
    stream?.end();
    server.closeAllConnections();
    await new Promise<void>(resolve => server.close(() => resolve()));
  }
});
