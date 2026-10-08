import { describe, expect, it } from "vitest";
import { answerCopyText, packAnswerUiContext, parseAnswerCard, safeImageUrl, splitAnswerContent } from "./answerUiProtocol";

const plot = JSON.stringify({ type: "plot", title: "函数", fn: "quadratic", a: 1, b: 0 });
const block = (raw: string) => `\`\`\`study-ui\n${raw}\n\`\`\``;
describe("answer UI wire format", () => {
  it("copies readable descriptions and original values while preserving ordinary code examples", () => {
    expect(answerCopyText("结论\n\n" + block(plot))).toContain("y = 1x²");
    expect(answerCopyText(block(plot))).not.toContain('"type"');
    expect(answerCopyText("```ts\nconst x = 1;\n```")).toBe("```ts\nconst x = 1;\n```");
  });
  it("shows text immediately and waits for a complete, closed component", () => {
    expect(splitAnswerContent(`先看结论\n\n\`\`\`study-ui\n${plot}`, true).map(p => p.kind)).toEqual(["markdown", "pending"]);
    expect(splitAnswerContent(`先看结论\n\n${block(plot)}\n\n继续解释`, true).map(p => p.kind)).toEqual(["markdown", "card", "markdown"]);
    expect(splitAnswerContent(`\`\`\`study-ui\n${plot}`, false)[0].kind).toBe("markdown");
  });
  it("does not interpret nested code examples as executable UI", () => {
    expect(splitAnswerContent(`\`\`\`\`markdown\n${block(plot)}\n\`\`\`\``).every(p => p.kind === "markdown")).toBe(true);
    expect(splitAnswerContent(block("broken"))[0].kind).toBe("markdown");
    expect(splitAnswerContent(Array.from({ length: 6 }, () => block(plot)).join("\n")).filter(p => p.kind === "card")).toHaveLength(4);
  });
  it("rejects scripts, unsupported formulas, out-of-bounds coordinates and oversized data", () => {
    for (const c of [
      { type: "html", title: "bad", html: "<script>bad()</script>" },
      { type: "plot", title: "bad", fn: "eval", a: 1, b: 0 },
      { type: "plot", title: "bad", fn: "linear", a: 500, b: 0 },
      { type: "map", title: "bad", points: [{ label: "bad", lat: 91, lon: 0 }] },
      { type: "chart", title: "bad", points: Array.from({ length: 41 }, () => ({ label: "x", value: 1 })) },
    ]) expect(parseAnswerCard(JSON.stringify(c))).toBeNull();
    expect(parseAnswerCard(" ".repeat(24001))).toBeNull();
  });
  it("accepts only safe image URLs", () => {
    for (const url of ["javascript:alert(1)", "data:image/svg+xml,bad", "file:///tmp/p.png", "//example.com/a.png", "/assets/../settings", "https://user:secret@example.com/a", "https://example.com/\\bad"]) expect(safeImageUrl(url)).toBe(false);
    expect(safeImageUrl("/assets/avatars/nahida.png")).toBe(true);
    expect(safeImageUrl("https://example.com/a.png")).toBe(true);
  });
  it("strips unknown fields and frames UI instructions separately from durable preferences", () => {
    expect(parseAnswerCard(JSON.stringify({ type: "plot", title: "函数", fn: "quadratic", a: 1, b: 0, onClick: "bad()" }))).not.toHaveProperty("onClick");
    const encoded = packAnswerUiContext(" 用户手写要求 ", "原有示例状态");
    const payload = JSON.parse(encoded.replace("__STUDY_AGENT_TURN_CONTEXT_V1__", ""));
    expect(payload.conversation_instruction).toBe(" 用户手写要求 ");
    expect(payload.turn_context).toContain("study-ui");
    expect(payload.turn_context).toContain("原有示例状态");
    expect(payload.turn_context.length).toBeLessThan(12000);
  });
});
