// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { InteractiveComputation } from "./InteractiveComputation";
import { chartSeries, isStale, provenanceCopy, renderableTable, type ComputationPayload } from "./computation";

afterEach(cleanup);

function payload(overrides: Partial<ComputationPayload> = {}): ComputationPayload {
  return {
    schema_version: "1",
    run_id: "run-1",
    tool_run_id: "tool-1",
    status: "succeeded",
    input_revision: 2,
    source_refs: ["source-1"],
    engine: "deterministic",
    result: { columns: ["方案", "耗时"], rows: [["A", 12.5], ["B", 9.8]], unit: "seconds" },
    ...overrides,
  };
}

describe("computation payload validation", () => {
  it("only renders server-validated succeeded tables", () => {
    expect(renderableTable(payload())).not.toBeNull();
    expect(renderableTable(payload({ status: "failed", result: {} }))).toBeNull();
    expect(renderableTable(payload({ result: { columns: ["a"], rows: [["x", "y"]] } as never }))).toBeNull();
    expect(renderableTable(payload({ result: { columns: ["a"], rows: [[Number.NaN]] } as never }))).toBeNull();
  });

  it("derives chart series from the label/value columns", () => {
    expect(chartSeries(renderableTable(payload())!)).toEqual([{ label: "A", value: 12.5 }, { label: "B", value: 9.8 }]);
    expect(isStale(payload({ status: "superseded", superseded_by_revision: 3 }))).toBe(true);
    expect(provenanceCopy(payload())).toContain("版本 v2");
    expect(provenanceCopy(payload())).toContain("source-1");
  });
});

describe("InteractiveComputation", () => {
  it("switches between bar, line and table views", () => {
    const { container } = render(<InteractiveComputation payload={payload()} />);
    expect(container.querySelector(".computation-bars")).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "折线图" }));
    expect(container.querySelector(".computation-line")).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "数据表" }));
    const table = container.querySelector(".computation-table");
    expect(table).not.toBeNull();
    expect(table!.textContent).toContain("12.5");
    expect(screen.getByText(/seconds|版本 v2/)).toBeTruthy();
  });

  it("refuses to render an unvalidated result", () => {
    render(<InteractiveComputation payload={payload({ status: "succeeded", result: { columns: ["a"], rows: [["x", "y"]] } as never })} />);
    expect(screen.getByText("计算结果未通过校验，已拒绝展示。")).toBeVisible();
  });

  it("marks a superseded result stale without overwriting the record", () => {
    render(<InteractiveComputation payload={payload({ status: "superseded", superseded_by_revision: 3 })} />);
    expect(screen.getByText(/已过期：输入已更新至 v3/)).toBeVisible();
  });

  it("asks the server to recompute when a parameter changes", () => {
    const onRecompute = vi.fn();
    render(<InteractiveComputation payload={payload()} parameters={[{ name: "concurrency", value: 4 }]} onRecompute={onRecompute} />);
    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "8" } });
    fireEvent.click(screen.getByRole("button", { name: "按新参数重新计算" }));
    expect(onRecompute).toHaveBeenCalledWith({ concurrency: 8 });
  });
});
