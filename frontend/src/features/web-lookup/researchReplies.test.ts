import { describe, expect, it } from "vitest";

import type { ChatResearchReply } from "../../types";
import {
  mergeResearchReplies,
  replyHeading,
  replyIsProvisional,
  replyStatusNote,
} from "./researchReplies";

const reply = (overrides: Partial<ChatResearchReply> = {}): ChatResearchReply => ({
  schema: "steering-reply-v1",
  reply_id: "web_lookup_run1:steer:s1",
  scope: "steering",
  steering_id: "s1",
  turn_id: "turn1",
  lifecycle: "open",
  stage: "analysis",
  content_version: 2,
  stale: false,
  analysis_state: "ready",
  focus: "",
  reason: "",
  questions: [],
  text: "评估重点变化：比较标准扩展到脚本控制",
  citations: [],
  updated_at: "2026-10-18T00:00:00+00:00",
  ...overrides,
});

describe("provisional reply merging", () => {
  it("accepts a strictly newer content version", () => {
    const merged = mergeResearchReplies([reply()], [reply({ content_version: 3, text: "newer" })]);
    expect(merged[0].text).toBe("newer");
  });

  it("never lets a late or duplicated event overwrite newer content", () => {
    const merged = mergeResearchReplies([reply({ content_version: 3, text: "newer" })], [
      reply({ content_version: 2, text: "older" }),
      reply({ content_version: 3, text: "same version, other text" }),
    ]);
    expect(merged[0].text).toBe("newer");
  });

  it("freezes a terminal reply against any later event", () => {
    const merged = mergeResearchReplies([reply({ lifecycle: "closed", content_version: 4 })], [
      reply({ lifecycle: "open", content_version: 9, text: "reopened" }),
    ]);
    expect(merged[0].lifecycle).toBe("closed");
    expect(merged[0].content_version).toBe(4);
  });

  it("accepts an authoritative terminal state at the same content version", () => {
    const merged = mergeResearchReplies([reply({ lifecycle: "open", content_version: 4 })], [
      reply({ lifecycle: "closed", content_version: 4, lifecycle_closed_by: "run_terminal" }),
    ]);
    expect(merged[0].lifecycle).toBe("closed");
  });

  it("states that an accepted requirement is not in the result, with the next step", () => {
    const note = replyStatusNote(
      reply({ lifecycle: "closed", lifecycle_closed_by: "run_terminal", analysis_state: "not_generated", result_state: "not_included" }),
    );
    // Stronger and more honest than "no analysis": the answer does not cover it.
    expect(note).toContain("未包含此要求");
    expect(note).toContain("排队下一轮");
    // A supplement that *was* executed but produced no analysis keeps the other note.
    expect(replyStatusNote(reply({ analysis_state: "not_generated" }))).toBe("本轮未生成模型分析");
  });

  it("never displays an unproven close as frozen, in either path", () => {
    const claimed = reply({ lifecycle: "closed", content_version: 4 });
    // First restore: nothing to compare against, and still not frozen.
    const restored = mergeResearchReplies([], [claimed]);
    expect(restored[0].lifecycle).toBe("open");
    expect(replyStatusNote(restored[0])).toBeNull();
    // Merge against a known reply: the bare claim changes nothing at all.
    const merged = mergeResearchReplies([reply({ content_version: 1, text: "kept" })], [claimed]);
    expect(merged[0].lifecycle).toBe("open");
    expect(merged[0].text).toBe("kept");
    // An authoritative freeze is still honoured in both paths.
    const frozen = reply({ lifecycle: "closed", lifecycle_closed_by: "run_terminal", content_version: 4 });
    expect(mergeResearchReplies([], [frozen])[0].lifecycle).toBe("closed");
    expect(mergeResearchReplies([reply({ content_version: 1 })], [frozen])[0].lifecycle).toBe("closed");
  });

  it("accepts a legitimate open -> superseded invalidation", () => {
    const merged = mergeResearchReplies([reply({ lifecycle: "open", content_version: 4 })], [
      reply({ lifecycle: "superseded", content_version: 5, stale: true, text: "已被取代" }),
    ]);
    expect(merged[0].lifecycle).toBe("superseded");
    expect(merged[0].text).toBe("已被取代");
    expect(replyStatusNote(merged[0])).toBe("已被后续纠正取代");
  });

  it("still refuses an older snapshot, including one claiming superseded", () => {
    const merged = mergeResearchReplies([reply({ lifecycle: "open", content_version: 9, text: "current" })], [
      reply({ lifecycle: "superseded", content_version: 3, text: "old" }),
    ]);
    expect(merged[0].lifecycle).toBe("open");
    expect(merged[0].text).toBe("current");
  });

  it("keeps a frozen reply frozen even against a superseded event", () => {
    const merged = mergeResearchReplies(
      [reply({ lifecycle: "closed", lifecycle_closed_by: "run_terminal", content_version: 6 })],
      [reply({ lifecycle: "superseded", content_version: 7 })],
    );
    expect(merged[0].lifecycle).toBe("closed");
  });

  it("ignores a writer merely claiming the reply is closed", () => {
    const merged = mergeResearchReplies([reply({ lifecycle: "open", content_version: 4 })], [
      reply({ lifecycle: "closed", content_version: 9, text: "claimed" }),
    ]);
    expect(merged[0].lifecycle).toBe("open");
    expect(merged[0].text).not.toBe("claimed");
  });

  it("keeps every reply and ignores empty text", () => {
    const merged = mergeResearchReplies(
      [reply()],
      [reply({ reply_id: "web_lookup_run1:research", scope: "research", text: "阶段性判断" }),
       reply({ reply_id: "empty", text: "" })],
    );
    expect(merged.map(item => item.reply_id)).toEqual([
      "web_lookup_run1:research",
      "web_lookup_run1:steer:s1",
    ]);
  });

  it("labels an acknowledgement as a receipt, never as analysis", () => {
    expect(replyHeading(reply({ stage: "acknowledgement" }))).toBe("已收到补充");
    expect(replyHeading(reply())).toBe("初步分析");
    expect(replyHeading(reply({ scope: "research" }))).toBe("阶段性判断");
    expect(replyIsProvisional(reply({ stage: "evidence_update" }))).toBe(true);
    expect(replyIsProvisional(reply())).toBe(false);
  });

  it("states why a judgment no longer covers the task", () => {
    expect(replyStatusNote(reply({ stale: true }))).toBe("尚未覆盖后续新增的条件");
    expect(replyStatusNote(reply({ lifecycle: "superseded" }))).toBe("已被后续纠正取代");
    expect(replyStatusNote(reply({ lifecycle: "closed" }))).toBe("研究已结束");
    // A missing analysis is reported as state, without erasing a sourced judgment.
    expect(replyStatusNote(reply({ analysis_state: "not_generated" }))).toBe("本轮未生成模型分析");
    expect(replyStatusNote(reply())).toBeNull();
  });
});
