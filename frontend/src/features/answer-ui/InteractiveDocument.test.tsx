// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MarkdownMessage } from "../../components/MarkdownMessage";
import { answerCopyText, packAnswerUiContext, parseAnswerCard, splitAnswerContent } from "./answerUiProtocol";
import { makeInteractiveDocument, stateText } from "./interactiveRuntime";

afterEach(cleanup);
const card = { type: "interactive", id: "orders", revision: 1, title: "库存探索", summary: "演示库存与锁定数量的关系。", html: "<label>库存<input id='stock' value='37'></label><script>window.studyUI.setState({stock:37})</script>" };
const block = (value: unknown) => "```study-ui\n" + JSON.stringify(value) + "\n```";

describe("generated interactive documents", () => {
  it("accepts a bounded complete document, strips unknown fields and keeps old types restricted", () => {
    expect(parseAnswerCard(JSON.stringify({ ...card, onSend: "secret()" }))).toEqual(card);
    for (const change of [{ id: "../bad" }, { revision: 0 }, { revision: 1.5 }, { summary: "" }, { html: "x".repeat(60001) }, { type: "html" }]) expect(parseAnswerCard(JSON.stringify({ ...card, ...change }))).toBeNull();
    expect(parseAnswerCard(JSON.stringify({ ...card, html: "x".repeat(30000) }))).not.toBeNull();
    expect(splitAnswerContent(block(card).slice(0, -3), true).slice(-1)[0]?.kind).toBe("pending");
    expect(splitAnswerContent(block(card).slice(0, -3), false).slice(-1)[0]?.kind).toBe("incomplete");
    expect(answerCopyText(block(card))).toContain("演示库存与锁定数量的关系");
    expect(answerCopyText(block(card))).not.toContain("<script>");
  });

  it("never activates a document in user or ordinary Markdown content", () => {
    const { container } = render(<MarkdownMessage content={block(card)} />);
    expect(container.querySelector("iframe")).toBeNull();
    expect(container.textContent).toContain("window.studyUI");
  });

  it("renders saved interfaces without requiring the secure-context UUID API", () => {
    const random = vi.spyOn(crypto, "randomUUID").mockImplementation(() => { throw new Error("unavailable outside a secure context"); });
    try {
      const view = render(<MarkdownMessage interactive content={block(card)} />);
      expect(view.container.querySelector("iframe")).not.toBeNull();
      expect(random).not.toHaveBeenCalled();
    } finally { random.mockRestore(); }
  });

  it("offers a readable recovery for a truncated document without running partial code", () => {
    const onDraft = vi.fn();
    const content = "可售库存等于总量减去锁定。\n" + block(card).slice(0, -35);
    const view = render(<MarkdownMessage interactive content={content} onDraft={onDraft} />);
    expect(view.container.querySelector("iframe")).toBeNull();
    expect(screen.getByText("可售库存等于总量减去锁定。")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "生成完整界面" }));
    expect(onDraft).toHaveBeenCalledWith(expect.stringContaining("自包含的完整版本"));
    expect(answerCopyText(content)).not.toContain("<script>");
  });

  it("reports the exact identity when the learner continues from an older version", () => {
    const onRestoreBase = vi.fn();
    render(<MarkdownMessage interactive content={block({ ...card, revision: 2 })} onRestoreBase={onRestoreBase} />);

    fireEvent.click(screen.getByRole("button", { name: "以此版本为基础继续" }));

    expect(onRestoreBase).toHaveBeenCalledWith({ id: "orders", revision: 2, title: "库存探索" });
  });

  it("parses inertly and puts policy before model content, removing navigation markup", () => {
    const doc = makeInteractiveDocument('<meta http-equiv="refresh" content="0;url=https://example.com"><base href="https://example.com"><iframe src="/settings"></iframe><button onclick="bad()">go</button><a href="https://example.com">link</a><svg><use href="#shape" /></svg><script>const safe = 1;</script>', "test-channel");
    expect(doc.indexOf("Content-Security-Policy")).toBeLessThan(doc.indexOf("const safe"));
    for (const value of ['http-equiv="refresh"', "<base", "<iframe", "onclick=", "https://example.com"]) expect(doc).not.toContain(value);
    expect(doc).toContain('href=\\"#shape\\"');
    expect(doc).toContain("connect-src 'none'");
    expect(doc).not.toContain("allow-same-origin");
  });

  it("ignores foreign/oversized bridge messages and preserves state across appended streamed prose", () => {
    const onDraft = vi.fn();
    const view = render(<MarkdownMessage interactive streaming content={block(card)} onDraft={onDraft} />);
    const frame = view.container.querySelector("iframe")!;
    expect(frame).toHaveAttribute("sandbox", "allow-scripts");
    const channel = /const channel = "([^"]+)"/.exec(frame.srcdoc)![1];
    const send = (source: Window | null, origin: string, value: unknown) => fireEvent(window, new MessageEvent("message", { source, origin, data: { channel, type: "state", value } }));
    send(window, "null", { stolen: true });
    send(frame.contentWindow, "https://example.com", { stolen: true });
    send(frame.contentWindow, "null", { stock: 42 });
    send(frame.contentWindow, "null", { oversized: "x".repeat(4001) });
    view.rerender(<MarkdownMessage interactive streaming content={block(card) + "\n\n接下来试试改变锁定数量。"} onDraft={onDraft} />);
    expect(view.container.querySelector("iframe")).toBe(frame);
    fireEvent.click(screen.getByRole("button", { name: "带着当前状态继续问" }));
    expect(onDraft).toHaveBeenLastCalledWith(expect.stringContaining('"stock":42'));
    expect(onDraft.mock.calls.slice(-1)[0][0]).not.toContain("stolen");
    fireEvent.click(screen.getByRole("button", { name: "停止" }));
    expect(view.container.querySelector("iframe")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "带着当前状态继续问" }));
    expect(onDraft).toHaveBeenLastCalledWith(expect.stringContaining('"stock":42'));
    fireEvent.click(screen.getByRole("button", { name: "运行" }));
    fireEvent.click(screen.getByRole("button", { name: "带着当前状态继续问" }));
    expect(onDraft).toHaveBeenLastCalledWith(expect.stringContaining("尚未提供状态"));
  });

  it("keeps runtime errors outside the generated canvas and drafts a repair without sending", () => {
    const onDraft = vi.fn();
    const view = render(<MarkdownMessage interactive content={block(card)} onDraft={onDraft} />);
    const frame = view.container.querySelector("iframe")!;
    const channel = /const channel = "([^"]+)"/.exec(frame.srcdoc)![1];
    fireEvent(window, new MessageEvent("message", { source: frame.contentWindow, origin: "null", data: { channel, type: "error", value: "draw is not defined" } }));
    expect(screen.getByRole("alert")).toHaveTextContent("draw is not defined");
    fireEvent.click(screen.getByRole("button", { name: "请模型修复" }));
    expect(onDraft).toHaveBeenCalledTimes(1);
    expect(onDraft).toHaveBeenCalledWith(expect.stringContaining("请修复这个界面"));
  });

  it("keeps prompt capability and readable fallback within the existing transient envelope", () => {
    const packed = packAnswerUiContext("我的要求", "当前课程");
    const payload = JSON.parse(packed.replace("__STUDY_AGENT_TURN_CONTEXT_V1__", ""));
    expect(payload.conversation_instruction).toBe("我的要求");
    expect(payload.turn_context).toContain('"type":"interactive"');
    expect(payload.turn_context).toContain("window.studyUI.setState");
    expect(payload.turn_context).toContain("当前课程");
    expect(payload.turn_context.length).toBeLessThan(12000);
    expect(stateText(null)).toBeNull();
    expect(stateText([])).toBeNull();
  });
});
