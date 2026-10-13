import { describe, expect, it } from "vitest";
import type { ChatResearchApproach, ChatResearchProgress } from "../../types";
import {
  approachFocus,
  approachSummary,
  isResearchActive,
  mergeApproach,
  mergeResearchProgress,
} from "./researchApproach";

function approach(overrides: Partial<ChatResearchApproach> = {}): ChatResearchApproach {
  return {
    status: "ready",
    summary: "我会比较功能覆盖与兼容性。",
    focus: ["功能覆盖", "兼容性"],
    origin: "model_plan",
    sequence: 1,
    mode: "standard",
    ...overrides,
  };
}

function progress(overrides: Partial<ChatResearchProgress> = {}): ChatResearchProgress {
  return {
    run_id: "research_1",
    status: "running",
    stage: "searching",
    provider_status: "ok",
    stop_reason: "",
    error: "",
    query_attempt_count: 1,
    selected_source_count: 2,
    version: 3,
    ...overrides,
  };
}

describe("researchApproach merge", () => {
  it("carries the opening forward when an event omits it", () => {
    const previous = progress({ approach: approach() });
    const merged = mergeResearchProgress(previous, progress({ version: 4 }));
    expect(merged?.approach?.summary).toBe("我会比较功能覆盖与兼容性。");
  });

  it("ignores a stale (lower-sequence) approach", () => {
    const previous = progress({ approach: approach({ sequence: 2, summary: "新的方向。" }) });
    const merged = mergeResearchProgress(
      previous,
      progress({ approach: approach({ sequence: 1, summary: "旧的方向。" }) }),
    );
    expect(merged?.approach?.summary).toBe("新的方向。");
  });

  it("accepts a newer sequence (mode upgrade / direction update)", () => {
    const previous = progress({ approach: approach({ sequence: 1 }) });
    const merged = mergeResearchProgress(
      previous,
      progress({
        approach: approach({ sequence: 2, origin: "direction_update", summary: "继续核对自动化接口。" }),
      }),
    );
    expect(merged?.approach?.origin).toBe("direction_update");
    expect(merged?.approach?.sequence).toBe(2);
  });

  it("does not erase a known opening when incoming has none and previous is null", () => {
    expect(mergeApproach(null, undefined)).toBeNull();
  });

  it("does not inherit a previous run's opening when a new run arrives (forward isolation)", () => {
    const previous = progress({ run_id: "run_A", approach: approach({ sequence: 3, summary: "A 的方向。" }) });
    const merged = mergeResearchProgress(previous, progress({ run_id: "run_B", version: 1 }));
    expect(merged?.run_id).toBe("run_B");
    expect(merged?.approach).toBeNull();
  });

  it("documents the reverse out-of-order boundary (late old-run event)", () => {
    // The pure helper cannot know which run is *currently active*: given a
    // later-arriving event it adopts that event's run. Run-level protection for
    // a stale cross-run event therefore lives in the controller's `isCurrent()`
    // operation guard, not here. This test pins the boundary honestly rather
    // than claiming protection the helper does not provide.
    const previous = progress({ run_id: "run_B", approach: approach({ sequence: 1, summary: "B 的方向。" }) });
    const merged = mergeResearchProgress(
      previous,
      progress({ run_id: "run_A", approach: approach({ sequence: 9, summary: "A 的迟到方向。" }) }),
    );
    expect(merged?.run_id).toBe("run_A");
  });
});

describe("researchApproach view", () => {
  it("exposes the summary only when ready", () => {
    expect(approachSummary(progress({ approach: approach() }))).toBe("我会比较功能覆盖与兼容性。");
    expect(approachSummary(progress({ approach: approach({ status: "pending", summary: "" }) }))).toBeNull();
    expect(approachSummary(progress({}))).toBeNull();
  });

  it("exposes focus only when ready", () => {
    expect(approachFocus(progress({ approach: approach() }))).toEqual(["功能覆盖", "兼容性"]);
    expect(approachFocus(progress({ approach: approach({ status: "pending" }) }))).toEqual([]);
  });

  it("treats cancelled as not active (never a completed opening)", () => {
    expect(isResearchActive(progress({ status: "cancelled" }))).toBe(false);
    expect(isResearchActive(progress({ status: "running" }))).toBe(true);
    expect(isResearchActive(progress({ status: "pending" }))).toBe(true);
  });
});
