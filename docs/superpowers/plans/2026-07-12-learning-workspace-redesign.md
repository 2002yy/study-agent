# 学习工作台 UI 重构实现计划（方案 B）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把工作台从三列重构为"双栏专注 + 学习伴侣栏"：教学法状态一等公民可视化、联网工具逐条可追溯、次要面板降级为 slide-over。

**Architecture:** `AppShell` 三列网格改两列（340px 学习面板 + 1fr 对话栏）。教学法状态来自 `lastChat.route.learning_state`；联网/RAG 证据来自 `lastChat.rag`；本轮教学动作来自新增 `ChatResponse.pedagogy`（后端小改，决策 a，取自 `PreparedChatTurn.pedagogy_plan`）。每条 assistant 消息挂 `evidence`（实时从 response 填充；恢复从 session detail 按 turnId 回填教学法动作）。次要面板用通用 `SlideOver` 抽屉，由对话栏顶栏 dock 按钮触发。组件抽取纯函数供 vitest 单测（本仓库无 DOM 测试库范式）。

**Tech Stack:** React 18 + TS + Vite 8、vitest 4、lucide-react、纯 `styles.css`（深青 CSS 变量已存在）、FastAPI/Pydantic。

**Spec:** `docs/superpowers/specs/2026-07-12-learning-workspace-redesign-design.md`

**测试命令：**
- 后端：`$env:PYTHONPATH="."; python -m pytest <path> -q`（全量 `python -m pytest -q`）
- 前端：`npx vitest run <path>`（全量 `npx vitest run`）；构建 `npm run build`（在 `frontend/`）

---

## 文件结构

**新建（前端）：**
- `frontend/src/features/pedagogy/pedagogyLabels.ts`（+`.test.ts`）- 纯函数 `moveLabel`/`protocolLabel`/`deriveMastery`/`phaseTrail`
- `frontend/src/features/learning/LearningPanel.tsx` - 左栏 + 子组件 `ObjectiveCard`/`MasteryRing`/`GapAlert`/`ConfirmedPoints`/`PhaseIndicator`/`TurnMoveBadge`/`MemorySnapshot`
- `frontend/src/features/evidence/evidenceHelpers.ts`（+`.test.ts`）- `summarizeWebCalls`/`buildCitations`/`evidenceFromResponse`/`evidenceFromSessionTurns`
- `frontend/src/features/evidence/EvidenceTrail.tsx` - 消息下方证据轨迹 + `WebToolCallCard`
- `frontend/src/components/SlideOver.tsx` - 通用抽屉
- `frontend/src/features/settings/SettingsDrawer.tsx` - 设置抽屉（迁自 Sidebar）

**修改（前端）：** `types.ts`、`app/workspaceReducer.ts`(+test)、`features/chat/chatController.ts`、`features/single-chat/ChatPanel.tsx`、`app/WorkspaceView.tsx`、`styles.css`

**修改（后端）：** `src/api/models/chat.py`、`src/api/routes/chat_routes.py`、新增 `tests/test_chat_routes_pedagogy.py`

---

## Task 1: 后端 - ChatResponse 补 pedagogy 摘要（决策 a）

`PreparedChatTurn.pedagogy_plan`（`chat_service.py:91`）已有 `mode/phase/move/disclosure_level`，直接提取，不改 chat_service。

**Files:** Modify `src/api/models/chat.py`、`src/api/routes/chat_routes.py`；Test `tests/test_chat_routes_pedagogy.py`

- [ ] **Step 1: 写失败测试** `tests/test_chat_routes_pedagogy.py`

```python
from __future__ import annotations
from types import SimpleNamespace
from src.api.routes.chat_routes import pedagogy_summary_from_plan


def _plan(**overrides):
    base = {"mode": "socratic", "phase": "scaffold", "move": "give_hint",
            "disclosure_level": 2, "knowledge_kind": "derivable",
            "learner_claim": "", "unresolved_gap": "", "target_understanding": "",
            "library_needed": False, "evidence_ids": (), "constraints": ()}
    base.update(overrides)
    return SimpleNamespace(**base)


def test_pedagogy_summary_picks_compact_fields():
    assert pedagogy_summary_from_plan(_plan()) == {
        "mode": "socratic", "phase": "scaffold", "move": "give_hint", "disclosure_level": 2}


def test_pedagogy_summary_handles_missing_attributes():
    assert pedagogy_summary_from_plan(SimpleNamespace()) == {
        "mode": "", "phase": "", "move": "", "disclosure_level": 0}
```

- [ ] **Step 2: 运行确认失败** `python -m pytest tests/test_chat_routes_pedagogy.py -q` → FAIL（ImportError）

- [ ] **Step 3: 实现** 在 `src/api/routes/chat_routes.py` 导入区后加：

```python
from typing import Any


def pedagogy_summary_from_plan(plan: Any) -> dict[str, Any]:
    """Compact pedagogy snapshot for the chat response (decision point a)."""
    return {
        "mode": str(getattr(plan, "mode", "") or ""),
        "phase": str(getattr(plan, "phase", "") or ""),
        "move": str(getattr(plan, "move", "") or ""),
        "disclosure_level": int(getattr(plan, "disclosure_level", 0) or 0),
    }
```

`src/api/models/chat.py` 的 `ChatResponse` 在 `rag` 字段后加：`pedagogy: dict = Field(default_factory=dict)`

`chat_routes.py` 非流式返回（约 37-43 行）加 `pedagogy=pedagogy_summary_from_plan(prepared.pedagogy_plan)`；`done` 事件 payload（约 80-84 行）加 `"pedagogy": pedagogy_summary_from_plan(prepared.pedagogy_plan)`。

- [ ] **Step 4: 运行确认通过** `python -m pytest tests/test_chat_routes_pedagogy.py -q` → 2 passed

- [ ] **Step 5: 回归** `python -m pytest -q` → 546 passed

- [ ] **Step 6: 提交** `git add src/api/models/chat.py src/api/routes/chat_routes.py tests/test_chat_routes_pedagogy.py && git commit -m "feat(api): expose compact pedagogy summary in ChatResponse and stream done event"`

---

## Task 2: 前端类型 - 强类型接口 + evidence + DrawerId

**Files:** Modify `frontend/src/types.ts`

- [ ] **Step 1: 在 `ChatMessage` 之前加类型**

```typescript
export type PedagogySummary = {
  mode: string; phase: string; move: string; disclosure_level: number;
};

export type LearningState = {
  protocol: string; protocol_version?: number; objective: string; phase: string;
  learner_claim?: string; confirmed_points?: string[]; unresolved_gap: string;
  attempted_examples?: string[]; hint_level: number; library_facts_given?: string[];
  turn_count: number; payload?: Record<string, unknown>;
};

export type WebToolCall = {
  name: string; arguments: Record<string, unknown>; result: Record<string, unknown>;
};

export type TurnEvidence = {
  pedagogy?: PedagogySummary;
  rag?: ChatResponse["rag"];
  route?: Record<string, unknown>;
};

export type DrawerId = "group" | "news" | "tools" | "sessions" | "memory" | "settings";
```

- [ ] **Step 2: `ChatMessage` 加 `evidence?: TurnEvidence;`（在 `parentTurnId?` 后）**

- [ ] **Step 3: `ChatResponse` 在 `rag` 块后加 `pedagogy?: PedagogySummary;`**

- [ ] **Step 4: 提交** `git add frontend/src/types.ts && git commit -m "feat(types): add PedagogySummary, LearningState, TurnEvidence, DrawerId"`

---

## Task 3: workspaceReducer - activeDrawer + 开关动作

**Files:** Modify `frontend/src/app/workspaceReducer.ts`(+`.test.ts`)

- [ ] **Step 1: 写失败测试** 在 `workspaceReducer.test.ts` 的 `describe` 内加：

```typescript
  it("opens and closes a slide-over drawer", () => {
    const opened = workspaceReducer(createWorkspaceRuntimeState(), { type: "OPEN_DRAWER", drawer: "settings" });
    expect(opened.activeDrawer).toBe("settings");
    expect(workspaceReducer(opened, { type: "CLOSE_DRAWER" }).activeDrawer).toBeNull();
  });

  it("opening a drawer replaces the previous one", () => {
    const next = workspaceReducer(createWorkspaceRuntimeState({ activeDrawer: "group" }), { type: "OPEN_DRAWER", drawer: "memory" });
    expect(next.activeDrawer).toBe("memory");
  });
```

顶部导入改为 `import type { ChatMessage, ChatResponse, DrawerId } from "../types";`

- [ ] **Step 2: 运行确认失败** `npx vitest run frontend/src/app/workspaceReducer.test.ts` → FAIL

- [ ] **Step 3: 实现** `WorkspaceRuntimeState` 加 `activeDrawer: DrawerId | null;`；`createWorkspaceRuntimeState` 默认加 `activeDrawer: null,`；`WorkspaceAction` 加 `| { type: "OPEN_DRAWER"; drawer: DrawerId } | { type: "CLOSE_DRAWER" }`；switch 加（`SELECT_PANEL` 前）：

```typescript
    case "OPEN_DRAWER":
      return { ...state, activeDrawer: action.drawer };
    case "CLOSE_DRAWER":
      return { ...state, activeDrawer: null };
```

- [ ] **Step 4: 运行确认通过** → 6 passed

- [ ] **Step 5: 提交** `git add frontend/src/app/workspaceReducer.ts frontend/src/app/workspaceReducer.test.ts && git commit -m "feat(workspace): add activeDrawer state with OPEN/CLOSE_DRAWER actions"`

---

## Task 4: SlideOver 通用抽屉组件

**Files:** Create `frontend/src/components/SlideOver.tsx`（薄展示层，逻辑由 reducer 覆盖）

- [ ] **Step 1: 创建**

```typescript
import { X } from "lucide-react";
import { useEffect, type ReactNode } from "react";

export function SlideOver({ open, title, onClose, children }: {
  open: boolean; title: string; onClose: () => void; children: ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="slide-over-root" role="dialog" aria-modal="true" aria-label={title}>
      <button className="slide-over-backdrop" onClick={onClose} aria-label="关闭" type="button" />
      <aside className="slide-over">
        <header className="slide-over-header">
          <strong>{title}</strong>
          <button className="icon-button" onClick={onClose} type="button" title="关闭"><X size={17} /></button>
        </header>
        <div className="slide-over-body">{children}</div>
      </aside>
    </div>
  );
}
```

- [ ] **Step 2: 提交** `git add frontend/src/components/SlideOver.tsx && git commit -m "feat(ui): add SlideOver drawer component"`

---

## Task 5: 教学法标签纯函数 + 测试

**Files:** Create `frontend/src/features/pedagogy/pedagogyLabels.ts`(+`.test.ts`)

- [ ] **Step 1: 写失败测试** `frontend/src/features/pedagogy/pedagogyLabels.test.ts`

```typescript
import { describe, expect, it } from "vitest";
import { deriveMastery, moveLabel, phaseTrail, protocolLabel } from "./pedagogyLabels";
import type { LearningState } from "../../types";

describe("pedagogyLabels", () => {
  it("maps known moves to Chinese", () => {
    expect(moveLabel("give_hint")).toBe("给提示");
    expect(moveLabel("elicit_claim")).toBe("引出主张");
    expect(moveLabel("direct_explain")).toBe("直接讲解");
  });
  it("falls back to raw code for unknown moves", () => {
    expect(moveLabel("unknown_move")).toBe("unknown_move");
  });
  it("labels protocols in Chinese", () => {
    expect(protocolLabel("socratic")).toBe("苏格拉底");
    expect(protocolLabel("socratic_rediscovery")).toBe("苏格拉底");
    expect(protocolLabel("feynman")).toBe("费曼");
    expect(protocolLabel("project")).toBe("项目");
    expect(protocolLabel("direct")).toBe("普通");
    expect(protocolLabel("auto")).toBe("自动");
  });
  it("derives mastery in (0,1) from points and phase trail", () => {
    const state: LearningState = {
      protocol: "socratic", objective: "x", phase: "scaffold",
      unresolved_gap: "gap", confirmed_points: ["a", "b"], hint_level: 1, turn_count: 4,
    };
    const m = deriveMastery(state, ["orientation", "library_fact", "scaffold"]);
    expect(m).toBeGreaterThan(0);
    expect(m).toBeLessThan(1);
  });
  it("dedupes phase trail preserving order", () => {
    expect(phaseTrail(["orientation", "library_fact", "library_fact", "scaffold"]))
      .toEqual(["orientation", "library_fact", "scaffold"]);
  });
});
```

- [ ] **Step 2: 运行确认失败** `npx vitest run frontend/src/features/pedagogy/pedagogyLabels.test.ts` -> FAIL

- [ ] **Step 3: 实现** `frontend/src/features/pedagogy/pedagogyLabels.ts`

```typescript
import type { LearningState } from "../../types";

const MOVE_LABELS: Record<string, string> = {
  elicit_claim: "引出主张", clarify_definition: "澄清定义", expose_assumption: "暴露假设",
  request_prediction: "请求预测", test_example: "举例验证", offer_counterexample: "给反例",
  surface_contradiction: "揭示矛盾", give_hint: "给提示", provide_library_fact: "提供事实",
  reconstruct: "重构理解", transfer: "迁移", direct_explain: "直接讲解", set_scope: "界定范围",
  invite_explanation: "邀请解释", identify_main_gap: "定位缺口", minimal_repair: "最小修补",
  request_reexplanation: "要求重讲", transfer_test: "迁移检验", define_acceptance: "定义验收",
  inspect_artifact: "检查产出", form_hypothesis: "形成假设", choose_solution: "选择方案",
  apply_patch: "应用补丁", run_validation: "运行验证", close_stage: "收束阶段",
};

const PROTOCOL_LABELS: Record<string, string> = {
  socratic: "苏格拉底", socratic_rediscovery: "苏格拉底", feynman: "费曼",
  project: "项目", direct: "普通", auto: "自动",
};

export function moveLabel(move: string): string {
  return MOVE_LABELS[move] ?? move;
}

export function protocolLabel(protocol: string): string {
  return PROTOCOL_LABELS[protocol] ?? (protocol || "自动");
}

export function phaseTrail(phases: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const p of phases) {
    if (p && !seen.has(p)) { seen.add(p); out.push(p); }
  }
  return out;
}

export function deriveMastery(state: LearningState, visitedPhases: string[]): number {
  const confirmed = state.confirmed_points?.length ?? 0;
  const gap = state.unresolved_gap ? 1 : 0;
  const pointRatio = confirmed / Math.max(1, confirmed + gap);
  const totalPhases = Math.max(1, visitedPhases.length);
  const phaseRatio = visitedPhases.includes(state.phase)
    ? (visitedPhases.indexOf(state.phase) + 1) / totalPhases
    : 0;
  return Math.max(0, Math.min(1, 0.5 * pointRatio + 0.5 * phaseRatio));
}
```

- [ ] **Step 4: 运行确认通过** -> 5 passed

- [ ] **Step 5: 提交** `git add frontend/src/features/pedagogy && git commit -m "feat(pedagogy): add move/protocol labels, mastery derivation, phase trail helpers"`

---

## Task 6: 证据辅助函数 + 测试

**Files:** Create `frontend/src/features/evidence/evidenceHelpers.ts`(+`.test.ts`)

- [ ] **Step 1: 写失败测试** `frontend/src/features/evidence/evidenceHelpers.test.ts`

```typescript
import { describe, expect, it } from "vitest";
import {
  buildCitations, evidenceFromResponse, evidenceFromSessionTurns, summarizeWebCalls,
} from "./evidenceHelpers";
import type { ChatResponse } from "../../types";

const baseRag: ChatResponse["rag"] = {
  status: "ok", query: "q", retrieval_mode: "hybrid", reason: "", context: "",
  sources: "", result_count: 1, results: [], debug: {}, attempts: [], rewritten_query: "",
};

describe("evidenceHelpers", () => {
  it("summarizes web_search and web_read calls", () => {
    const calls = summarizeWebCalls([
      { name: "web_search", arguments: { query: "FastAPI" }, result: { results: [{ title: "t", url: "u" }] } },
      { name: "web_read", arguments: { url: "https://x.com" }, result: { ok: "true", content: "page".repeat(200) } },
    ]);
    expect(calls.searches).toEqual([{ query: "FastAPI", results: [{ title: "t", url: "u" }] }]);
    expect(calls.reads[0].url).toBe("https://x.com");
    expect(calls.reads[0].preview.length).toBeLessThanOrEqual(300);
  });
  it("builds citations from rag results", () => {
    const cites = buildCitations({ ...baseRag, results: [{ title: "Doc", source_path: "a.md", score: 0.8 }] as never });
    expect(cites[0]).toMatchObject({ title: "Doc", source: "a.md", score: 0.8 });
  });
  it("builds evidence from a ChatResponse", () => {
    const resp: ChatResponse = {
      reply: "r", session_id: "s", turn_id: "t1",
      route: { mode: "socratic" }, rag: baseRag,
      pedagogy: { mode: "socratic", phase: "scaffold", move: "give_hint", disclosure_level: 2 },
    };
    const ev = evidenceFromResponse(resp);
    expect(ev.pedagogy?.move).toBe("give_hint");
    expect(ev.rag).toBe(baseRag);
    expect(ev.route).toEqual({ mode: "socratic" });
  });
  it("maps session turns to evidence by turnId (pedagogy only)", () => {
    const map = evidenceFromSessionTurns([
      { turn_id: "t1", pedagogy_snapshot: { mode: "socratic", move: "give_hint", phase: "scaffold", disclosure_level: 1 } },
    ]);
    expect(map.get("t1")?.pedagogy?.move).toBe("give_hint");
    expect(map.get("t1")?.rag).toBeUndefined();
  });
});
```

- [ ] **Step 2: 运行确认失败** `npx vitest run frontend/src/features/evidence/evidenceHelpers.test.ts` -> FAIL

- [ ] **Step 3: 实现** `frontend/src/features/evidence/evidenceHelpers.ts`

```typescript
import type { ChatResponse, PedagogySummary, TurnEvidence, WebToolCall } from "../../types";

export type WebSearchSummary = { query: string; results: { title?: string; url?: string; snippet?: string }[] };
export type WebReadSummary = { url: string; ok: boolean; preview: string; error?: string };
export type WebCallsSummary = { searches: WebSearchSummary[]; reads: WebReadSummary[] };

export function summarizeWebCalls(calls: WebToolCall[] | undefined): WebCallsSummary {
  const out: WebCallsSummary = { searches: [], reads: [] };
  for (const call of calls ?? []) {
    if (call.name === "web_search") {
      const results = Array.isArray((call.result as { results?: unknown }).results)
        ? (call.result as { results: { title?: string; url?: string; snippet?: string }[] }).results
        : [];
      out.searches.push({ query: String(call.arguments.query ?? ""), results });
    } else if (call.name === "web_read") {
      const r = call.result as { ok?: string; content?: string; url?: string; error?: string };
      out.reads.push({
        url: String(call.arguments.url ?? r.url ?? ""),
        ok: r.ok === "true",
        preview: (r.content ?? "").slice(0, 300),
        error: r.error,
      });
    }
  }
  return out;
}

export type Citation = { title: string; source: string; score: number };

export function buildCitations(rag: ChatResponse["rag"]): Citation[] {
  const results = (rag.results ?? []) as Array<Record<string, unknown>>;
  return results.map((r) => ({
    title: String(r.title ?? r.source_path ?? "未命名"),
    source: String(r.source_path ?? r.source ?? ""),
    score: Number(r.score ?? 0),
  }));
}

export function evidenceFromResponse(resp: ChatResponse): TurnEvidence {
  return { pedagogy: resp.pedagogy, rag: resp.rag, route: resp.route };
}

type SessionTurn = { turn_id: string; pedagogy_snapshot?: Record<string, unknown> };

export function evidenceFromSessionTurns(turns: SessionTurn[]): Map<string, TurnEvidence> {
  const map = new Map<string, TurnEvidence>();
  for (const turn of turns) {
    const snap = turn.pedagogy_snapshot ?? {};
    const pedagogy: PedagogySummary | undefined =
      typeof snap.mode === "string" || typeof snap.move === "string"
        ? {
            mode: String(snap.mode ?? ""),
            phase: String(snap.phase ?? ""),
            move: String(snap.move ?? ""),
            disclosure_level: Number(snap.disclosure_level ?? 0),
          }
        : undefined;
    if (pedagogy) map.set(turn.turn_id, { pedagogy });
  }
  return map;
}
```

- [ ] **Step 4: 运行确认通过** -> 4 passed

- [ ] **Step 5: 提交** `git add frontend/src/features/evidence/evidenceHelpers.ts frontend/src/features/evidence/evidenceHelpers.test.ts && git commit -m "feat(evidence): add web-call summarizer, citation builder, evidence mappers"`

---

## Task 7: EvidenceTrail 组件

**Files:** Create `frontend/src/features/evidence/EvidenceTrail.tsx`（薄展示层，复用 Task 5/6 纯函数）

- [ ] **Step 1: 创建**

```typescript
import { ChevronDown, ChevronRight, FileText, Search } from "lucide-react";
import { useState } from "react";
import { moveLabel, protocolLabel } from "../pedagogy/pedagogyLabels";
import { buildCitations, summarizeWebCalls } from "./evidenceHelpers";
import type { TurnEvidence } from "../../types";

export function EvidenceTrail({ evidence }: { evidence: TurnEvidence }) {
  const [open, setOpen] = useState(false);
  const pedagogy = evidence.pedagogy;
  const rag = evidence.rag;
  const web = rag ? summarizeWebCalls((rag.web_tools?.calls as never) ?? []) : { searches: [], reads: [] };
  const citations = rag ? buildCitations(rag) : [];
  const webUsed = Boolean(rag?.web_tools?.used);
  const webError = rag?.web_tools?.error;
  if (!pedagogy && citations.length === 0 && !webUsed && !webError) return null;
  return (
    <div className="evidence-trail">
      <button className="evidence-toggle" onClick={() => setOpen((v) => !v)} type="button">
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        证据轨迹
        {pedagogy ? <span className="move-badge">{protocolLabel(pedagogy.mode)} · {moveLabel(pedagogy.move)}</span> : null}
        {webUsed ? <span className="web-flag">联网 {web.searches.length + web.reads.length}</span> : null}
        {citations.length ? <span className="cite-flag">引用 {citations.length}</span> : null}
      </button>
      {open ? (
        <div className="evidence-detail">
          {webError ? <div className="evidence-error">联网工具错误：{webError}</div> : null}
          {web.searches.map((s, i) => (
            <div key={`s${i}`} className="web-call-card">
              <div className="web-call-head"><Search size={13} /> 搜索 “{s.query}”</div>
              {s.results.slice(0, 3).map((r, j) => (
                <a key={j} className="web-result" href={r.url} target="_blank" rel="noreferrer">
                  {r.title || r.url}{r.url ? <span className="web-url">{r.url}</span> : null}
                </a>
              ))}
            </div>
          ))}
          {web.reads.map((r, i) => (
            <div key={`r${i}`} className="web-call-card">
              <div className="web-call-head"><FileText size={13} /> 阅读 {r.url}</div>
              <p className="web-preview">{r.error ? `读取失败：${r.error}` : r.preview}</p>
            </div>
          ))}
          {citations.length ? (
            <ol className="citation-list">
              {citations.map((c, i) => (
                <li key={i}><strong>[{i + 1}]</strong> {c.title} <span className="cite-src">{c.source}</span> <span className="cite-score">{c.score.toFixed(2)}</span></li>
              ))}
            </ol>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
```

- [ ] **Step 2: 提交** `git add frontend/src/features/evidence/EvidenceTrail.tsx && git commit -m "feat(evidence): add collapsible EvidenceTrail with web/RAG/pedagogy sections"`

---

## Task 8: chatController 填充 evidence（实时 + 恢复）

**Files:** Modify `frontend/src/features/chat/chatController.ts`

- [ ] **Step 1: 导入** 顶部 import 区加：

```typescript
import { evidenceFromResponse, evidenceFromSessionTurns } from "../evidence/evidenceHelpers";
```

- [ ] **Step 2: 实时填充（onDone）** 在 `onDone` 回调里，把写入 `done.reply` 的 `setMessages` 块（约 244-252 行）替换为同时写 `evidence`：

```typescript
              const donePedagogy = (done as { pedagogy?: ChatResponse["pedagogy"] }).pedagogy;
              setMessages((current) =>
                current.map((message, index) =>
                  index === assistantIndex
                    ? {
                        ...message,
                        content: done.reply as string,
                        turnStatus: "completed",
                        evidence: donePedagogy
                          ? { pedagogy: donePedagogy, route: streamedRoute, rag: streamedRag ?? undefined }
                          : message.evidence,
                      }
                    : index === userIndex
                      ? { ...message, turnStatus: "completed" }
                      : message
                )
              );
```

并在 `send` 末尾 final settlement 的 `setMessages`（约 266-276 行）里，给 assistant 消息补 `evidence: evidenceFromResponse(response)`：

```typescript
      setMessages((current) =>
        current.map((message, index) =>
          index === assistantIndex
            ? {
                ...message,
                content: effectiveReply,
                avatarRole: String(response.route.role ?? "auto"),
                evidence: evidenceFromResponse(response),
              }
            : message
        )
      );
```

- [ ] **Step 3: 恢复填充（applySessionDetail）** 在 `applySessionDetail` 里（约 394-478 行），构建 `restoredMessages` 后、`transitionSession` 前，用 `detail.turns` 按 `turnId` 回填 pedagogy 证据。在 `const restoredLastChat...` 之前插入：

```typescript
    const evidenceByTurn = evidenceFromSessionTurns(detail.turns ?? []);
    const restoredWithEvidence = restoredMessages.map((message) =>
      message.turnId && evidenceByTurn.has(message.turnId)
        ? { ...message, evidence: evidenceByTurn.get(message.turnId) }
        : message
    );
```

然后把 `transitionSession(detail.session_id, restoredMessages.length ? restoredMessages : seedMessages, ...)` 改为用 `restoredWithEvidence`：

```typescript
    transitionSession(
      detail.session_id,
      restoredWithEvidence.length ? restoredWithEvidence : seedMessages,
      restoredLastChat,
      restoredRecovery
    );
```

- [ ] **Step 4: 运行现有 chatController 测试确认不回归** `npx vitest run frontend/src/features/chat` -> 全绿

- [ ] **Step 5: 提交** `git add frontend/src/features/chat/chatController.ts && git commit -m "feat(chat): attach per-turn evidence to assistant messages (live + restored)"`

---

## Task 9: LearningPanel 学习面板 + 子组件

**Files:** Create `frontend/src/features/learning/LearningPanel.tsx`

数据源：`lastChat.route.learning_state`（提交后状态）+ `lastChat.pedagogy`（本轮动作）+ session detail `turns`（阶段轨迹）+ `memoryStatus`（记忆快照）。learning_state 取值用安全访问，因 `route` 为 `Record<string,unknown>`。

- [ ] **Step 1: 创建** `frontend/src/features/learning/LearningPanel.tsx`

```typescript
import { AlertTriangle, BookOpen, CheckCircle2, Target } from "lucide-react";
import { useMemo } from "react";
import { latestMemorySection } from "../single-chat/ChatPanel";
import { deriveMastery, moveLabel, phaseTrail, protocolLabel } from "../pedagogy/pedagogyLabels";
import type { ChatResponse, LearningState, MemoryStatusResponse, SessionDetailResponse } from "../../types";

function asLearningState(raw: unknown): LearningState | null {
  if (!raw || typeof raw !== "object") return null;
  const o = raw as Record<string, unknown>;
  return {
    protocol: String(o.protocol ?? ""),
    objective: String(o.objective ?? ""),
    phase: String(o.phase ?? ""),
    unresolved_gap: String(o.unresolved_gap ?? ""),
    confirmed_points: Array.isArray(o.confirmed_points) ? (o.confirmed_points as string[]) : [],
    hint_level: Number(o.hint_level ?? 0),
    turn_count: Number(o.turn_count ?? 0),
  };
}

export function LearningPanel({
  lastChat, sessionDetail, memoryStatus,
}: {
  lastChat: ChatResponse | null;
  sessionDetail: SessionDetailResponse | null;
  memoryStatus: MemoryStatusResponse | null;
}) {
  const state = asLearningState(lastChat?.route?.learning_state);
  const pedagogy = lastChat?.pedagogy;
  const visitedPhases = useMemo(
    () => phaseTrail((sessionDetail?.turns ?? []).map((t) => String((t as { phase?: string }).phase ?? "")).filter(Boolean)),
    [sessionDetail]
  );
  const mastery = state ? deriveMastery(state, visitedPhases) : 0;
  const confirmed = state?.confirmed_points ?? [];
  const focus = memoryStatus?.latest_section || latestMemorySection(memoryStatus, "current_focus.md", "尚无当前学习重点。");

  return (
    <aside className="learning-panel">
      <header className="learning-header"><BookOpen size={16} /> 学习伴侣</header>

      <section className="learning-card objective-card">
        <div className="card-label"><Target size={13} /> 学习目标</div>
        <p>{state?.objective || "发一条学习请求以建立目标"}</p>
      </section>

      <section className="learning-card phase-card">
        <div className="card-label">阶段轨迹</div>
        {state ? (
          <div className="phase-indicator">
            <span className="phase-current">{protocolLabel(state.protocol)} · {state.phase || "未开始"}</span>
            {visitedPhases.length ? (
              <ol className="phase-trail">{visitedPhases.map((p) => <li key={p} className={p === state.phase ? "is-current" : ""}>{p}</li>)}</ol>
            ) : null}
          </div>
        ) : <p className="muted">尚无学习状态</p>}
      </section>

      <section className="learning-card mastery-card">
        <div className="card-label">掌握度</div>
        <div className="mastery-row">
          <div className="mastery-ring" style={{ background: `conic-gradient(var(--accent) ${mastery * 360}deg, var(--surface-strong) 0)` }}>
            <span>{Math.round(mastery * 100)}%</span>
          </div>
          <div className="mastery-meta">
            <span>已确认 {confirmed.length} 点</span>
            <span>提示级别 L{state?.hint_level ?? 0}</span>
            <span>第 {state?.turn_count ?? 0} 轮</span>
          </div>
        </div>
      </section>

      <section className={`learning-card gap-card${state?.unresolved_gap ? " has-gap" : ""}`}>
        <div className="card-label"><AlertTriangle size={13} /> 当前缺口</div>
        <p>{state?.unresolved_gap || "无未解决缺口"}</p>
      </section>

      <section className="learning-card confirmed-card">
        <div className="card-label"><CheckCircle2 size={13} /> 已确认点</div>
        {confirmed.length ? (
          <ul className="confirmed-list">{confirmed.map((c, i) => <li key={i}>{c}</li>)}</ul>
        ) : <p className="muted">尚未确认知识点</p>}
      </section>

      {pedagogy ? (
        <section className="learning-card move-card">
          <div className="card-label">本轮动作</div>
          <span className="move-badge">{protocolLabel(pedagogy.mode)} · {moveLabel(pedagogy.move)}</span>
        </section>
      ) : null}

      <details className="learning-card memory-snapshot">
        <summary>记忆快照</summary>
        <p className="muted">{focus}</p>
      </details>
    </aside>
  );
}
```

- [ ] **Step 2: 提交** `git add frontend/src/features/learning/LearningPanel.tsx && git commit -m "feat(learning): add LearningPanel with objective, phase trail, mastery ring, gap, confirmed points"`

---

## Task 10: ChatPanel - dock 按钮 + 渲染 EvidenceTrail

**Files:** Modify `frontend/src/features/single-chat/ChatPanel.tsx`

- [ ] **Step 1: 导入** 顶部加：

```typescript
import { EvidenceTrail } from "../evidence/EvidenceTrail";
import { BookOpen, Database, MessageSquare, MemoryStick, Settings, Wrench } from "lucide-react";
import type { DrawerId } from "../../types";
```

- [ ] **Step 2: 加 dock 按钮 prop** 在 `ChatPanel` 参数解构与类型里加 `onOpenDrawer: (drawer: DrawerId) => void;`（在 `memoryStatus` 之后）。

- [ ] **Step 3: 顶栏加 dock 按钮组** 把 `topbar-actions`（约 109-116 行）改为：

```typescript
        <div className="topbar-actions">
          <button className="icon-button" onClick={onUploadClick} type="button" title="上传资料"><Upload size={17} /></button>
          <button className="icon-button" disabled={!hasSearchQuery} onClick={onSearchSources} type="button" title={hasSearchQuery ? "检索来源" : "输入关键词或通过 RAG 提问后可检索"}>
            {isSearching ? <Loader2 className="spin" size={17} /> : <Search size={17} />}
          </button>
          <span className="dock-divider" />
          <button className="icon-button" onClick={() => onOpenDrawer("group")} type="button" title="群聊"><MessageSquare size={16} /></button>
          <button className="icon-button" onClick={() => onOpenDrawer("news")} type="button" title="新闻"><Database size={16} /></button>
          <button className="icon-button" onClick={() => onOpenDrawer("tools")} type="button" title="工具"><Wrench size={16} /></button>
          <button className="icon-button" onClick={() => onOpenDrawer("sessions")} type="button" title="会话"><BookOpen size={16} /></button>
          <button className="icon-button" onClick={() => onOpenDrawer("memory")} type="button" title="记忆"><MemoryStick size={16} /></button>
          <button className="icon-button" onClick={() => onOpenDrawer("settings")} type="button" title="设置"><Settings size={16} /></button>
        </div>
```

- [ ] **Step 4: 消息下渲染 EvidenceTrail** 把消息渲染（约 150-162 行）的 `<article>` 内 `message-body` 之后加：

```typescript
            <article className={`message ${message.role}`} key={`${message.role}-${index}`}>
              <RoleAvatar fallback={message.role === "user" ? "user" : "assistant"} roleId={avatarRole} />
              <div className="message-body">
                <span>{label}</span>
                <MarkdownMessage content={message.content} />
                {message.role === "assistant" && message.evidence ? <EvidenceTrail evidence={message.evidence} /> : null}
              </div>
            </article>
```

- [ ] **Step 5: 运行现有 ChatPanel 测试不回归** `npx vitest run frontend/src/features/single-chat/ChatPanel.test.ts` -> 绿

- [ ] **Step 6: 提交** `git add frontend/src/features/single-chat/ChatPanel.tsx && git commit -m "feat(chat): add drawer dock buttons and inline EvidenceTrail under assistant messages"`

---

## Task 11: pedagogyPhases 状态 + WorkspaceView 两栏接线

`sessionDetail` 不在 workspace state（chatController 本地消费后丢弃）。加一个 `pedagogyPhases` 字段供 LearningPanel 阶段轨迹。同时把 LearningPanel 的 `sessionDetail` prop 改为 `visitedPhases: string[]`。

**Files:** Modify `workspaceReducer.ts`、`chatController.ts`、`WorkspaceView.tsx`、`LearningPanel.tsx`

- [ ] **Step 1: reducer 加字段** `WorkspaceRuntimeState` 加 `pedagogyPhases: string[];`；`createWorkspaceRuntimeState` 默认 `pedagogyPhases: [],`；`WorkspaceAction` 加 `| { type: "SET_PEDAGOGY_PHASES"; value: string[] }`；switch 加：

```typescript
    case "SET_PEDAGOGY_PHASES":
      return { ...state, pedagogyPhases: action.value };
```

并在 `START_NEW_CHAT_SESSION` case 的返回里加 `pedagogyPhases: []`（新会话清空）。

- [ ] **Step 2: chatController 回填** 在 `applySessionDetail` 里 `transitionSession(...)` 之后加：

```typescript
    const phases = phaseTrail(
      (detail.turns ?? [])
        .map((t) => String((t as { phase?: string }).phase ?? ""))
        .filter(Boolean)
    );
    dispatch({ type: "SET_PEDAGOGY_PHASES", value: phases });
```

顶部加导入 `import { phaseTrail } from "../pedagogy/pedagogyLabels";`。`dispatch` 已在作用域内（`useWorkspace()` 解构）。

- [ ] **Step 3: LearningPanel prop 调整** 把 `LearningPanel` 的 `sessionDetail: SessionDetailResponse | null` 改为 `visitedPhases: string[]`；删掉 `useMemo` 与 `sessionDetail` 引用，`visitedPhases` 直接用 prop；`mastery = state ? deriveMastery(state, visitedPhases) : 0`。

- [ ] **Step 4: WorkspaceView 两栏接线** 重写 `WorkspaceView` 的 return（保留 `handleUpload`/`submit`/`partialErrors`）。引入：

```typescript
import { LearningPanel } from "../features/learning/LearningPanel";
import { SlideOver } from "../components/SlideOver";
import { useWorkspace } from "./WorkspaceProvider";
```

在组件内取 `const { state, dispatch } = useWorkspace();` 与 `const openDrawer = (d: DrawerId) => dispatch({ type: "OPEN_DRAWER", drawer: d });`、`const closeDrawer = () => dispatch({ type: "CLOSE_DRAWER" });`（顶部加 `import type { DrawerId } from "../types";`）。

把 `<AppShell>...</AppShell>` 内的 `<Sidebar/>`、`<ChatPanel/>`、`<Inspector/>` 替换为：

```tsx
      <LearningPanel
        lastChat={chatController.lastChat}
        visitedPhases={state.pedagogyPhases}
        memoryStatus={snapshot.memoryStatus}
      />
      <ChatPanel
        sessionId={chatController.threadId}
        messages={chatController.messages}
        input={ui.input}
        setInput={ui.setInput}
        isSending={chatController.isSending}
        onSubmit={submit}
        onStop={chatController.stop}
        streamRecovery={chatController.streamRecovery}
        onContinueInterruptedReply={chatController.continueInterrupted}
        onRetry={chatController.retry}
        onCopyInterruptedReply={chatController.copyInterrupted}
        onUploadClick={() => fileInputRef.current?.click()}
        onSearchSources={() => ragController.search(activeQuery)}
        isSearching={ragController.isSearching}
        hasSearchQuery={Boolean(activeQuery)}
        onQuickPrompt={ui.setInput}
        lastChat={chatController.lastChat}
        ragEnabled={ui.ragEnabled}
        memoryStatus={snapshot.memoryStatus}
        onOpenDrawer={openDrawer}
      />
      <SlideOver open={state.activeDrawer === "settings"} title="设置" onClose={closeDrawer}>
        <Sidebar
          snapshot={snapshot}
          ragEnabled={ui.ragEnabled}
          ragUploadMode={uploadController.mode}
          setRagUploadMode={uploadController.setMode}
          setRagEnabled={ui.setRagEnabled}
          chatSettings={ui.chatSettings}
          setChatSettings={ui.setChatSettings}
          ragSettings={ui.ragSettings}
          setRagSettings={ui.setRagSettings}
          onSaveSettings={settingsController.save}
          isSavingSettings={settingsController.isSaving}
          onLoadRole={roleController.load}
          roleDetail={roleController.detail}
          keepCurrentRole={ui.keepCurrentRole}
          setKeepCurrentRole={ui.setKeepCurrentRole}
          conversationInstruction={ui.conversationInstruction}
          setConversationInstruction={ui.setConversationInstruction}
          onNewSession={chatController.startNewSession}
          isSending={chatController.isSending}
          refresh={refresh}
          onUploadClick={() => fileInputRef.current?.click()}
          uploadState={uploadController.status}
          lastChat={chatController.lastChat}
        />
      </SlideOver>
      <SlideOver open={state.activeDrawer === "group"} title="群聊" onClose={closeDrawer}>
        <WechatPanel wechat={snapshot.wechat} newsController={newsController} webLookup={webLookupController.result}
          useWebLookup={webLookupController.useInChat} setUseWebLookup={webLookupController.setUseInChat}
          wechatInput={groupController.input} setWechatInput={groupController.setInput}
          newsQuery={ui.newsQuery} setNewsQuery={ui.setNewsQuery} readArticles={ui.readArticles} setReadArticles={ui.setReadArticles}
          sessionId={groupThreadId} onOpening={groupController.opening} onReset={groupController.reset}
          onMarkRead={groupController.markRead} onSendWechat={groupController.send} onStopWechat={groupController.stop}
          onLookupNews={webLookupController.lookup} isWechatBusy={groupController.isBusy} error={groupController.error}
          isNewsBusy={webLookupController.isBusy} />
      </SlideOver>
      <SlideOver open={state.activeDrawer === "news"} title="新闻" onClose={closeDrawer}>
        <NewsWorkspace newsController={newsController} />
      </SlideOver>
      <SlideOver open={state.activeDrawer === "tools"} title="工具" onClose={closeDrawer}>
        <ToolPanel toolCount={snapshot.tools.length} run={toolController.run} error={toolController.error}
          previewTool={toolController.preview} callTool={toolController.call} isPreviewing={toolController.isPreviewing}
          isCalling={toolController.isCalling} canCall={toolController.canCall} callBlockedReason={toolController.callBlockedReason}
          invocationLabel={toolController.invocationLabel} />
      </SlideOver>
      <SlideOver open={state.activeDrawer === "sessions"} title="会话历史" onClose={closeDrawer}>
        <SessionsPanel sessions={snapshot.sessions} activeSessionId={chatController.threadId} isSending={chatController.isSending}
          onRestore={chatController.restoreSession} onArchive={chatController.archiveCurrentSession} />
      </SlideOver>
      <SlideOver open={state.activeDrawer === "memory"} title="学习记忆" onClose={closeDrawer}>
        <MemoryPanel memoryStatus={snapshot.memoryStatus} controller={memoryController} />
      </SlideOver>
```

顶部加导入：`import { WechatPanel } from "../features/wechat-workspace/WechatPanel";`、`import { NewsWorkspace } from "../features/news-workspace/NewsWorkspace";`、`import { ToolPanel } from "../features/tools/ToolPanel";`、`import { SessionsPanel } from "../features/sessions/SessionsPanel";`、`import { MemoryPanel } from "../features/learning-memory/MemoryPanel";`、`import { Sidebar } from "../layout/Sidebar";`。删除 `Inspector` 导入（不再直接用）。`NewsWorkspace`/`ToolPanel` 等若所需 prop 与原 `Inspector` 调用有差异，照原 `Inspector.tsx` 的传参补齐。

- [ ] **Step 5: 运行前端全量单测** `npx vitest run` -> 全绿（含新 reducer/Controller 测试）

- [ ] **Step 6: 提交** `git add frontend/src/app workspaceReducer.ts frontend/src/app/WorkspaceView.tsx frontend/src/features/chat/chatController.ts frontend/src/features/learning/LearningPanel.tsx && git commit -m "feat(workspace): wire two-column layout with LearningPanel and slide-over drawers"`

---

## Task 12: styles.css - 两列网格 + 抽屉 + 学习卡片 + 证据 chip

**Files:** Modify `frontend/src/styles.css`

- [ ] **Step 1: 改主网格** 把 `.app-shell`（约 53-59 行）的 `grid-template-columns: 268px minmax(420px, 1fr) 372px;` 改为：

```css
  grid-template-columns: 340px 1fr;
```

- [ ] **Step 2: 追加样式** 在 `styles.css` 末尾追加：

```css
/* === 学习伴侣栏 === */
.learning-panel {
  border-right: 1px solid var(--border);
  background: var(--surface);
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.learning-header { display: flex; align-items: center; gap: 8px; color: var(--accent-strong); font-weight: 600; }
.learning-card { border: 1px solid var(--border); border-radius: 10px; background: var(--surface); padding: 12px; }
.learning-card .card-label { display: flex; align-items: center; gap: 6px; color: var(--muted); font-size: 12px; margin-bottom: 6px; }
.learning-card p { margin: 0; font-size: 14px; line-height: 1.5; }
.learning-card .muted { color: var(--muted); }
.objective-card p { font-weight: 600; color: var(--text); }
.phase-current { font-weight: 600; color: var(--accent-strong); }
.phase-trail { margin: 6px 0 0; padding-left: 16px; font-size: 12px; color: var(--muted); }
.phase-trail li.is-current { color: var(--accent); font-weight: 600; }
.mastery-row { display: flex; align-items: center; gap: 12px; }
.mastery-ring { width: 56px; height: 56px; border-radius: 50%; display: grid; place-items: center; font-size: 12px; font-weight: 600; color: var(--text); }
.mastery-ring span { background: var(--surface); width: 42px; height: 42px; border-radius: 50%; display: grid; place-items: center; }
.mastery-meta { display: flex; flex-direction: column; gap: 2px; font-size: 12px; color: var(--muted); }
.gap-card.has-gap { border-color: var(--amber); background: #fff8ef; }
.gap-card.has-gap p { color: var(--amber); font-weight: 600; }
.confirmed-list { margin: 0; padding-left: 18px; font-size: 13px; }
.confirmed-list li { color: var(--success); }
.move-badge { display: inline-block; background: var(--surface-strong); color: var(--accent-strong); border: 1px solid var(--border); border-radius: 999px; padding: 2px 10px; font-size: 12px; }
.memory-snapshot summary { cursor: pointer; color: var(--muted); font-size: 13px; }

/* === SlideOver 抽屉 === */
.slide-over-root { position: fixed; inset: 0; z-index: 50; display: flex; justify-content: flex-end; }
.slide-over-backdrop { position: absolute; inset: 0; background: rgba(23,32,36,0.32); border: 0; cursor: pointer; }
.slide-over { position: relative; width: 420px; max-width: 90vw; background: var(--surface); box-shadow: var(--shadow); display: flex; flex-direction: column; animation: slide-in 0.18s ease-out; }
@keyframes slide-in { from { transform: translateX(24px); opacity: 0; } to { transform: none; opacity: 1; } }
.slide-over-header { display: flex; align-items: center; justify-content: space-between; padding: 14px 16px; border-bottom: 1px solid var(--border); }
.slide-over-body { overflow-y: auto; padding: 16px; }

/* === 证据轨迹 === */
.evidence-trail { margin-top: 8px; border-top: 1px dashed var(--border); padding-top: 6px; }
.evidence-toggle { display: flex; align-items: center; gap: 8px; background: none; border: 0; cursor: pointer; color: var(--muted); font-size: 12px; padding: 2px 0; }
.evidence-toggle .web-flag, .evidence-toggle .cite-flag { background: var(--surface-strong); border: 1px solid var(--border); border-radius: 999px; padding: 1px 8px; }
.evidence-detail { margin-top: 8px; display: flex; flex-direction: column; gap: 8px; }
.evidence-error { color: var(--danger); font-size: 12px; }
.web-call-card { border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; background: var(--surface); }
.web-call-head { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--accent-strong); font-weight: 600; }
.web-result { display: block; font-size: 12px; color: var(--text); margin-top: 4px; }
.web-url { display: block; color: var(--muted); font-size: 11px; word-break: break-all; }
.web-preview { margin: 4px 0 0; font-size: 12px; color: var(--muted); }
.citation-list { margin: 0; padding-left: 18px; font-size: 12px; }
.cite-src { color: var(--muted); }
.cite-score { color: var(--accent); margin-left: 6px; }
.dock-divider { width: 1px; height: 18px; background: var(--border); display: inline-block; margin: 0 4px; }

/* === 响应式 === */
@media (max-width: 1100px) {
  .app-shell { grid-template-columns: 1fr; }
  .learning-panel { display: none; }
}
```

- [ ] **Step 3: 提交** `git add frontend/src/styles.css && git commit -m "style: two-column grid, slide-over, learning cards, evidence trail, responsive"`

---

## Task 13: 全量回归 + 构建

**Files:** 无修改，仅验证

- [ ] **Step 1: 后端全量** `$env:PYTHONPATH="."; python -m pytest -q` -> 全绿（含 Task 1 新增 2 个）

- [ ] **Step 2: 前端全量单测** `npx vitest run` -> 全绿（含 Task 3/5/6 新增）

- [ ] **Step 3: 前端构建** 在 `frontend/` 下 `npm run build` -> 构建成功（TS 类型检查通过，验证 Task 2/8/9/10/11 类型一致）

- [ ] **Step 4: 手动冒烟** `npm run dev`（frontend）+ 后端 `uvicorn src.api.app:app`，发一条学习请求，确认：学习面板显示目标/阶段/掌握度/缺口；最新 assistant 消息下"证据轨迹"可展开看 RAG 引用与联网调用；dock 按钮能开关各抽屉；设置抽屉内原 Sidebar 功能可用。

- [ ] **Step 5: 修复任何回归** 若构建/测试报错，按报错修类型或导入，不扩大改动范围。

---

## 自审（writing-plans self-review）

**Spec 覆盖：**
- 教学法可视化 -> Task 5（标签/掌握度）+ Task 9（LearningPanel）+ Task 11（pedagogyPhases）✅
- 联网工具可追溯 -> Task 6（summarizeWebCalls）+ Task 7（EvidenceTrail）+ Task 8（evidence 填充）✅
- Inspector 信息架构重排 -> Task 11（面板降级为 SlideOver）+ Task 4（SlideOver）✅
- 决策点 a（ChatResponse.pedagogy）-> Task 1 ✅
- 历史轮教学法动作 -> Task 6 evidenceFromSessionTurns + Task 8 恢复回填 ✅
- 强类型 -> Task 2 ✅

**已知边界（非占位符，刻意取舍）：**
- 历史轮仅回填教学法动作（pedagogy_snapshot），逐轮 RAG/联网仅在最新轮可得（session detail turns 不暴露 route_snapshot/rag_snapshot）。若日后要历史轮完整证据，扩展 session detail API 暴露逐轮 route/rag 即可，前端 `evidenceFromSessionTurns` 同步扩展。
- `MasteryRing` 派生为启发式（确认点 + 阶段进度），可在有真实掌握度评估数据后校准。
- `RoadmapPanel`（静态迁移信息）不再渲染；如需保留，加一个"关于"抽屉。

**类型一致性：** `TurnEvidence`/`PedagogySummary`/`WebToolCall`/`DrawerId`/`LearningState` 在 Task 2 定义，后续 Task 5/6/7/8/9/11 引用名一致；`evidenceFromResponse`/`evidenceFromSessionTurns`/`summarizeWebCalls`/`buildCitations` 在 Task 6 定义，Task 7/8 引用一致；`moveLabel`/`protocolLabel`/`deriveMastery`/`phaseTrail` 在 Task 5 定义，Task 7/9/11 引用一致。

---

## 执行交接

计划已保存至 `docs/superpowers/plans/2026-07-12-learning-workspace-redesign.md`。两种执行方式：

1. **Subagent-Driven（推荐）** - 每个 Task 派一个全新 subagent 执行，任务间两段审查，迭代快。
2. **Inline Execution** - 在当前会话用 executing-plans 批量执行，带检查点。

用户已说明：今天先产出计划，明天执行全部工作。明天开始时按上面任一方式推进即可。
