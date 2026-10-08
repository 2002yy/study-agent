import { describe, expect, it } from "vitest";
import { panelBounds } from "./PanelResizeHandle";

describe("panel width limits", () => {
  it("leaves both reading and chat usable when widening the sidebar in a narrow desktop", () => {
    const available = 1045;
    const sidebar = panelBounds("sidebar", available, true);
    expect(sidebar.min).toBeGreaterThanOrEqual(180);
    expect(available - sidebar.max).toBeGreaterThanOrEqual(736);
    const reading = panelBounds("reading", available - sidebar.max - 16, true);
    expect(reading.min).toBeGreaterThanOrEqual(360);
    expect(available - sidebar.max - 16 - reading.max).toBeGreaterThanOrEqual(360);
  });
  it("allows more navigation space in conversation mode while retaining a readable conversation", () => {
    const available = 760;
    expect(available - panelBounds("sidebar", available, false).max).toBeGreaterThanOrEqual(400);
  });
  it("keeps limits ordered when embedded in a smaller available space", () => {
    const bounds = panelBounds("reading", 600, true);
    expect(bounds.min).toBeLessThanOrEqual(bounds.max);
    expect(bounds.min).toBeGreaterThan(0);
    expect(bounds.max).toBeLessThan(600);
  });
});
