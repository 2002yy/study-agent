import type { ChatMessage } from "../../types";

export const SESSION_STORAGE_KEY = "study-agent-react-session";

export const seedMessages: ChatMessage[] = [
  {
    role: "assistant",
    avatarRole: "nahida",
    transient: true,
    content:
      "本地学习工作台已就绪。你可以提问、上传资料、查看引用来源，并在右侧检查工具调用与工作流状态。"
  }
];

export const POLLUTED_HISTORY_PREFIXES = ["[群聊]", "[联网检索]", "[联网搜索]"];

export function sanitizeSingleChatMessages(savedMessages: ChatMessage[] | undefined): ChatMessage[] {
  if (!savedMessages?.length) {
    return seedMessages;
  }
  const cleaned: ChatMessage[] = [];
  let skipNextAssistant = false;
  for (const message of savedMessages) {
    const isPollutedUserMessage =
      message.role === "user" && POLLUTED_HISTORY_PREFIXES.some((prefix) => message.content.trim().startsWith(prefix));
    if (isPollutedUserMessage) {
      skipNextAssistant = true;
      continue;
    }
    if (skipNextAssistant && message.role === "assistant") {
      skipNextAssistant = false;
      continue;
    }
    skipNextAssistant = false;
    cleaned.push(markTransientWelcome(message));
  }
  return cleaned.length ? cleaned : seedMessages;
}

export function toChatHistoryPayload(messages: ChatMessage[]): ChatMessage[] {
  return messages.filter((message) => message.role !== "system" && !message.transient);
}

function markTransientWelcome(message: ChatMessage): ChatMessage {
  if (
    message.role === "assistant" &&
    message.content === seedMessages[0].content &&
    (message.avatarRole === "nahida" || !message.avatarRole)
  ) {
    return { ...message, avatarRole: "nahida", transient: true };
  }
  return message;
}
