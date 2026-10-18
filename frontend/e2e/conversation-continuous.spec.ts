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
  const supplementRequests: Array<Record<string, unknown>> = [];
  const queue: Array<Record<string, unknown>> = [];
  const queueRequests: Array<Record<string, unknown>> = [];
  const chatRequests: Array<Record<string, unknown>> = [];
  // A supplement receipt carries what it actually changed: the check the server
  // created for it, named by the supplement's own target rather than by a
  // restatement of the original question. Sources stay out of this fixture
  // because no read is attributed to these questions yet.
  const steeringState = (version: number) =>
    steering.map(entry => ({
      id: entry.id, content: entry.content,
      status: version > 1 ? "executing" : "pending",
      ...(version > 1
        ? { effects: { questions: [{ text: String(entry.content), created: true }], sources: [] } }
        : {}),
    }));
  const progress = (version: number, status = "running") => ({
    run_id: "run-live", status, stage: status === "running" ? "searching" : "completed",
    provider_status: "", stop_reason: "", error: "", query_attempt_count: version,
    selected_source_count: 1, version, steering_supported: true,
    read_count: version >= 3 ? 2 : 1,
    findings: [
      { id: "run-live:excerpt:1", kind: "source_excerpt", title: "已读来源：自动化接口", url: "https://example.org/automation", text: "该工具的脚本接口支持批量重命名图层、导出 PNG，并保留 PSD 图层样式。", question: "Photoshop 自动化接口" },
      ...(version >= 3 ? [{ id: "run-live:excerpt:2", kind: "source_excerpt", title: "开源工具文档", url: "https://example.org/open-tool", text: "该开源工具的脚本接口支持批量处理图层和导出 PNG，但不支持部分 PSD 图层样式。", question: "开源替代品的兼容范围" }] : []),
    ],
    reading_gaps: version >= 3 ? [] : ["开源替代品的兼容范围"],
    interim_analysis: version >= 4 ? {
      status: "provisional",
      text: "批量处理图层、导出 PNG，两种方案都能接入 Agent 脚本。\n\n需要保留 PSD 图层样式时，优先原工具：开源方案仍有部分样式不兼容。",
      citations: [
        { url: "https://example.org/automation", title: "自动化接口文档", quote: "该工具的脚本接口支持批量重命名图层、导出 PNG，并保留 PSD 图层样式。" },
        { url: "https://example.org/open-tool", title: "开源工具文档", quote: "该开源工具的脚本接口支持批量处理图层和导出 PNG，但不支持部分 PSD 图层样式。" },
      ],
    } : null,
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
      chatRequests.push(input);
      if (streams > 1) {
        response.writeHead(200, { "Content-Type": "text/event-stream" });
        response.write(`event: computation\ndata: ${JSON.stringify({
        schema_version: "1", run_id: "run-live", tool_run_id: "tool-1", status: "succeeded",
        input_revision: 1, source_refs: ["source-1"], engine: "deterministic",
        result: { columns: ["方案", "耗时"], rows: [["A", 12.5], ["B", 9.8]], unit: "seconds" },
        })}\n\n`);
        response.end(`event: done\ndata: ${JSON.stringify({ session_id: "chat-live", turn_id: input.turn_id, reply: "按给定示例，B 比 A 少用 2.7 秒。" })}\n\n`);
        return;
      }
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
      supplementRequests.push(input);
      if (supplementRequests.length === 1) {
        response.writeHead(503, { "Content-Type": "application/json" });
        response.end(JSON.stringify({ detail: "temporary supplement failure" }));
        return;
      }
      steering.push({ id: `s${steering.length + 1}`, request_id: input.request_id, content: input.content, incorporated_in_round: null });
      response.setHeader("Content-Type", "application/json");
      response.end(JSON.stringify({ id: "run-live", research_context: { deep: { steering } } }));
      emit("research", progress(steering.length + 1));
      return;
    }
    if (request.url?.endsWith("/queue")) {
      queueRequests.push(input);
      if (queueRequests.length === 1) {
        response.writeHead(503, { "Content-Type": "application/json" });
        response.end(JSON.stringify({ detail: "temporary queue failure" }));
        return;
      }
      queue.push({ id: input.request_id, content: input.content, status: "pending", attachment_refs: input.attachment_ids.map((id: string) => ({ attachment_id: id })) });
    }
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
    const attachment = {
      id: "att1", thread_id: "chat-live", filename: "notes.txt", content_hash: "h",
      mime_type: "text/plain", size_bytes: 8, status: "ready", stage_error: "",
      stage_history: [], retry_count: 0, promoted_rag_run_id: "", external_calls: [],
      created_at: "", updated_at: "",
    };
    let attached = false;
    await page.route(/\/sessions\/[^/]+\/attachments$/, route => {
      if (route.request().method() === "POST") {
        attached = true;
        return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(attachment) });
      }
      return route.fulfill({
        status: 200, contentType: "application/json",
        body: JSON.stringify({ attachments: attached ? [attachment] : [], max_files_per_thread: 5, total_bytes: 8 }),
      });
    });
    let firstChatBody: Record<string, unknown> | null = null;
    await page.route(/\/(?:chat\/stream|research-runs\/run-live(?:\/(?:steer|queue(?:\/[^/]+\/complete)?))?)$/, route => {
      firstChatBody ??= route.request().postDataJSON() as Record<string, unknown>;
      return route.continue({ url: `http://127.0.0.1:${address.port}${new URL(route.request().url()).pathname}` });
    });
    await page.route(/\/chat\/turns\/turn_queue_[^/]+\/status$/, route => route.fulfill({
      status: 404, contentType: "application/json", body: JSON.stringify({ detail: "not found" }),
    }));
    await page.goto("/");
    const input = page.getByRole("textbox", { name: "输入学习问题" });
    // Slice C/D: a first multimodal question attaches before any empty send;
    // the composer creates the session on demand.
    await page.locator('.composer-attachments input[type="file"]').setInputFiles(
      { name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from("evidence") },
    );
    await expect(page.locator(".composer-attachment-chips").getByText("notes.txt")).toBeVisible();
    await expect(page.getByRole("button", { name: "取消选择附件 notes.txt", exact: true })).toHaveAttribute("aria-pressed", "true");

    await input.fill("比较 Photoshop 和开源替代品，重点考虑自动化编辑");
    await input.press("Enter");
    // The research plan opening lives in the conversation, not a floating bar.
    await expect(page.getByText("我会先比较功能与 PSD 兼容性，再核对哪些操作能由 Agent 完成。")).toBeVisible();
    // Only this message's selection travels with the request...
    expect(firstChatBody?.attachment_ids).toEqual(["att1"]);
    // ...and it is cleared once the message was sent.
    await expect(page.getByText("本次选中 1 个")).toHaveCount(0);
    // No duplicated global status surface while the run is live.
    await expect(page.getByText(/已发起 \d+ 次查询/)).toHaveCount(0);
    const portrait = page.locator('.message.assistant > .avatar img').first();
    await expect(portrait).toBeVisible();
    await expect.poll(() => portrait.evaluate(image => (image as HTMLImageElement).naturalWidth)).toBe(512);
    const avatarBox = await page.locator('.message.assistant > .avatar').first().boundingBox();
    expect(avatarBox?.width).toBe(page.viewportSize()!.width > 900 ? 96 : 80);
    const composerBox = await page.locator('.composer-main').boundingBox();
    expect(composerBox?.height).toBeLessThan(170);
    const filename = page.locator('.composer-attachment-name').first();
    const filenameBox = await filename.boundingBox();
    expect(filenameBox?.width).toBeGreaterThan(40);
    await page.getByRole("textbox", { name: "输入学习问题" }).focus();
    await page.keyboard.press("Tab");
    await expect(page.getByRole("button", { name: "添加附件", exact: true })).toBeFocused();
    await page.getByRole("textbox", { name: "输入学习问题" }).focus();
    await page.screenshot({ path: testInfo.outputPath("research-opening.png"), fullPage: true });
    // The first read-backed content is visible before any answer token or done.
    await expect(page.getByRole("region", { name: "已读资料摘录" })).toBeVisible();
    await expect(page.getByText("Photoshop 自动化接口", { exact: true })).toBeVisible();
    await expect(page.getByText("暂无正文：开源替代品的兼容范围", { exact: true })).toBeVisible();
    await expect(page.getByText("该工具的脚本接口支持批量重命名图层、导出 PNG，并保留 PSD 图层样式。", { exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "已读来源：自动化接口" })).toHaveAttribute("href", "https://example.org/automation");
    await expect(page.getByRole("button", { name: "停止", exact: true })).toBeVisible();
    await expect(page.getByText("已保留已有资料，并完成新增维度的补查。", { exact: true })).toHaveCount(0);

    // Supplement 1: adjust the current research.
    await page.getByRole("button", { name: "选择附件 notes.txt", exact: true }).click();
    await input.fill("再考虑 Agent 自动编辑");
    await page.getByRole("button", { name: "追加要求", exact: true }).click();
    await expect(page.getByRole("alert").getByText("操作没有完成", { exact: true })).toBeVisible();
    await expect(input).toHaveValue("再考虑 Agent 自动编辑");
    await expect(page.getByRole("button", { name: "取消选择附件 notes.txt", exact: true })).toHaveAttribute("aria-pressed", "true");
    await page.getByRole("button", { name: "追加要求", exact: true }).click();
    expect(supplementRequests[0].attachment_ids).toEqual(["att1"]);
    expect(supplementRequests[1]).toEqual(supplementRequests[0]);
    await expect(page.getByRole("button", { name: "选择附件 notes.txt", exact: true })).toHaveAttribute("aria-pressed", "false");
    await expect(page.getByText("正在按补充要求执行研究")).toBeVisible();
    // The supplement shows the check it created instead of leaving a blank, and
    // the check is named by the supplement itself, not by the original question.
    await expect(page.getByText("新增核查：再考虑 Agent 自动编辑")).toBeVisible();
    await expect(page.getByRole("button", { name: "停止", exact: true })).toBeVisible();

    // Supplement 2: still steers the same single HTTP stream.
    await input.fill("并补查脚本接口与图层控制");
    await page.getByRole("button", { name: "追加要求", exact: true }).click();
    await expect(page.getByText("正在按补充要求执行研究")).toHaveCount(2);
    await expect(page.getByText(/^新增核查：/)).toHaveCount(2);
    await expect(page.getByText("新增核查：并补查脚本接口与图层控制")).toBeVisible();
    await expect(page.getByText("开源替代品的兼容范围", { exact: true })).toBeVisible();
    await expect(page.getByText("暂无正文：开源替代品的兼容范围", { exact: true })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "已读来源：自动化接口" })).toHaveCount(1);
    expect(supplementRequests[2].attachment_ids).toEqual([]);

    // Queued task: a separate timeline card that never changes the search.
    await page.getByRole("combobox", { name: "追加方式" }).selectOption("queue");
    await page.getByRole("button", { name: "选择附件 notes.txt", exact: true }).click();
    await input.fill("示例 A 耗时12.5秒、B耗时9.8秒，计算差异并列表");
    await page.getByRole("button", { name: "加入下一轮", exact: true }).click();
    await expect(page.getByRole("alert").getByText("操作没有完成", { exact: true })).toBeVisible();
    await expect(input).toHaveValue("示例 A 耗时12.5秒、B耗时9.8秒，计算差异并列表");
    await expect(page.getByRole("button", { name: "取消选择附件 notes.txt", exact: true })).toHaveAttribute("aria-pressed", "true");
    await page.getByRole("button", { name: "加入下一轮", exact: true }).click();
    await expect(page.getByText("下一轮任务")).toBeVisible();
    await expect(page.getByText("附带 1 个附件，将用于这条问题。", { exact: true })).toBeVisible();
    expect(queueRequests[0].attachment_ids).toEqual(["att1"]);
    expect(queueRequests[1]).toEqual(queueRequests[0]);
    await expect(page.getByRole("button", { name: "选择附件 notes.txt", exact: true })).toHaveAttribute("aria-pressed", "false");
    // A queued task needs a manual send; the card must not imply auto-continue.
    await expect(page.getByText("已保存，待发送")).toBeVisible();
    await expect(page.getByText("不会修改当前研究的搜索条件；研究完成后需手动发送。")).toBeVisible();

    expect(streams).toBe(1);
    expect(queue).toHaveLength(1);
    expect(steering.map(entry => entry.content)).toEqual(["再考虑 Agent 自动编辑", "并补查脚本接口与图层控制"]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath("continuous-research.png"), fullPage: true });

    // A model synthesis becomes readable before done; raw excerpts give way
    // to a quieter analysis with quotes available on request.
    emit("research", progress(4));
    await expect(page.getByRole("region", { name: "阶段性分析", exact: true })).toBeVisible();
    await expect(page.getByText("批量处理图层、导出 PNG，两种方案都能接入 Agent 脚本。", { exact: true })).toBeVisible();
    await expect(page.getByText("需要保留 PSD 图层样式时，优先原工具：开源方案仍有部分样式不兼容。", { exact: true })).toBeVisible();
    await expect(page.locator(".answer-progress-approach, .research-status-line")).toHaveCount(0);
    await expect(page.getByRole("figure", { name: "计算结果" })).toHaveCount(0);
    await expect(page.getByRole("region", { name: "已读资料摘录", exact: true })).toHaveCount(0);
    await page.getByText("来源与研究过程（2）", { exact: true }).click();
    await expect(page.getByRole("link", { name: "自动化接口文档", exact: true })).toHaveAttribute("href", "https://example.org/automation");
    await expect(page.getByText("该开源工具的脚本接口支持批量处理图层和导出 PNG，但不支持部分 PSD 图层样式。", { exact: true })).toBeVisible();
    await page.getByText("来源与研究过程（2）", { exact: true }).click();
    await page.getByRole("region", { name: "学习对话", exact: true }).evaluate(element => { element.scrollTop = 0; });
    await page.screenshot({ path: testInfo.outputPath("interim-analysis.png"), fullPage: true });

    emit("research", { ...progress(5, "completed"), steering: steering.map(entry => ({ id: entry.id, content: entry.content, status: "applied" })) });
    emit("done", { session_id: "chat-live", turn_id: turnId, reply: "已保留已有资料，并完成新增维度的补查。" });
    stream?.end();
    await expect(page.getByRole("button", { name: "发送排队问题", exact: true })).toBeVisible();
    // The search process is collapsed by default and only expands on request.
    const process = page.getByText("来源与研究过程（2）");
    await expect(process).toBeVisible();
    await process.click();
    await expect(page.getByText(/研究过程已结束 · 阶段性判断/)).toBeVisible();
    await expect(page.getByText("已纳入补充：再考虑 Agent 自动编辑")).toBeVisible();
    await page.getByRole("button", { name: "发送排队问题", exact: true }).click();
    await expect(page.getByText("按给定示例，B 比 A 少用 2.7 秒。", { exact: true })).toBeVisible();
    // Slice B: the bound computation renders in the same conversation, with
    // unit/source/version provenance, and is switchable to a data table.
    await expect(page.getByRole("figure", { name: "计算结果" })).toBeVisible();
    await expect(page.getByText(/确定性计算 · 版本 v1/)).toBeVisible();
    await page.getByRole("button", { name: "数据表" }).click();
    await expect(page.getByRole("cell", { name: "12.5" })).toBeVisible();

    expect(chatRequests[1].attachment_ids).toEqual(["att1"]);
    expect(chatRequests[1].turn_id).toBe(`turn_${queueRequests[1].request_id}`);
  } finally {
    stream?.end();
    server.closeAllConnections();
    await new Promise<void>(resolve => server.close(() => resolve()));
  }
});
