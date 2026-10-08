import type { Page, Route } from "@playwright/test";

export const FIRST_QUESTION = "什么是二分查找？";
export const FIRST_REPLY = "二分查找会在有序序列中反复把候选范围缩小一半。";
export const CONTINUE_REPLY = "继续学习：请用自己的话解释左右边界为什么会变化。";
export const RETRY_REPLY = "请求已恢复。二分查找每轮排除一半候选范围。";

const STORAGE_KEY = "study-agent-react-session";
const EXTERNAL_DATA_NOTICE_KEY = "study-agent:external-data-notice:v1";
const EMPTY_RAG = {
  status: "waiting",
  query: "",
  retrieval_mode: "hybrid",
  reason: "",
  context: "",
  sources: "",
  result_count: 0,
  results: [],
  debug: {},
  attempts: [],
  rewritten_query: "",
};

function ragWithExternalDataPolicy() {
  return {
    ...EMPTY_RAG,
    external_data_policy: {
      web_policy: "off",
      cloud_context_policy: "allow_local_evidence",
      task_source_policy: "model_only",
      web_allowed: false,
      local_retrieval_allowed: false,
      history_allowed: true,
      memory_allowed: true,
      local_evidence_to_model_allowed: true,
      reason: "task_does_not_allow_web",
      web_search_performed: false,
      history_sent_to_model: false,
      history_message_count: 0,
      learning_state_sent_to_model: true,
      memory_context_sent_to_model: false,
      local_evidence_sent_to_model: false,
      local_evidence_chunk_count: 0,
    },
  };
}

const RUNTIME_SETTINGS = {
  settings: {
    selected_role: "auto",
    selected_mode: "auto",
    selected_model: "auto",
    relationship_mode: "standard",
    entry_mode: "single",
    performance_mode: "fast",
    memory_mode: "manual",
    debug_mode: false,
    safe_mode: true,
    route_mode: "auto",
    context_mode: "light",
    current_version: "browser-audit",
    active_task: "",
    next_version: "",
    wechat_memory_capture_enabled: false,
    wechat_memory_capture_mode: "off",
    rag_enabled: true,
    rag_retrieval_mode: "hybrid",
    rag_search_top_k: 5,
    rag_chat_top_k: 3,
    rag_top_k: 5,
    rag_min_score: 0.01,
    web_policy: "off",
    cloud_context_policy: "allow_local_evidence",
  },
  options: {
    roles: [{ id: "auto", label: "自动" }],
    modes: [{ id: "auto", label: "自动" }],
    models: [{ id: "auto", label: "自动" }],
    performance_modes: [{ id: "fast", label: "快速" }],
    relationship_modes: [{ id: "standard", label: "标准" }],
    entry_modes: [{ id: "single", label: "单人" }],
    memory_modes: ["manual"],
    retrieval_modes: ["hybrid"],
    web_policies: ["off"],
    cloud_context_policies: ["allow_local_evidence"],
  },
  runtime_profile: {},
  warnings: [],
};

export type SessionRow = {
  session_id: string;
  kind: string;
  name: string;
  path: string;
  size_bytes: number;
  mtime_ns: number;
  title: string;
  task_intent: string;
  objective: string;
  confirmed_points: string[];
  unresolved_gap: string;
  next_action: string;
  has_completed_turns: boolean;
};

export type SessionDetail = {
  session_id: string;
  kind: string;
  path: string;
  messages: Array<Record<string, unknown>>;
  turns: Array<Record<string, unknown>>;
  settings: Record<string, unknown>;
  route: Record<string, unknown>;
  rag: Record<string, unknown>;
  learning_state: Record<string, unknown>;
  pedagogy: Record<string, unknown>;
  latest_attempted_pedagogy: Record<string, unknown>;
  navigation: Record<string, unknown>;
  conversation_instruction: string;
};

export type ApiFixtureState = {
  sessions: SessionRow[];
  details: Map<string, SessionDetail>;
  closureRuns: Map<string, Record<string, unknown>>;
  learningResume: Map<string, Record<string, unknown>>;
  failNextChat: boolean;
  chatAttempts: number;
  unexpectedApiPaths: string[];
};

export function makeLearningSession(): { row: SessionRow; detail: SessionDetail } {
  const learningState = {
    protocol: "socratic",
    objective: "理解二分查找边界条件",
    phase: "verify",
    confirmed_points: ["每轮缩小搜索区间"],
    unresolved_gap: "左右边界更新时机",
    hint_level: 0,
    turn_count: 3,
    payload: { next_action: "完成一次边界迁移练习" },
  };
  const row: SessionRow = {
    session_id: "returning-learning-session",
    kind: "current",
    name: "returning-learning-session.md",
    path: "",
    size_bytes: 0,
    mtime_ns: 1,
    title: "二分查找",
    task_intent: "learn",
    objective: learningState.objective,
    confirmed_points: learningState.confirmed_points,
    unresolved_gap: learningState.unresolved_gap,
    next_action: "完成一次边界迁移练习",
    has_completed_turns: true,
  };
  const route = {
    role: "nahida",
    mode: "苏格拉底",
    model_profile: "flash",
    task_contract: {
      task_intent: "learn",
      source_policy: "model_only",
      closure_eligibility: "learning_summary",
      learning_state_enabled: true,
    },
    learning_state: learningState,
  };
  return {
    row,
    detail: {
      session_id: row.session_id,
      kind: row.kind,
      path: "",
      messages: [
        {
          role: "user",
          content: "我想学习二分查找边界条件",
          turnId: "turn-returning-1",
          turnStatus: "completed",
        },
        {
          role: "assistant",
          content: "我们已经确认每轮会缩小搜索区间。",
          avatarRole: "nahida",
          turnId: "turn-returning-1",
          turnStatus: "completed",
        },
      ],
      turns: [
        {
          turn_id: "turn-returning-1",
          status: "completed",
          user_message: "我想学习二分查找边界条件",
          assistant_message: "我们已经确认每轮会缩小搜索区间。",
          parent_turn_id: null,
          route_snapshot: route,
          rag_snapshot: ragWithExternalDataPolicy(),
          pedagogy_snapshot: {
            phase: "verify",
            committed_learning_state: learningState,
          },
        },
      ],
      settings: defaultSessionSettings("苏格拉底"),
      route,
      rag: ragWithExternalDataPolicy(),
      learning_state: learningState,
      pedagogy: {
        phase: "verify",
        committed_learning_state: learningState,
      },
      latest_attempted_pedagogy: {},
      navigation: {
        phase: "verify",
        objective: learningState.objective,
        confirmed_points: learningState.confirmed_points,
        unresolved_gap: learningState.unresolved_gap,
        next_action: row.next_action,
      },
      conversation_instruction: "",
    },
  };
}

export function makeStaleLearningResume(): Record<string, unknown> {
  const now = new Date().toISOString();
  const currentFreshness = (headCommit: string) => ({
    status: "current",
    head_commit: headCommit,
    reason: "head matches verified commit",
  });
  return {
    source: "durable",
    status: "active",
    topic: {
      topic_id: "topic-binary-search",
      title: "二分查找",
      scope: "边界条件",
    },
    goal: {
      goal_id: "goal-boundary",
      topic_id: "topic-binary-search",
      objective: "理解二分查找边界条件",
      status: "active",
    },
    claims: [
      {
        claim_id: "claim-loop-shrink",
        revision_id: "rev-1",
        text: "每轮循环会缩小搜索区间",
        claim_kind: "understanding",
        scope: "core",
        understanding_status: "confirmed",
        validation_result: "pass",
        latest_validation: {
          method: "socratic_check",
          result: "pass",
          verified_at: now,
        },
        primary_evidence: {
          path: "src/algorithms/binary_search.py",
          kind: "code",
          head_file_sha: "sha-loop-shrink",
        },
        supporting_evidence: [],
        freshness: currentFreshness("commit-loop-shrink"),
      },
      {
        claim_id: "claim-boundary-update",
        revision_id: "rev-2",
        text: "左右边界更新时机取决于中位数的取法",
        claim_kind: "understanding",
        scope: "core",
        understanding_status: "confirmed",
        validation_result: "pass",
        latest_validation: {
          method: "socratic_check",
          result: "pass",
          verified_at: now,
        },
        primary_evidence: {
          path: "src/algorithms/binary_search.py",
          kind: "code",
          head_file_sha: "sha-boundary-new",
        },
        supporting_evidence: [],
        freshness: {
          status: "stale_candidate",
          head_commit: "commit-boundary-old",
          reason: "primary evidence file changed after verified commit",
          primary: {
            path: "src/algorithms/binary_search.py",
            kind: "code",
            status: "suspicious",
            head_file_sha: "sha-boundary-new",
            materially_changed: true,
          },
          supporting_drift: [],
        },
      },
    ],
    claim_count: 2,
    unresolved: [
      {
        hypothesis_id: "hyp-boundary",
        text: "左右边界更新时机",
        reason: "仍待解释",
      },
    ],
    next_step: {
      next_step_id: "step-boundary-practice",
      text: "完成一次边界迁移练习",
      status: "pending",
      is_primary: true,
    },
    optional_next_steps: [],
    legacy_confirmed_points: [],
  };
}

function defaultSessionSettings(selectedMode = "auto") {
  return {
    selectedRole: "auto",
    selectedMode,
    selectedModel: "auto",
    relationshipMode: "standard",
    contextMode: "light",
    ragEnabled: true,
    ragSettings: {
      retrievalMode: "hybrid",
      topK: 5,
      chatTopK: 3,
      minScore: 0.01,
    },
    keepCurrentRole: false,
  };
}

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

function replyFor(question: string, retry: boolean) {
  if (retry) return RETRY_REPLY;
  if (question.includes("继续当前任务")) return CONTINUE_REPLY;
  return FIRST_REPLY;
}

function taskIntentFor(question: string, current?: SessionRow) {
  if (current?.task_intent === "learn" || question.includes("继续当前任务")) {
    return "learn";
  }
  return "quick_answer";
}

function closureResponse(
  sessionId: string,
  status: "preview_ready" | "completed",
): Record<string, unknown> {
  const runId = `closure-${sessionId}`;
  const completed = status === "completed";
  const updates = [
    {
      target: "progress",
      content: "已确认：每轮会缩小搜索区间",
      append: true,
      learner_pending: false,
    },
    {
      target: "revision_notes",
      content: "还需解释左右边界更新时机",
      append: true,
      learner_pending: true,
    },
    {
      target: "current_focus",
      content: "下一步完成一次边界迁移练习",
      append: false,
      learner_pending: false,
    },
  ];
  const now = new Date().toISOString();
  return {
    id: runId,
    thread_id: sessionId,
    source_thread_version: 2,
    last_completed_turn_id: "turn-returning-1",
    source_hash: "browser-closure-source",
    closure_eligibility: "learning_summary",
    status,
    committed_snapshot: {},
    generated_result: { candidates: updates },
    memory_run_id: `memory-${sessionId}`,
    memory_run: {
      id: `memory-${sessionId}`,
      status: completed ? "succeeded" : "previewed",
      updates,
      updates_hash: "browser-memory-updates",
      preview: {
        writable: true,
        memory_mode: "confirm_write",
        safe_mode: false,
        updates: updates.map((update) => ({
          target: update.target,
          path: `${update.target}.md`,
          action: update.append ? "append" : "replace",
          allowed: true,
          preview: update.content,
        })),
      },
      result: completed
        ? {
            results: updates.map((update) => ({
              target: update.target,
              action: update.append ? "append" : "replace",
              path: `${update.target}.md`,
            })),
            errors: [],
          }
        : {},
      reason: "",
      version: completed ? 2 : 1,
      created_at: now,
      updated_at: now,
      completed_at: completed ? now : null,
    },
    thread_summary: {
      thread_id: sessionId,
      status: completed ? "summarized" : "not_summarized",
      source_thread_version: completed ? 2 : null,
      last_completed_turn_id: completed ? "turn-returning-1" : null,
      current_last_completed_turn_id: "turn-returning-1",
      closure_run_id: completed ? runId : null,
      summarized_at: completed ? now : null,
      can_summarize: !completed,
    },
    error: "",
    reason: "",
    active_operation_id: null,
    active_operation_started_at: null,
    cancel_requested_at: null,
    created_at: now,
    updated_at: now,
    completed_at: completed ? now : null,
    version: completed ? 2 : 1,
  };
}

export async function installApiFixture(
  page: Page,
  options: {
    session?: { row: SessionRow; detail: SessionDetail };
    learningResume?: Record<string, unknown>;
    failNextChat?: boolean;
  } = {},
): Promise<ApiFixtureState> {
  await page.addInitScript((noticeKey) => {
    window.localStorage.setItem(noticeKey, "acknowledged");
  }, EXTERNAL_DATA_NOTICE_KEY);
  const state: ApiFixtureState = {
    sessions: options.session ? [structuredClone(options.session.row)] : [],
    details: new Map(
      options.session
        ? [[options.session.row.session_id, structuredClone(options.session.detail)]]
        : [],
    ),
    closureRuns: new Map(),
    learningResume: new Map(
      options.session && options.learningResume
        ? [[options.session.row.session_id, structuredClone(options.learningResume)]]
        : [],
    ),
    failNextChat: options.failNextChat ?? false,
    chatAttempts: 0,
    unexpectedApiPaths: [],
  };

  await page.route("**/*", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;

    if (path === "/assets/avatars/nahida.png") {
      await route.fulfill({
        status: 200,
        contentType: "image/svg+xml",
        body: '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"><circle cx="16" cy="16" r="14" fill="#ddd"/></svg>',
      });
      return;
    }
    if (path === "/health") {
      await fulfillJson(route, {
        status: "ok",
        service: "study-agent",
        rag_index_exists: true,
      });
      return;
    }
    if (path === "/health/providers") {
      await fulfillJson(route, {
        status: "ready",
        preferred_provider: "searxng",
        probed: true,
        checked_at: "2026-08-13T00:00:00Z",
        providers: [
          {
            name: "searxng",
            role: "preferred",
            enabled: true,
            configured: true,
            reachable: true,
            search_capable: true,
            status: "ready",
            detail: "valid_results_returned",
            endpoint: "http://127.0.0.1:8080",
          },
          {
            name: "bing_rss",
            role: "fallback",
            enabled: true,
            configured: true,
            reachable: null,
            search_capable: null,
            status: "enabled",
            detail: "not_probed",
            endpoint: "",
          },
          {
            name: "duckduckgo_html",
            role: "last_fallback",
            enabled: true,
            configured: true,
            reachable: null,
            search_capable: null,
            status: "enabled",
            detail: "not_probed_challenge_prone",
            endpoint: "",
          },
        ],
      });
      return;
    }
    if (path === "/rag/status") {
      await fulfillJson(route, {
        index_path: "browser-fixture",
        index_exists: true,
        documents: 1,
        chunks: 1,
        vector_backend: { name: "fixture", available: true },
      });
      return;
    }
    if (path === "/knowledge-base/documents") {
      await fulfillJson(route, {
        index_path: "browser-fixture",
        index_exists: true,
        index_version: 1,
        documents: [],
        chunks: 0,
        retrievable_documents: 0,
        retrievable_chunks: 0,
      });
      return;
    }
    if (path === "/tools") {
      await fulfillJson(route, { tools: [] });
      return;
    }
    if (path === "/workflows/runs") {
      await fulfillJson(route, { runs: [] });
      return;
    }
    if (path === "/runtime/settings") {
      await fulfillJson(route, RUNTIME_SETTINGS);
      return;
    }
    if (path === "/memory") {
      await fulfillJson(route, {
        writable: true,
        memory_mode: "manual",
        safe_mode: true,
        reason: "",
        context_mode: "light",
        groups: {},
        files: [],
      });
      return;
    }
    if (path === "/wechat") {
      await fulfillJson(route, {
        group_thread_id: "",
        state: {},
        content: "",
        unread: "",
        has_unread: false,
        started: false,
        message_count: 0,
        unread_count: 0,
        summary: "",
      });
      return;
    }
    if (path === "/sessions" && request.method() === "GET") {
      await fulfillJson(route, { sessions: state.sessions });
      return;
    }
    if (path === "/sessions/new" && request.method() === "POST") {
      const sessionId = `browser-new-session-${state.sessions.length + 1}`;
      const row: SessionRow = {
        session_id: sessionId,
        kind: "current",
        name: `${sessionId}.md`,
        path: "",
        size_bytes: 0,
        mtime_ns: Date.now(),
        title: "新学习会话",
        task_intent: "",
        objective: "",
        confirmed_points: [],
        unresolved_gap: "",
        next_action: "",
        has_completed_turns: false,
      };
      state.sessions = [
        row,
        ...state.sessions.filter((session) => session.kind !== "current"),
      ];
      await fulfillJson(route, {
        session_id: sessionId,
        settings: RUNTIME_SETTINGS.settings,
      });
      return;
    }
    const closureCreateMatch = path.match(
      /^\/sessions\/([^/]+)\/learning-closure-runs$/,
    );
    if (closureCreateMatch && request.method() === "POST") {
      const sessionId = decodeURIComponent(closureCreateMatch[1]);
      const closure = closureResponse(sessionId, "preview_ready");
      state.closureRuns.set(String(closure.id), closure);
      await fulfillJson(route, closure);
      return;
    }
    const closureMatch = path.match(
      /^\/learning-closure-runs\/([^/]+)(?:\/(commit|retry|cancel))?$/,
    );
    if (closureMatch) {
      const runId = decodeURIComponent(closureMatch[1]);
      const existing = state.closureRuns.get(runId);
      if (!existing) {
        await fulfillJson(route, { detail: "closure run not found" }, 404);
        return;
      }
      if (request.method() === "GET") {
        await fulfillJson(route, existing);
        return;
      }
      if (request.method() === "POST" && closureMatch[2] === "commit") {
        const completed = closureResponse(String(existing.thread_id), "completed");
        state.closureRuns.set(runId, completed);
        await fulfillJson(route, completed);
        return;
      }
    }
    const archiveMatch = path.match(/^\/sessions\/([^/]+)\/archive$/);
    if (archiveMatch && request.method() === "POST") {
      const sessionId = decodeURIComponent(archiveMatch[1]);
      state.sessions = state.sessions.map((session) =>
        session.session_id === sessionId
          ? { ...session, kind: "archived" }
          : session,
      );
      await fulfillJson(route, {
        session_id: sessionId,
        kind: "archived",
        path: `${sessionId}.md`,
        archived: true,
      });
      return;
    }
    const resumeMatch = path.match(/^\/sessions\/([^/]+)\/learning-resume$/);
    if (resumeMatch && request.method() === "GET") {
      const sessionId = decodeURIComponent(resumeMatch[1]);
      const resume = state.learningResume.get(sessionId);
      if (!resume) {
        await fulfillJson(route, {
          source: "durable",
          status: "no_active_goal",
          topic: {},
          goal: {},
          claims: [],
          claim_count: 0,
          unresolved: [],
          next_step: {},
          optional_next_steps: [],
          legacy_confirmed_points: [],
        });
        return;
      }
      await fulfillJson(route, resume);
      return;
    }
    const revalidateMatch = path.match(
      /^\/sessions\/([^/]+)\/claims\/([^/]+)\/revalidate$/,
    );
    if (revalidateMatch && request.method() === "POST") {
      const sessionId = decodeURIComponent(revalidateMatch[1]);
      const claimId = decodeURIComponent(revalidateMatch[2]);
      const resume = state.learningResume.get(sessionId);
      if (!resume) {
        await fulfillJson(route, { detail: "claim not found" }, 404);
        return;
      }
      const claims = (resume.claims as Array<Record<string, unknown>>) ?? [];
      if (!claims.some((claim) => claim.claim_id === claimId)) {
        await fulfillJson(route, { detail: "claim not found" }, 404);
        return;
      }
      claims.forEach((claim) => {
        claim.freshness = {
          status: "current",
          head_commit: "verified-head-commit",
          reason: "revalidated against current head",
        };
      });
      state.learningResume.set(sessionId, resume);
      await fulfillJson(route, {
        claim_id: claimId,
        outcome: "revalidated",
        revision_id: "rev-revalidated",
        head_commit: "verified-head-commit",
        freshness_status: "current",
      });
      return;
    }
    const presentationPath = /^\/sessions\/([^/]+)\/turns\/([^/]+)\/research-presentation$/.exec(path);
    if (presentationPath && request.method() === "GET") {
      await fulfillJson(route, { protocol_version: 1, session_id: decodeURIComponent(presentationPath[1]),
          snapshot_kind: "turn", turn_updated_at: "2026-10-08T10:00:00Z",
        turn_id: decodeURIComponent(presentationPath[2]), publication_status: "observation_only",
        publication_authority: false, blocks: [], truncated: false, watch: false, audit_status: null, audit_integrity: "absent" });
      return;
    }
    if (path.startsWith("/sessions/") && request.method() === "GET") {
      const sessionId = decodeURIComponent(path.slice("/sessions/".length));
      const detail = state.details.get(sessionId);
      if (!detail) {
        await fulfillJson(route, { detail: "session not found" }, 404);
        return;
      }
      await fulfillJson(route, detail);
      return;
    }
    if (path === "/chat/stream" && request.method() === "POST") {
      state.chatAttempts += 1;
      if (state.failNextChat) {
        state.failNextChat = false;
        await route.fulfill({
          status: 503,
          contentType: "text/plain",
          body: "simulated chat outage",
        });
        return;
      }

      const payload = request.postDataJSON() as Record<string, unknown>;
      const question = String(payload.user_input ?? "");
      const requestedSession = String(payload.session_id ?? "");
      const existing = state.sessions.find(
        (item) => item.session_id === requestedSession,
      );
      const sessionId = requestedSession || existing?.session_id || "browser-first-session";
      const turnId = String(payload.turn_id ?? `turn-browser-${state.chatAttempts}`);
      const retry = Boolean(payload.retry_of_turn_id);
      const taskIntent = taskIntentFor(question, existing);
      const reply = replyFor(question, retry);
      const learningState = taskIntent === "learn"
        ? {
            protocol: "socratic",
            objective: existing?.objective || "理解二分查找边界条件",
            phase: "verify",
            confirmed_points: existing?.confirmed_points ?? ["每轮缩小搜索区间"],
            unresolved_gap: existing?.unresolved_gap ?? "左右边界更新时机",
            hint_level: 0,
            turn_count: 4,
            payload: {
              next_action: existing?.next_action ?? "完成一次边界迁移练习",
            },
          }
        : {};
      const responseRoute = {
        role: "nahida",
        mode: taskIntent === "learn" ? "苏格拉底" : "auto",
        model_profile: "flash",
        task_contract: {
          task_intent: taskIntent,
          source_policy: "model_only",
          closure_eligibility: taskIntent === "learn"
            ? "learning_summary"
            : "not_applicable",
          learning_state_enabled: taskIntent === "learn",
        },
        ...(taskIntent === "learn" ? { learning_state: learningState } : {}),
      };
      const previousDetail = state.details.get(sessionId);
      const nextMessages = [
        ...(previousDetail?.messages ?? []),
        { role: "user", content: question, turnId, turnStatus: "completed" },
        {
          role: "assistant",
          content: reply,
          avatarRole: "nahida",
          turnId,
          turnStatus: "completed",
        },
      ];
      const nextTurns = [
        ...(previousDetail?.turns ?? []),
        {
          turn_id: turnId,
          status: "completed",
          user_message: question,
          assistant_message: reply,
          parent_turn_id: payload.retry_of_turn_id ?? null,
          route_snapshot: responseRoute,
          rag_snapshot: ragWithExternalDataPolicy(),
          pedagogy_snapshot: taskIntent === "learn"
            ? { phase: "verify", committed_learning_state: learningState }
            : {},
        },
      ];
      const learningPayload = learningState as Record<string, unknown>;
      const nextAction = taskIntent === "learn"
        ? String((learningPayload.payload as Record<string, unknown>).next_action)
        : "继续提出下一个问题";
      const row: SessionRow = {
        session_id: sessionId,
        kind: "current",
        name: `${sessionId}.md`,
        path: "",
        size_bytes: 0,
        mtime_ns: Date.now(),
        title: existing?.title || question,
        task_intent: taskIntent,
        objective: taskIntent === "learn"
          ? String(learningPayload.objective)
          : question,
        confirmed_points: taskIntent === "learn"
          ? learningPayload.confirmed_points as string[]
          : [],
        unresolved_gap: taskIntent === "learn"
          ? String(learningPayload.unresolved_gap)
          : "",
        next_action: nextAction,
        has_completed_turns: true,
      };
      const detail: SessionDetail = {
        session_id: sessionId,
        kind: "current",
        path: "",
        messages: nextMessages,
        turns: nextTurns,
        settings: previousDetail?.settings ?? defaultSessionSettings(),
        route: responseRoute,
        rag: ragWithExternalDataPolicy(),
        learning_state: learningState,
        pedagogy: taskIntent === "learn"
          ? { phase: "verify", committed_learning_state: learningState }
          : {},
        latest_attempted_pedagogy: {},
        navigation: taskIntent === "learn"
          ? {
              phase: "verify",
              objective: learningPayload.objective,
              confirmed_points: learningPayload.confirmed_points,
              unresolved_gap: learningPayload.unresolved_gap,
              next_action: nextAction,
            }
          : {},
        conversation_instruction: "",
      };
      state.sessions = [
        row,
        ...state.sessions.filter((item) => item.session_id !== sessionId),
      ];
      state.details.set(sessionId, detail);

      const event = (name: string, data: unknown) =>
        `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`;
      const split = Math.ceil(reply.length / 2);
      const body = [
        event("session", {
          session_id: sessionId,
          turn_id: turnId,
          operation_id: `operation-${state.chatAttempts}`,
        }),
        event("route", { route: responseRoute }),
        event("rag", { rag: ragWithExternalDataPolicy() }),
        event("token", { text: reply.slice(0, split) }),
        event("token", { text: reply.slice(split) }),
        event("done", {
          session_id: sessionId,
          turn_id: turnId,
          reply,
          pedagogy: taskIntent === "learn"
            ? {
                mode: "socratic",
                phase: "verify",
                move: "probe",
                disclosure_level: 1,
              }
            : undefined,
        }),
      ].join("");
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        headers: { "Cache-Control": "no-cache" },
        body,
      });
      return;
    }

    if (["fetch", "xhr"].includes(request.resourceType())) {
      state.unexpectedApiPaths.push(`${request.method()} ${path}`);
      await fulfillJson(
        route,
        { detail: `unhandled browser fixture path: ${path}` },
        404,
      );
      return;
    }
    await route.continue();
  });

  return state;
}

export async function seedWorkspaceRecovery(page: Page, sessionId: string) {
  await page.addInitScript(
    ({ key, value }) => window.localStorage.setItem(key, value),
    {
      key: STORAGE_KEY,
      value: JSON.stringify({
        schemaVersion: 3,
        savedAt: new Date().toISOString(),
        workspace: {
          singleChatSessionId: sessionId,
          lastSessionId: sessionId,
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
      }),
    },
  );
}
