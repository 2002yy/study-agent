// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ChatMessage } from "../../types";
import { seedMessages } from "./chatHistory";
import { buildChatTranscript, canExportChatTranscript, downloadChatTranscript } from "./chatTranscriptExport";

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("chat transcript export", () => {
  it("exports only the loaded conversation, not system prompts, a welcome hint or a queued draft", () => {
    const messages: ChatMessage[] = [
      { role: "system", content: "hidden runtime instructions" },
      seedMessages[0],
      { role: "user", content: "为什么有彩虹？" },
      { role: "user", content: "待发送的补充", researchQueued: { runId: "r", id: "q", status: "pending" } },
      { role: "assistant", content: "折射和色散。\n\n参考：[资料](https://example.org)", turnStatus: "completed" },
    ];
    const result = buildChatTranscript(messages);
    expect(result).toContain("## 你\n\n为什么有彩虹？");
    expect(result).toContain("## 助手\n\n折射和色散。\n\n参考：[资料](https://example.org)");
    expect(result).not.toContain("hidden runtime instructions");
    expect(result).not.toContain("待发送的补充");
    expect(result).not.toContain(seedMessages[0].content);
    expect(result).toContain("附件、资料原文、交互组件状态及服务端历史备份不包含在内");
  });

  it("replaces the interactive wire payload with the same readable copy used by the chat UI", () => {
    const result = buildChatTranscript([{ role: "assistant", content: '说明\n\n```study-ui\n{"type":"chart","title":"对比","points":[{"label":"甲","value":2},{"label":"乙","value":3}]}\n```' }]);
    expect(result).toContain("说明");
    expect(result).toContain("对比");
    expect(result).not.toContain('"type":"chart"');
  });

  it("preserves a recoverable partial reply exactly once, and labels interrupted messages", () => {
    const recovered = { question: "原问题", reply: "未完的回答" };
    const missing = buildChatTranscript([{ role: "user", content: "原问题" }], recovered)!;
    expect(missing).toContain("## 未完成任务（待恢复）");
    expect(missing).toContain("未完的回答");
    const visible = buildChatTranscript([
      { role: "user", content: "原问题", turnStatus: "interrupted" },
      { role: "assistant", content: "未完的回答\n\n生成中断：网络错误", turnStatus: "interrupted" },
    ], recovered)!;
    expect(visible).toContain("## 助手（未完成）");
    expect(visible.match(/未完的回答/g)).toHaveLength(1);
    expect(visible).not.toContain("## 未完成任务（待恢复）");
  });

  it("refuses an empty, system-only, or pending-queue-only export", () => {
    expect(buildChatTranscript([])).toBeNull();
    expect(buildChatTranscript([seedMessages[0], { role: "system", content: "private" }])).toBeNull();
    expect(buildChatTranscript([{ role: "user", content: "待发送", researchQueued: { runId: "r", id: "q", status: "pending" } }])).toBeNull();
    expect(buildChatTranscript([], { question: "问题", reply: "" })).toContain("（尚无回答内容）");
    expect(canExportChatTranscript([seedMessages[0], { role: "system", content: "private" }])).toBe(false);
    expect(canExportChatTranscript([{ role: "user", content: "问题" }])).toBe(true);
    expect(canExportChatTranscript([], { question: "问题", reply: "" })).toBe(true);
  });

  it("downloads a local Markdown blob with a timestamp-only filename and revokes its URL", () => {
    vi.useFakeTimers();
    const createUrl = vi.fn((_blob: Blob) => "blob:local-only");
    const revokeUrl = vi.fn();
    const originalCreate = URL.createObjectURL;
    const originalRevoke = URL.revokeObjectURL;
    URL.createObjectURL = createUrl;
    URL.revokeObjectURL = revokeUrl;
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      expect(this.download).toBe("study-agent-chat-20261119123456.md");
      expect(this.href).toBe("blob:local-only");
      expect(document.body.contains(this)).toBe(true);
    });
    try {
      downloadChatTranscript("# 导出内容", new Date("2026-11-19T12:34:56Z"));
      expect(createUrl).toHaveBeenCalledOnce();
      expect(createUrl.mock.calls[0][0]).toBeInstanceOf(Blob);
      expect(click).toHaveBeenCalledOnce();
      expect(document.querySelector("a[download]")).toBeNull();
      vi.advanceTimersByTime(1000);
      expect(revokeUrl).toHaveBeenCalledWith("blob:local-only");
    } finally {
      URL.createObjectURL = originalCreate;
      URL.revokeObjectURL = originalRevoke;
    }
  });
});
