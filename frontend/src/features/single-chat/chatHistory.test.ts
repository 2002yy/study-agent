import { describe, expect, it } from "vitest";
import { sanitizeSingleChatMessages, seedMessages } from "./chatHistory";
import type { ChatMessage } from "../../types";

describe("sanitizeSingleChatMessages", () => {
  it("removes legacy wechat and news workspace messages from single chat history", () => {
    const saved: ChatMessage[] = [
      seedMessages[0],
      { role: "user", content: "讲一下 RAG", avatarRole: "user" },
      { role: "assistant", content: "RAG 是检索增强生成。", avatarRole: "nahida" },
      { role: "user", content: "[群聊] 大家怎么看？", avatarRole: "user" },
      { role: "assistant", content: "【三月七】我觉得可以先拆状态。", avatarRole: "auto" },
      { role: "user", content: "[联网检索] AI 新闻", avatarRole: "user" },
      { role: "assistant", content: "新闻摘要内容", avatarRole: "nahida" },
      { role: "user", content: "[联网搜索] AI 新闻", avatarRole: "user" },
      { role: "assistant", content: "已找到 3 条联网来源。", avatarRole: "nahida" }
    ];

    expect(sanitizeSingleChatMessages(saved)).toEqual([
      seedMessages[0],
      { role: "user", content: "讲一下 RAG", avatarRole: "user" },
      { role: "assistant", content: "RAG 是检索增强生成。", avatarRole: "nahida" }
    ]);
  });
});
