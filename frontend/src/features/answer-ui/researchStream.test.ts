import { afterEach, expect, it, vi } from "vitest";
import { sendChatStream } from "../../api";
import { researchFixture } from "./researchPresentation.fixture";

const options = { sessionId: "s1", turnId: "t1", ragEnabled: false,
  chatSettings: { selectedRole: "auto", selectedMode: "auto", selectedModel: "flash", relationshipMode: "standard", contextMode: "" },
  ragSettings: { retrievalMode: "lexical" as const, topK: 3, minScore: 0, chatTopK: 3 } };
const event = (name: string, data: unknown) => `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`;
function response(body: string) {
  return new Response(new ReadableStream({ start(c) { c.enqueue(new TextEncoder().encode(body)); c.close(); } }), { headers: { "Content-Type": "text/event-stream" } });
}
afterEach(() => { vi.unstubAllGlobals(); });
it("delivers observational sources before any answer token and ignores a foreign turn", async () => {
  const snapshot = researchFixture(); const foreign = { ...snapshot, turn_id: "other" };
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(event("research_presentation", foreign)
    + event("research_presentation", snapshot) + event("token", { text: "已获准显示的正文" })
    + event("done", { session_id: "s1", turn_id: "t1", reply: "已获准显示的正文" }))));
  const order: string[] = [];
  await sendChatStream("q", [], options, { onResearchPresentation: s => { expect(s.publication_authority).toBe(false); order.push("source"); }, onToken: () => order.push("text") });
  expect(order).toEqual(["source", "text"]);
});
it("does not mistake an EOF after progress or partial tokens for a completed answer", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(event("research_presentation", researchFixture()) + event("token", { text: "partial" }))));
  await expect(sendChatStream("q", [], options)).rejects.toThrow(/连接已中断/);
});
