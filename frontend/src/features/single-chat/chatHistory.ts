import type { ChatMessage, WorkspaceState } from "../../types";

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

export const POLLUTED_HISTORY_PREFIXES = ["[群聊]", "[联网检索]", "[联网搜索]", "[继续生成指令]"];

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

const WORKSPACE_STATE_DEFAULTS: WorkspaceState = {
  singleChatMessages: seedMessages,
  chatSettings: { selectedRole: "auto", selectedMode: "auto", selectedModel: "auto", relationshipMode: "standard", contextMode: "light" },
  ragSettings: { retrievalMode: "hybrid", topK: 5, minScore: 0.01, chatTopK: 3 },
  ragEnabled: true,
  keepCurrentRole: false,
  conversationInstruction: "",
};

type LegacyWorkspaceState = Partial<WorkspaceState> & {
  sessionId?: string;
};

export function buildWorkspaceState(partial: LegacyWorkspaceState): WorkspaceState {
  const { sessionId, ...rest } = partial;
  return {
    ...WORKSPACE_STATE_DEFAULTS,
    ...rest,
    singleChatSessionId: partial.singleChatSessionId ?? sessionId,
  };
}

export function serializeWorkspaceState(state: WorkspaceState): string {
  return JSON.stringify(state);
}

export function deserializeWorkspaceState(raw: string | null): WorkspaceState | null {
  if (!raw) return null;
  try {
    return buildWorkspaceState(JSON.parse(raw));
  } catch {
    return null;
  }
}

export function buildContinuationHistory(
  messages: ChatMessage[],
  recovery: { question: string; reply: string }
): ChatMessage[] {
  return messages.map((message, index) => {
    const previousMessage = messages[index - 1];
    const nextMessage = messages[index + 1];
    if (!message.transient) {
      return message;
    }
    if (
      message.role === "assistant" &&
      previousMessage?.role === "user" &&
      previousMessage.content === recovery.question
    ) {
      const { transient: _transient, ...rest } = message;
      return { ...rest, content: recovery.reply };
    }
    if (
      message.role === "user" &&
      message.content === recovery.question &&
      nextMessage?.role === "assistant" &&
      nextMessage.transient
    ) {
      const { transient: _transient, ...rest } = message;
      return rest;
    }
    return message;
  });
}
