import { expect, test, type Page } from "@playwright/test";

const API_BASE = "http://127.0.0.1:8000";
const STORAGE_KEY = "study-agent-react-session";

const FIRST_QUESTION = "带我系统学习二分查找复杂度";
const FIRST_REPLY =
  "我们先建立目标：理解为什么二分查找是 O(log n)。请说明每一轮会怎样改变候选区间？";
const BARE_REPLY =
  "只说“懂了”还不足以确认掌握。请用因果关系解释候选区间怎样变化？";
const CORRECT_EXPLANATION =
  "所以二分查找每轮把候选范围减半，因此问题规模按一半递减，查找次数是对数级，因为只需重复减半直到剩一个元素。";
const CORRECT_REPLY =
  "这段解释已经通过理解验证；下一步把减半过程迁移到查找次数估算。";
const MATERIAL_FILE = "binary-search-boundaries.md";
const MATERIAL_HEADING = "二分查找边界条件";
const MATERIAL_SOURCE_TITLE = "binary-search-boundaries";
const MATERIAL_QUESTION =
  "请根据刚上传的资料，带我系统学习二分查找边界，并先完整讲解：目标值大于中点值时左边界如何更新？";
const MATERIAL_REPLY =
  "根据刚上传的资料，目标值大于中点值时，左边界更新为 mid + 1。请解释为什么不能仍把 mid 留在候选区间。";

type DurableState = {
  database_path: string;
  thread: {
    id: string;
    learning_state: {
      phase?: string;
      confirmed_points?: string[];
      payload?: Record<string, unknown>;
    };
  };
  turns: Array<{
    id: string;
    status: string;
    user_message: string;
    assistant_message: string;
    rag_snapshot?: Record<string, unknown>;
  }>;
  summary: {
    status?: string;
    closure_run_id?: string;
  };
};

type RagStatus = {
  index_path: string;
  index_exists: boolean;
  documents: number;
  chunks: number;
  index_version: number;
};

type KnowledgeDocuments = {
  index_path: string;
  index_exists: boolean;
  index_version: number;
  chunks: number;
  documents: Array<{
    document_id: string;
    revision_id: string;
    title: string;
    source_path: string;
    chunks: number;
    evidence_status: string;
  }>;
};

type ClosureList = {
  runs: Array<{
    id: string;
    thread_id: string;
    status: string;
    memory_run?: { status: string; preview: { writable: boolean } } | null;
    thread_summary?: { status?: string };
  }>;
};

type MemoryStatus = {
  writable: boolean;
  files: Array<{ name: string; exists: boolean; preview: string }>;
};

test.beforeEach(async ({ request }) => {
  const response = await request.post(`${API_BASE}/__e2e__/reset`);
  expect(response.ok()).toBe(true);
});

function assistantMessage(page: Page, text: string) {
  return page
    .getByRole("region", { name: "学习对话" })
    .locator("article.message.assistant")
    .filter({ hasText: text })
    .last()
    .getByText(text, { exact: true });
}

async function activeSessionId(page: Page): Promise<string> {
  await page.waitForFunction(
    ({ key }) => {
      const raw = window.localStorage.getItem(key);
      if (!raw) return false;
      try {
        const parsed = JSON.parse(raw) as {
          workspace?: { singleChatSessionId?: string; lastSessionId?: string };
        };
        return Boolean(
          parsed.workspace?.singleChatSessionId ?? parsed.workspace?.lastSessionId,
        );
      } catch {
        return false;
      }
    },
    { key: STORAGE_KEY },
  );
  return page.evaluate(({ key }) => {
    const parsed = JSON.parse(window.localStorage.getItem(key) ?? "{}") as {
      workspace?: { singleChatSessionId?: string; lastSessionId?: string };
    };
    const sessionId =
      parsed.workspace?.singleChatSessionId ?? parsed.workspace?.lastSessionId;
    if (!sessionId) throw new Error("Active session was not persisted");
    return sessionId;
  }, { key: STORAGE_KEY });
}

async function jsonFrom<T>(page: Page, path: string): Promise<T> {
  const response = await page.request.get(`${API_BASE}${path}`);
  expect(response.ok()).toBe(true);
  return (await response.json()) as T;
}

async function durableState(page: Page, sessionId: string): Promise<DurableState> {
  return jsonFrom<DurableState>(
    page,
    `/__e2e__/state/${encodeURIComponent(sessionId)}`,
  );
}

async function send(page: Page, text: string) {
  const composer = page.getByLabel("输入学习问题");
  await composer.fill(text);
  await composer.press("Enter");
}

async function openEvidence(page: Page) {
  const toggle = page.getByRole("button", { name: /证据轨迹/ }).last();
  await expect(toggle).toBeVisible();
  await toggle.click();
  return page.getByRole("region", { name: "回答采用的证据" });
}

async function completeReasonedLearning(page: Page): Promise<string> {
  await send(page, FIRST_QUESTION);
  await expect(assistantMessage(page, FIRST_REPLY)).toBeVisible();
  const sessionId = await activeSessionId(page);
  await send(page, CORRECT_EXPLANATION);
  await expect(assistantMessage(page, CORRECT_REPLY)).toBeVisible();
  return sessionId;
}

test("first learning turn crosses React, FastAPI and SQLite then restores", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "学习工作台" })).toBeVisible();

  await send(page, FIRST_QUESTION);
  await expect(assistantMessage(page, FIRST_REPLY)).toBeVisible();

  const sessionId = await activeSessionId(page);
  const stored = await durableState(page, sessionId);
  expect(stored.database_path).toContain("real-stack-runtime");
  expect(stored.thread.id).toBe(sessionId);
  expect(stored.turns).toHaveLength(1);
  expect(stored.turns[0]).toMatchObject({
    status: "completed",
    user_message: FIRST_QUESTION,
    assistant_message: FIRST_REPLY,
  });
  expect(stored.thread.learning_state.confirmed_points ?? []).toEqual([]);
  expect(stored.thread.learning_state.phase).not.toBe("answer");

  await page.reload();
  await expect(assistantMessage(page, FIRST_REPLY)).toBeVisible();
  await page.getByText("本会话学习上下文", {exact:true}).click();
  await expect(page.getByRole("region", { name: "继续当前任务" })).toBeVisible();

  const restored = await durableState(page, sessionId);
  expect(restored.turns).toEqual(stored.turns);
  expect(restored.thread.learning_state).toEqual(stored.thread.learning_state);
});

test("bare understanding is rejected before a reasoned claim commits", async ({
  page,
}) => {
  await page.goto("/");
  await send(page, FIRST_QUESTION);
  await expect(assistantMessage(page, FIRST_REPLY)).toBeVisible();

  const sessionId = await activeSessionId(page);
  await send(page, "懂了");
  await expect(assistantMessage(page, BARE_REPLY)).toBeVisible();

  const rejected = await durableState(page, sessionId);
  expect(rejected.turns).toHaveLength(2);
  expect(rejected.turns.at(-1)).toMatchObject({
    status: "completed",
    user_message: "懂了",
    assistant_message: BARE_REPLY,
  });
  expect(rejected.thread.learning_state.confirmed_points ?? []).toEqual([]);
  expect(rejected.thread.learning_state.phase).not.toBe("transfer");
  expect(rejected.thread.learning_state.payload?.pedagogy_evaluation).toMatchObject({
    final_decision: "reject",
    reasons: ["understanding_asserted_without_reasoning"],
  });

  await send(page, CORRECT_EXPLANATION);
  await expect(assistantMessage(page, CORRECT_REPLY)).toBeVisible();

  const accepted = await durableState(page, sessionId);
  expect(accepted.turns).toHaveLength(3);
  expect(accepted.turns.at(-1)).toMatchObject({
    status: "completed",
    user_message: CORRECT_EXPLANATION,
    assistant_message: CORRECT_REPLY,
  });
  expect(accepted.thread.learning_state.phase).toBe("transfer");
  expect(accepted.thread.learning_state.confirmed_points).toContain(
    CORRECT_EXPLANATION,
  );

  await page.reload();
  await expect(assistantMessage(page, CORRECT_REPLY)).toBeVisible();
  await page.getByText("本会话学习上下文", {exact:true}).click();
  const restoreCard = page.getByRole("region", { name: "继续当前任务" });
  await expect(restoreCard.getByText(CORRECT_EXPLANATION, { exact: true })).toBeVisible();

  const restored = await durableState(page, sessionId);
  expect(restored.thread.learning_state).toEqual(accepted.thread.learning_state);
  expect(restored.turns).toEqual(accepted.turns);
});

test("real Markdown upload activates an index and grounds restored learning", async ({
  page,
}) => {
  await page.goto("/");
  const chooserPromise = page.waitForEvent("filechooser");
  if (!(await page.getByLabel("上传学习资料").filter({visible:true}).isVisible())) await page.getByLabel("打开会话历史").click();
  await page.getByLabel("上传学习资料").filter({visible:true}).click();
  const chooser = await chooserPromise;
  await chooser.setFiles({
    name: MATERIAL_FILE,
    mimeType: "text/markdown",
    buffer: Buffer.from(
      [
        `# ${MATERIAL_HEADING}`,
        "",
        "二分查找用于升序数组，每轮比较中点并缩小候选区间。",
        "当目标值大于中点值时，左边界更新为 mid + 1。",
        "当目标值小于中点值时，右边界更新为 mid - 1。",
        "mid 已经比较过，因此不能继续留在下一轮候选区间。",
      ].join("\n"),
    ),
  });

  await expect(page.getByText("资料已准备好", { exact: true })).toBeVisible();
  await expect(page.getByText(/已索引 1 个文档、\d+ 个片段 · 索引版本 v1/)).toBeVisible();

  const status = await jsonFrom<RagStatus>(page, "/rag/status");
  expect(status.index_exists).toBe(true);
  expect(status.index_path).toContain("real-stack-runtime");
  expect(status.documents).toBe(1);
  expect(status.chunks).toBeGreaterThan(0);
  expect(status.index_version).toBe(1);

  const knowledge = await jsonFrom<KnowledgeDocuments>(
    page,
    "/knowledge-base/documents",
  );
  expect(knowledge.index_exists).toBe(true);
  expect(knowledge.documents).toHaveLength(1);
  expect(knowledge.documents[0]).toMatchObject({
    title: MATERIAL_SOURCE_TITLE,
    evidence_status: "active",
  });
  expect(knowledge.documents[0].revision_id).not.toBe("");

  await page.getByRole("button", { name: "开始系统学习" }).click();
  const composer = page.getByLabel("输入学习问题");
  await expect(composer).toHaveValue(/请基于刚上传的资料开始系统学习/);
  await send(page, MATERIAL_QUESTION);
  await expect(assistantMessage(page, MATERIAL_REPLY)).toBeVisible();

  const sessionId = await activeSessionId(page);
  const stored = await durableState(page, sessionId);
  const ragSnapshot = stored.turns.at(-1)?.rag_snapshot ?? {};
  expect(ragSnapshot).toMatchObject({
    status: "found",
    result_count: 1,
    evidence_snapshot: {
      disclosure_policy: "full",
      refs: [{ title: MATERIAL_SOURCE_TITLE, lifecycle_status: "selected" }],
    },
  });

  const adopted = await openEvidence(page);
  await expect(
    adopted.getByText(MATERIAL_SOURCE_TITLE, { exact: true }),
  ).toBeVisible();

  await page.reload();
  await expect(assistantMessage(page, MATERIAL_REPLY)).toBeVisible();
  const restoredAdopted = await openEvidence(page);
  await expect(
    restoredAdopted.getByText(MATERIAL_SOURCE_TITLE, { exact: true }),
  ).toBeVisible();

  const restored = await durableState(page, sessionId);
  expect(restored.turns).toEqual(stored.turns);
});

test("learning closure previews, hash-commits and restores before archive", async ({
  page,
}) => {
  await page.goto("/");
  const sessionId = await completeReasonedLearning(page);

  await page.getByRole("button", { name: "整理学习" }).click();
  const review = page.getByTestId("learning-closure-review");
  await expect(review.getByRole("heading", { name: "回顾这次学习" })).toBeVisible();
  await expect(review.getByText(CORRECT_EXPLANATION, { exact: true })).toBeVisible();
  await expect(
    review.getByText("继续当前会话时，可以自行决定下一步。", { exact: true }),
  ).toBeVisible();
  const previewDialog = page.getByRole("dialog", { name: "学习成果" });
  await previewDialog.getByText("高级写入明细", { exact: true }).click();
  const focusPreview = previewDialog
    .locator(".memory-preview-item")
    .filter({ hasText: "当前重点" });
  await expect(
    focusPreview.getByText("下一步练习二分查找边界迁移", { exact: true }),
  ).toBeVisible();

  const previewClosures = await jsonFrom<ClosureList>(
    page,
    "/learning-closure-runs",
  );
  expect(previewClosures.runs).toHaveLength(1);
  expect(previewClosures.runs[0]).toMatchObject({
    thread_id: sessionId,
    status: "preview_ready",
    memory_run: { status: "previewed", preview: { writable: true } },
  });

  await review.getByRole("button", { name: "确认并保存学习成果" }).click();
  await expect(page.getByText("本次已整理", { exact: true })).toBeVisible();

  const committed = await durableState(page, sessionId);
  expect(committed.summary).toMatchObject({
    status: "summarized",
    closure_run_id: previewClosures.runs[0].id,
  });
  const completedClosures = await jsonFrom<ClosureList>(
    page,
    "/learning-closure-runs",
  );
  expect(completedClosures.runs[0]).toMatchObject({
    status: "completed",
    memory_run: { status: "succeeded" },
    thread_summary: { status: "summarized" },
  });

  const memory = await jsonFrom<MemoryStatus>(page, "/memory");
  expect(memory.writable).toBe(true);
  expect(
    memory.files.find((file) => file.name === "current_focus.md"),
  ).toMatchObject({
    exists: true,
  });
  expect(
    memory.files.find((file) => file.name === "current_focus.md")?.preview,
  ).toContain("下一步练习二分查找边界迁移");
  expect(
    memory.files.find((file) => file.name === "progress.md")?.preview,
  ).toContain(CORRECT_EXPLANATION);

  await page.reload();
  await expect(assistantMessage(page, CORRECT_REPLY)).toBeVisible();
  if (!(await page.getByLabel("打开更多学习工具").filter({visible:true}).isVisible())) await page.getByLabel("打开会话历史").click();
  await page.getByLabel("打开更多学习工具").filter({visible:true}).click();
  await page.getByRole("menuitem", { name: /学习成果/ }).click();
  const resultsDialog = page.getByRole("dialog", { name: "学习成果" });
  await expect(resultsDialog.getByText("本次已整理", { exact: true })).toBeVisible();

  await resultsDialog.getByRole("button", { name: "归档并新建" }).click();
  await expect(resultsDialog).toBeHidden();
  const transitionDialog = page.getByRole("dialog", {
    name: "归档当前会话前确认未完成工作",
  });
  await expect(transitionDialog).toContainText("当前会话将进入历史记录");
  await transitionDialog.getByRole("button", { name: "仍然归档并新建" }).click();
  await expect(page.getByRole("region", { name: "开始新任务" })).toBeVisible();

  const sessionsResponse = await jsonFrom<{
    sessions: Array<{ session_id: string; kind: string }>;
  }>(page, "/sessions");
  expect(
    sessionsResponse.sessions.find((session) => session.session_id === sessionId),
  ).toMatchObject({ kind: "archived" });
});
