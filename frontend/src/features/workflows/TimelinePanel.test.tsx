// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
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

    const { container } = render(
      <TimelinePanel
        runs={[run]}
        selectedRun={selectedRun}
        loadingRunId=""
        onSelectRun={onSelectRun}
      />
    );

    const text = container.textContent ?? "";
    expect(text).toContain("任务运行");
    expect(text).toContain("读取学习资料");
    expect(text).toContain("成功");
    expect(text).not.toContain("run-secret-id");
    expect(text).not.toContain("step-secret-id");
    expect(text).not.toContain("route_internal_code");
    expect(text).not.toContain("internal_workflow_code");

    fireEvent.click(screen.getAllByRole("button")[0]);
    expect(onSelectRun).toHaveBeenCalledWith("run-secret-id");
  });

  it("uses readable workflow and duration labels", () => {
    expect(workflowLabel("learning_closure")).toBe("学习整理");
    expect(workflowLabel("unknown_internal_code")).toBe("任务运行");
    expect(workflowDurationLabel(850)).toBe("850 毫秒");
    expect(workflowDurationLabel(1250)).toBe("1.3 秒");
  });
});
