import type { ChatMessage } from "../../types";
import { answerCopyText } from "../answer-ui/answerUiProtocol";
import { seedMessages } from "./chatHistory";

type InterruptedTask = { question: string; reply: string } | null;

function isExportableMessage(message: ChatMessage): boolean {
  return message.role !== "system" && !message.researchQueued && Boolean(message.content.trim())
    && !(message.transient && message.role === "assistant" && message.content === seedMessages[0].content);
}

/** Keep the toolbar check cheap during streaming; format text only on click. */
export function canExportChatTranscript(messages: ChatMessage[], recovery: InterruptedTask = null): boolean {
  return messages.some(isExportableMessage) || Boolean(recovery);
}

/** Export the currently loaded, user-visible conversation, not a server backup. */
export function buildChatTranscript(messages: ChatMessage[], recovery: InterruptedTask = null): string | null {
  const entries = messages
    .filter(isExportableMessage)
    .map(message => ({
      role: message.role,
      content: message.role === "assistant" ? answerCopyText(message.content).trim() : message.content.trim(),
      interrupted: message.turnStatus === "interrupted" || message.turnStatus === "cancelled",
    }))
    .filter(message => message.content);

  const partial = recovery?.reply.trim() ?? "";
  const recoveryAlreadyVisible = partial && entries.some(message => message.role === "assistant" && message.content.includes(partial));
  const recoveryBlock = recovery && !recoveryAlreadyVisible
    ? `## 未完成任务（待恢复）\n\n**原问题**\n\n${recovery.question.trim()}\n\n**部分回答**\n\n${partial || "（尚无回答内容）"}`
    : "";

  if (!entries.length && !recoveryBlock) return null;
  const sections = entries.map(message =>
    `## ${message.role === "user" ? "你" : "助手"}${message.interrupted ? "（未完成）" : ""}\n\n${message.content}`,
  );
  if (recoveryBlock) sections.push(recoveryBlock);
  return [
    "# Study Agent 对话文本",
    "> 仅导出当前已加载的对话正文。附件、资料原文、交互组件状态及服务端历史备份不包含在内。",
    ...sections,
  ].join("\n\n---\n\n") + "\n";
}

/** Download only on an explicit user gesture; no request to a remote service. */
export function downloadChatTranscript(content: string, now = new Date()): void {
  const filename = `study-agent-chat-${now.toISOString().slice(0, 19).replace(/[-:T]/g, "")}.md`;
  const url = URL.createObjectURL(new Blob([content], { type: "text/markdown;charset=utf-8" }));
  try {
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.hidden = true;
    document.body.append(anchor);
    try { anchor.click(); } finally { anchor.remove(); }
  } finally {
    // Let the browser start reading the blob before releasing its URL.
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}
