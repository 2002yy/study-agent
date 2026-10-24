import { describe, expect, it } from "vitest";

import type { ChatResearchReply } from "../../types";
import {
  analysisLeadBeforeAnswer,
  firstSubstantiveMs,
  usefulCharsAt,
  usefulTimeline,
  emptyTiming,
  evidenceLeadBeforeAnswer,
  leadBeforeAnswer,
  mergeTiming,
  visibleStageAt,
} from "./researchTiming";

const reply = (overrides: Partial<ChatResearchReply> = {}): ChatResearchReply => ({
  schema: "steering-reply-v1",
  reply_id: "run1:steer:s1",
  scope: "steering",
  steering_id: "s1",
  turn_id: "turn1",
  lifecycle: "open",
  stage: "acknowledgement",
  content_version: 1,
  stale: false,
  analysis_state: "pending",
  focus: "",
  reason: "",
  questions: [],
  text: "已收到这条补充要求",
  citations: [],
  updated_at: "2026-10-18T00:00:00+00:00",
  ...overrides,
});

describe("browser-side reply timing", () => {
  it("records submit, receipt and answer on one clock", () => {
    let state = emptyTiming();
    state = mergeTiming(state, { kind: "submit", at: 100, steeringId: "s1" });
    state = mergeTiming(state, { kind: "replies", at: 420, replies: [reply()] });
    state = mergeTiming(state, { kind: "reply_visible", at: 460, reply: reply() });
    state = mergeTiming(state, { kind: "answer_done", at: 20000 });
    state = mergeTiming(state, { kind: "answer_visible", at: 20120 });

    expect(state.marks[0].submit_ms).toBe(100);
    expect(state.marks[0].receipt_ms).toBe(420);
    // 20000 (answer done) - 460 (first visible receipt)
    expect(leadBeforeAnswer(state, "run1:steer:s1")).toBe(19540);
  });

  it("never moves an earlier observation later on a replayed event", () => {
    let state = emptyTiming();
    state = mergeTiming(state, { kind: "replies", at: 420, replies: [reply()] });
    state = mergeTiming(state, { kind: "reply_visible", at: 460, reply: reply() });
    state = mergeTiming(state, { kind: "reply_visible", at: 900, reply: reply() });
    expect(visibleStageAt(state, "run1:steer:s1", "acknowledgement")).toBe(460);
  });

  it("keys visibility by content version and stage, not by reply alone", () => {
    let state = emptyTiming();
    state = mergeTiming(state, { kind: "reply_visible", at: 500, reply: reply() });
    state = mergeTiming(state, {
      kind: "reply_visible", at: 9000,
      reply: reply({ stage: "analysis", content_version: 2, text: "评估重点变化：…" }),
    });
    state = mergeTiming(state, {
      kind: "reply_visible", at: 15000,
      reply: reply({ stage: "evidence_update", content_version: 3, text: "初步看可行。" }),
    });
    expect(visibleStageAt(state, "run1:steer:s1", "acknowledgement")).toBe(500);
    expect(visibleStageAt(state, "run1:steer:s1", "analysis")).toBe(9000);
    expect(visibleStageAt(state, "run1:steer:s1", "evidence_update")).toBe(15000);
  });

  it("never counts a receipt as the model analysis", () => {
    let state = emptyTiming();
    state = mergeTiming(state, { kind: "reply_visible", at: 500, reply: reply() });
    state = mergeTiming(state, { kind: "answer_visible", at: 21000 });
    // No G1 was ever visible: the lead must be null, not the receipt's lead.
    expect(analysisLeadBeforeAnswer(state, "run1:steer:s1")).toBeNull();
    expect(evidenceLeadBeforeAnswer(state, "run1:steer:s1")).toBeNull();
  });

  it("reports G1 and G2 separately, and G2 without G1 does not fake a G1", () => {
    let state = emptyTiming();
    state = mergeTiming(state, { kind: "reply_visible", at: 500, reply: reply() });
    state = mergeTiming(state, {
      kind: "reply_visible", at: 12000,
      reply: reply({ stage: "evidence_update", content_version: 3, text: "初步看可行。" }),
    });
    state = mergeTiming(state, { kind: "answer_visible", at: 21000 });
    expect(analysisLeadBeforeAnswer(state, "run1:steer:s1")).toBeNull();
    expect(evidenceLeadBeforeAnswer(state, "run1:steer:s1")).toBe(9000);
  });

  it("reports null when the analysis only became visible after the answer", () => {
    let state = emptyTiming();
    state = mergeTiming(state, { kind: "answer_done", at: 500 });
    state = mergeTiming(state, { kind: "answer_visible", at: 510 });
    state = mergeTiming(state, {
      kind: "reply_visible", at: 900,
      reply: reply({ stage: "analysis", content_version: 2 }),
    });
    expect(analysisLeadBeforeAnswer(state, "run1:steer:s1")).toBeNull();
  });

  it("opens a new window per send and refuses the previous answer", () => {
    let state = emptyTiming();
    state = mergeTiming(state, { kind: "run_start", at: 0, turnId: "turn2" });
    state = mergeTiming(state, { kind: "reply_visible", at: 500, reply: reply() });
    state = mergeTiming(state, { kind: "answer_visible", at: 900, turnId: "turn1" });
    // The previous turn's answer is still mounted and still reporting.
    expect(state.answer_visible_ms).toBeNull();
    state = mergeTiming(state, { kind: "answer_visible", at: 21000, turnId: "turn2" });
    expect(state.answer_visible_ms).toBe(21000);
  });

  it("drops every earlier observation when a new send starts", () => {
    let state = emptyTiming();
    state = mergeTiming(state, { kind: "run_start", at: 0, turnId: "turn1" });
    state = mergeTiming(state, { kind: "reply_visible", at: 500, reply: reply() });
    state = mergeTiming(state, { kind: "answer_visible", at: 900, turnId: "turn1" });
    state = mergeTiming(state, { kind: "run_start", at: 5000, turnId: "turn2" });
    expect(state.visible).toHaveLength(0);
    expect(state.answer_visible_ms).toBeNull();
    expect(state.target_turn_id).toBe("turn2");
  });

  it("refuses a late reply event from another run in the same session", () => {
    let state = emptyTiming();
    state = mergeTiming(state, { kind: "run_start", at: 0, turnId: "turn2" });
    // A late SSE from the previous run: receipt and render both refused.
    state = mergeTiming(state, { kind: "replies", at: 100, replies: [reply({ turn_id: "turn1" })] });
    state = mergeTiming(state, {
      kind: "reply_visible", at: 200, reply: reply({ turn_id: "turn1" }),
    });
    expect(state.marks).toHaveLength(0);
    expect(state.visible).toHaveLength(0);
    // The current run's own events are accepted.
    state = mergeTiming(state, { kind: "replies", at: 300, replies: [reply({ turn_id: "turn2" })] });
    state = mergeTiming(state, {
      kind: "reply_visible", at: 400, reply: reply({ turn_id: "turn2" }),
    });
    expect(state.marks).toHaveLength(1);
    expect(state.visible).toHaveLength(1);
  });

  it("observes every event when no window has been opened (restored session)", () => {
    let state = emptyTiming();
    state = mergeTiming(state, { kind: "replies", at: 100, replies: [reply({ turn_id: "turn9" })] });
    state = mergeTiming(state, { kind: "reply_visible", at: 200, reply: reply({ turn_id: "turn9" }) });
    state = mergeTiming(state, { kind: "answer_visible", at: 300, turnId: "turn9" });
    expect(state.marks).toHaveLength(1);
    expect(state.visible).toHaveLength(1);
    expect(state.answer_visible_ms).toBe(300);
  });

  it("counts only substantive text, and says how much existed at 10/20/30s", () => {
    let state = emptyTiming();
    state = mergeTiming(state, { kind: "run_start", at: 0, turnId: "turn1" });
    // A receipt is not substance.
    state = mergeTiming(state, {
      kind: "reply_visible", at: 3_000,
      reply: reply({ stage: "acknowledgement", text: "已收到补充" }),
    });
    state = mergeTiming(state, {
      kind: "reply_visible", at: 8_000,
      reply: reply({ stage: "knowledge", text: "x".repeat(120) }),
    });
    state = mergeTiming(state, {
      kind: "reply_visible", at: 25_000,
      // A different reply (the sourced judgment), so both texts coexist.
      reply: reply({
        reply_id: "run1:research",
        scope: "research",
        steering_id: "",
        stage: "evidence_update",
        text: "y".repeat(80),
      }),
    });

    expect(firstSubstantiveMs(state)).toBe(8_000);
    expect(usefulCharsAt(state, 5_000)).toBe(0);
    expect(usefulCharsAt(state, 10_000)).toBe(120);
    expect(usefulCharsAt(state, 30_000)).toBe(200);
    expect(usefulTimeline(state)).toEqual([
      { at: 10_000, chars: 120 },
      { at: 20_000, chars: 120 },
      { at: 30_000, chars: 200 },
    ]);
  });

  it("states what the answer mark measures", () => {
    expect(emptyTiming().visibility_source).toBe("rendered_after_frame");
  });

  it("tracks a research-level reply separately from its supplement", () => {
    let state = emptyTiming();
    state = mergeTiming(state, {
      kind: "reply_visible", at: 800,
      reply: reply({ reply_id: "run1:research", scope: "research", steering_id: "", stage: "evidence_update" }),
    });
    state = mergeTiming(state, { kind: "answer_visible", at: 3000 });
    expect(evidenceLeadBeforeAnswer(state, "run1:research")).toBe(2200);
    expect(analysisLeadBeforeAnswer(state, "run1:research")).toBeNull();
  });
});
