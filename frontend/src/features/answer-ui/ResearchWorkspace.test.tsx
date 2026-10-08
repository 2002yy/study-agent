// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render as baseRender, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ResearchWorkspace } from "./ResearchWorkspace";
import { researchFixture } from "./researchPresentation.fixture";

function render(...args: Parameters<typeof baseRender>) {
  const view = baseRender(...args);
  fireEvent.click(screen.getByRole("button", { name: "研究资料" }));
  fireEvent.click(screen.getByText("技术详情与证据关联"));
  document.querySelectorAll(".research-tier-list > details > summary").forEach(summary => fireEvent.click(summary));
  return view;
}

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers(); });
describe("research workspace data binding", () => {
  it("renders equal-version authoritative reads and ignores late partial SSE", async () => {
    const event = researchFixture(); event.snapshot_kind = "run"; event.turn_updated_at = null;
    event.blocks[0].read_count = 0;
    const turn = researchFixture(); turn.blocks[0].read_count = 1; turn.watch = false;
    turn.blocks[0].research_status = "completed";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(turn))));
    const view = render(<ResearchWorkspace sessionId="s1" turnId="t1" initial={event} />);
    await screen.findByText(/读取成功 1/);
    view.rerender(<ResearchWorkspace sessionId="s1" turnId="t1" initial={{ ...event }} />);
    expect(screen.getByText(/读取成功 1/)).toBeInTheDocument();
    expect(screen.getAllByText("研究结束")[0]).toBeInTheDocument();
  });
  it("pauses hidden-tab reads and stops polling a missing turn", async () => {
    vi.useFakeTimers();
    const request = vi.fn().mockResolvedValue(new Response("", { status: 404 }));
    vi.stubGlobal("fetch", request);
    const visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    render(<ResearchWorkspace sessionId="s1" turnId="t1" initial={researchFixture()} />);
    expect(request).not.toHaveBeenCalled();
    visibility.mockReturnValue("visible");
    await vi.advanceTimersByTimeAsync(5000);
    expect(request).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(10000);
    expect(request).toHaveBeenCalledTimes(1);
    visibility.mockRestore();
  });
  it("uses the unknown labels for prototype-shaped status and phase names", () => {
    const s = researchFixture(); s.blocks[0].research_status = "constructor";
    s.blocks[0].research_phase = "toString";
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})));
    render(<ResearchWorkspace sessionId="s1" turnId="t1" initial={s} />);
    expect(screen.getAllByText("状态未识别")[0]).toBeInTheDocument();
    expect(screen.getByText(/未提供阶段细节/)).toBeInTheDocument();
  });
  it("separates unread sources, unknown counts and Deep audit from approved answers", async () => {
    const s = researchFixture(); s.audit_status = "audited"; s.audit_integrity = "valid";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(s))));
    render(<ResearchWorkspace sessionId="s1" turnId="t1" initial={s} />);
    expect(screen.getByText(/读取成功 —/)).toBeInTheDocument();
    expect(screen.getAllByText(/读取状态未提供/)[0]).toBeInTheDocument();
    expect(screen.getAllByText(/尚未获准发布/)[0]).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "官方资料" })[0]).toHaveAttribute("href", "https://example.com/a");
    fireEvent.click(screen.getByRole("button", { name: "刷新研究状态" }));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("slider")).not.toBeInTheDocument();
  });
  it("refuses a different turn and aborts pending reads on unmount", async () => {
    const wrong = researchFixture(); wrong.turn_id = "other";
    const request = vi.fn().mockResolvedValue(new Response(JSON.stringify(wrong)));
    vi.stubGlobal("fetch", request);
    const view = render(<ResearchWorkspace sessionId="s1" turnId="t1" initial={researchFixture()} />);
    await screen.findByText(/连接暂不可用/);
    view.unmount();
    expect(request.mock.calls[0][1].signal.aborted).toBe(true);
  });
  it("does not restart a pending restore request on every SSE revision", async () => {
    const request = vi.fn().mockReturnValue(new Promise(() => {}));
    vi.stubGlobal("fetch", request);
    const first = researchFixture();
    const view = render(<ResearchWorkspace sessionId="s1" turnId="t1" initial={first} />);
    const next = researchFixture(); next.blocks[0].revision = 3;
    view.rerender(<ResearchWorkspace sessionId="s1" turnId="t1" initial={next} />);
    expect(request).toHaveBeenCalledTimes(1);
    expect(request.mock.calls[0][1].signal.aborted).toBe(false);
    expect(screen.getByText(/研究版本 3/)).toBeInTheDocument();
    view.rerender(<ResearchWorkspace sessionId="s2" turnId="t2" initial={first} />);
    expect(request.mock.calls[0][1].signal.aborted).toBe(true);
    expect(screen.queryByRole("region", { name: "研究工作区" })).toBeNull();
  });
  it("resumes stopped restoration when a later SSE starts unfinished work", async () => {
    const stopped = researchFixture(); stopped.watch = false;
    stopped.blocks[0].research_status = "completed";
    const request = vi.fn().mockResolvedValue(new Response(JSON.stringify(stopped)));
    vi.stubGlobal("fetch", request);
    const view = render(<ResearchWorkspace sessionId="s1" turnId="t1" initial={stopped} />);
    await waitFor(() => expect(request.mock.calls[0][1].signal.aborted).toBe(false));
    await waitFor(() => expect(screen.getAllByText("研究结束")[0]).toBeInTheDocument());
    // Wait for the successful restore to settle before the next independent event.
    await new Promise(resolve => setTimeout(resolve, 0));
    const started = researchFixture(); started.snapshot_kind = "run"; started.turn_updated_at = null;
    started.blocks[0].revision = 3;
    view.rerender(<ResearchWorkspace sessionId="s1" turnId="t1" initial={started} />);
    await waitFor(() => expect(request).toHaveBeenCalledTimes(2));
  });
});

describe("conversation first research disclosure", () => {
  it("keeps diagnostic machinery out of the default answer view", () => {
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})));
    baseRender(<ResearchWorkspace sessionId="s1" turnId="t1" initial={researchFixture()} />);
    expect(screen.getByText("研究进行中")).toBeVisible();
    expect(screen.queryByText("Lookup · 快速查找")).toBeNull();
    expect(screen.queryByText(/读取成功/)).toBeNull();
    expect(screen.getByRole("button", { name: "研究资料" })).toHaveAttribute("aria-expanded", "false");
  });
  it("opens a requested citation without granting publication authority", async () => {
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})));
    const snapshot = researchFixture(); snapshot.audit_status = "audited"; snapshot.audit_integrity = "valid";
    baseRender(<ResearchWorkspace sessionId="s1" turnId="t1" initial={snapshot} sourceRequest={{url: "https://example.com/a", key: 1}}/>);
    expect(await screen.findByRole("complementary", { name: "研究资料" })).toBeVisible();
    expect(screen.getAllByText(/尚未获准发布/).length).toBeGreaterThan(0);
    expect(document.querySelector("[data-source-url]")).toHaveClass("is-selected");
    fireEvent.click(screen.getByRole("button", {name: "关闭研究资料"}));
    expect(screen.getByRole("button", {name: "研究资料"})).toHaveFocus();
  });
});
