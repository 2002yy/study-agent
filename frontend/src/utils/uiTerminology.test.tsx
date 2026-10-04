// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ApiSnapshot, ChatResponse } from "../types";
import { LearningPanel } from "../features/learning/LearningPanel";
import { LearningStrip } from "../features/learning/LearningStripBase";
import type { LearningResumeResponse } from "../features/learning/learningResumeApi";
import { EvidenceTrail } from "../features/evidence/EvidenceTrail";
import { SourcesPanel } from "../features/rag/SourcesPanel";
import { ChatResearchRecovery } from "../features/web-lookup/ChatResearchRecovery";
import { SettingsPanel, CHAT_SETTINGS_DEFAULTS, RAG_SETTINGS_DEFAULTS } from "../features/settings/SettingsPanel";
import { GlobalNotices } from "../layout/GlobalNotices";
import { LearningClosureReview } from "../features/learning-memory/LearningClosureReview";
import type { LearningClosureRunResponse } from "../features/learning-memory/closureTypes";
import { roleLabel } from "../features/roles/roleCatalog";
import { translateStatus } from "./format";
import { humanizeUiError, uiStatusLabel, uiReasonLabel, scoreLabel, researchStepLabel } from "./uiLabels";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });
const unknown = "totally_new_internal_status";
const forbidden = /\b(?:Claims?|Goal|Hypothesis|UnderstandingEvidence|ResumeContext|Flash|Pro)\b|Evidence Gate|legacy_fallback|learning_state|confirmed_points|Primary Evidence|Supporting Evidence|Primary NextStep|legacy candidate|provider=|reason=|score=|Provider[:：]|Study Agent| vs |totally_new_internal_status/;
function cleanText(container: HTMLElement) { expect(container.textContent).not.toMatch(forbidden); }
const resume = {
  source: "durable", status: "active", topic: { title: "主题" }, goal: { objective: "继续学习" },
  claims: [{ claim_id: "c", revision_id: "r", text: "有依据的知识", claim_kind: unknown, scope: unknown,
    understanding_status: unknown, latest_validation: { method: unknown },
    primary_evidence: { path: "src/example.py", commit_sha: "a".repeat(40), start_line: 12, end_line: 20 },
    supporting_evidence: [{ path: "tests/example.py", commit_sha: "b".repeat(40) }] }],
  claim_count: 1, unresolved: [{ text: "待验证的问题" }], next_step: { text: "阅读来源" }, optional_next_steps: [],
} as unknown as LearningResumeResponse;
const rag = {
  status: "found", query: "问题", results: [], debug: {}, attempts: [],
  evidence_snapshot: { schema_version: "evidence-snapshot-v1", refs: [{ id: "e", type: "web_read", title: "来源标题", url: "https://example.com",
    lifecycle_status: "selected", provider_status: unknown, selection_reason: unknown, rejection_reason: unknown, score: 0.82 }] },
  web_tools: { calls: [], error: "Failed to fetch research_runtime" },
} as unknown as ChatResponse["rag"];

describe("product Chinese terminology at rendering boundaries", () => {
  it.each([unknown, "constructor", "toString", "__proto__"])("uses plain Chinese fallbacks for unknown key %s", (key) => {
    expect(uiStatusLabel(key)).toBe("其他状态");
    expect(uiReasonLabel(key)).toBe("原因待确认");
    expect(scoreLabel(key)).toBe("其他评分");
    expect(researchStepLabel(key)).toBe("其他步骤");
    expect(translateStatus(key)).toBe("其他状态");
  });
  it("renders saved learning, source locations and unknown understanding without raw enums", () => {
    const props = { resume, resumeError: "", lastChat: null, visitedPhases: [], memoryStatus: null };
    const panel = render(<LearningPanel {...props} />);
    fireEvent.click(panel.getByText(/补充证据/));
    cleanText(panel.container);
    expect(panel.container).toHaveTextContent("已保存的学习命题");
    expect(panel.container).toHaveTextContent("第 12–20 行");
    expect(panel.container).toHaveTextContent("状态未知");
    panel.unmount();
    const strip = render(<LearningStrip {...props} />);
    cleanText(strip.container);
    expect(strip.container).toHaveTextContent("学习命题 1/1");
  });
  it("renders evidence status and reasons with safe unknown fallbacks", () => {
    const view = render(<EvidenceTrail evidence={{ rag }} />);
    fireEvent.click(view.getByRole("button", { name: /证据轨迹/ }));
    fireEvent.click(view.getByRole("button", { name: "显示诊断详情" }));
    cleanText(view.container);
    expect(view.container).toHaveTextContent("来源状态：其他状态");
    expect(view.container).toHaveTextContent("相关度：0.82");
    expect(view.container).not.toHaveTextContent("Failed to fetch");
  });
  it("renders source diagnostics as labelled scores instead of internal JSON", () => {
    const chat = { rag: { ...rag, debug: { results: [{ rank: 1, title: "来源", score: 0.84,
      score_breakdown: { keyword: 0.72, semantic: 0.91, authority: 0.87, [unknown]: 0.1 } }] } } } as unknown as ChatResponse;
    const view = render(<SourcesPanel lastChat={chat} ragSearch={null} isSearching={false} />);
    fireEvent.click(view.getByRole("tab", { name: "检索诊断" }));
    cleanText(view.container);
    expect(view.container).toHaveTextContent("关键词匹配");
    expect(view.container).toHaveTextContent("语义相关度");
    expect(view.container).toHaveTextContent("来源权威度");
    expect(view.container).toHaveTextContent("其他评分");
  });
  it.each(["search", "read", "assess", "synthesize", unknown])("maps research step %s and evidence validation", (kind) => {
    const view = render(<ChatResearchRecovery run={null} isBusy={false} canRetry={false} canResume={false}
      useInChat={false} onRetry={vi.fn()} onResume={vi.fn()} progress={{ run_id: "r", status: "running",
        stage: "gating", provider_status: unknown, stop_reason: "", error: "", query_attempt_count: 1,
        selected_source_count: 1, version: 1, round: 1, last_step_kind: kind, last_step_text: "核对页面" }} />);
    cleanText(view.container);
    expect(view.container).toHaveTextContent("正在执行证据校验");
  });
  it("keeps settings labels Chinese while option values stay unchanged", () => {
    const view = render(<SettingsPanel snapshot={{ health: { status: "ok" }, runtimeSettings: { settings: {} } } as ApiSnapshot}
      ragEnabled={false} setRagEnabled={vi.fn()} chatSettings={CHAT_SETTINGS_DEFAULTS} setChatSettings={vi.fn()}
      ragSettings={RAG_SETTINGS_DEFAULTS} setRagSettings={vi.fn()} onSaveSettings={vi.fn()} isSavingSettings={false}
      onLoadRole={vi.fn()} roleDetail={null} keepCurrentRole={false} setKeepCurrentRole={vi.fn()}
      conversationInstruction="" setConversationInstruction={vi.fn()} isSending={false} refresh={vi.fn()} lastChat={null} />);
    cleanText(view.container);
    expect(view.container.querySelector('option[value="flash"]')).toHaveTextContent("快速档");
    expect(view.container.querySelector('option[value="pro"]')).toHaveTextContent("高质量档");
    expect(view.container).toHaveTextContent("回车键");
  });
  it("renders learning confirmation without internal evaluation names", () => {
    const run = { status: "preview_ready", committed_snapshot: {}, generated_result: {
      candidates: [], durable_learning_candidate: { source_ref: "source", claim_text: "待确认知识", next_step: "验证理解" },
    } } as unknown as LearningClosureRunResponse;
    const view = render(<LearningClosureReview run={run} memoryRun={null} isCommitting={false}
      onConfirm={vi.fn()} onContinue={vi.fn()} />);
    cleanText(view.container);
    expect(view.container).toHaveTextContent("教学评估");
    expect(view.container).toHaveTextContent("理解验证证据");
  });
  it("keeps raw errors and module keys inside closed developer diagnostics", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const view = render(<GlobalNotices apiError="" operationError="Failed to fetch research_runtime"
      partialErrors={[]} onRetryApi={vi.fn()} onOpenSettings={vi.fn()} onDismissOperationError={vi.fn()} />);
    expect(view.getByText("Failed to fetch research_runtime")).not.toBeVisible();
    expect(view.container).toHaveTextContent("本次操作未能完成，请稍后重试。");
    expect(humanizeUiError(new Error("connection refused"))).not.toContain("connection refused");
    expect(translateStatus(unknown)).toBe("其他状态");
    expect(roleLabel(unknown)).toBe("学习助手");
  });
  it("preserves external titles, user learning text and formal product names verbatim", () => {
    const external = "GitHub DeepSeek Claim Goal Flash Pro";
    const view = render(<LearningPanel resume={{ ...resume, claims: [], goal: { ...resume.goal, objective: external } }}
      resumeError="" lastChat={null} visitedPhases={[]} memoryStatus={null} />);
    expect(view.container).toHaveTextContent(external);
  });
});
