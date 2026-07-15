import { act, create } from "react-test-renderer";
import { describe, expect, it, vi } from "vitest";

import type { WorkflowRunDetail, WorkflowRunSummary } from "../../types";
import {
  TimelinePanel,
  workflowDurationLabel,
  workflowLabel,
} from "./TimelinePanel";

describe("TimelinePanel user-facing presentation", () => {
  it("keeps run and step identifiers internal while preserving selection", () => {
    const onSelectRun = vi.fn<(runId: string) => void>();
    const run: WorkflowRunSummary = {
      run_id: "run-secret-id",
      workflow_name: "internal_workflow_code",
      status: "succeeded",
      started_at: "2026-07-15T08:00:00Z",
      completed_at: "2026-07-15T08:00:01Z",
      elapsed_ms: 1234,
      event_count: 1,
    };
    const selectedRun: WorkflowRunDetail = {
      ...run,
      events: [
        {
          run_id: "run-secret-id",
          step_id: "step-secret-id",
          event_type: "route_internal_code",
          status: "succeeded",
          workflow_name: "internal_workflow_code",
          message: "读取学习资料",
          data: {},
          elapsed_ms: 120,
          created_at: "2026-07-15T08:00:00Z",
          error: "",
        },
      ],
    };

    let renderer!: ReturnType<typeof create>;
    act(() => {
      renderer = create(
        <TimelinePanel
          runs={[run]}
          selectedRun={selectedRun}
          loadingRunId=""
          onSelectRun={onSelectRun}
        />
      );
    });

    const serialized = JSON.stringify(renderer.toJSON());
    expect(serialized).toContain("任务运行");
    expect(serialized).toContain("读取学习资料");
    expect(serialized).toContain("成功");
    expect(serialized).not.toContain("run-secret-id");
    expect(serialized).not.toContain("step-secret-id");
    expect(serialized).not.toContain("route_internal_code");
    expect(serialized).not.toContain("internal_workflow_code");

    act(() => renderer.root.findByType("button").props.onClick());
    expect(onSelectRun).toHaveBeenCalledWith("run-secret-id");

    act(() => renderer.unmount());
  });

  it("uses readable workflow and duration labels", () => {
    expect(workflowLabel("learning_closure")).toBe("学习整理");
    expect(workflowLabel("unknown_internal_code")).toBe("任务运行");
    expect(workflowDurationLabel(850)).toBe("850 毫秒");
    expect(workflowDurationLabel(1250)).toBe("1.3 秒");
  });
});
