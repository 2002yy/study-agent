import { Loader2, Search, Send, Upload } from "lucide-react";
import type { FormEvent } from "react";
import { MarkdownMessage } from "../../components/MarkdownMessage";
import { RoleAvatar } from "../../components/RoleAvatar";
import type { ChatMessage, ChatResponse } from "../../types";
import { roleLabel } from "../roles/roleCatalog";

const quickPrompts = [
  "继续上次学习，先给我一个下一步建议",
  "分析当前 Study Agent 架构，并列出最该推进的三件事",
  "根据本地资料解释 RAG 工作流时间线的作用"
];

export function ChatPanel({
  messages,
  input,
  setInput,
  isSending,
  onSubmit,
  onUploadClick,
  onSearchSources,
  isSearching,
  onQuickPrompt,
  lastChat,
  ragEnabled
}: {
  messages: ChatMessage[];
  input: string;
  setInput: (value: string) => void;
  isSending: boolean;
  onSubmit: (event: FormEvent) => void;
  onUploadClick: () => void;
  onSearchSources: () => void;
  isSearching: boolean;
  onQuickPrompt: (value: string) => void;
  lastChat: ChatResponse | null;
  ragEnabled: boolean;
}) {
  return (
    <main className="chat-panel" id="chat">
      <header className="topbar">
        <div>
          <h1>学习工作台</h1>
          <p>提问、检索本地资料、检查执行链路，再决定哪些内容写入记忆。</p>
          <div className="topbar-meta">
            <span>RAG {ragEnabled ? "已启用" : "未启用"}</span>
            <span>路由 {lastChat ? "已生成" : "等待提问"}</span>
            <span>Session {lastChat?.session_id ?? "未开始"}</span>
          </div>
        </div>
        <div className="topbar-actions">
          <button className="icon-button" onClick={onUploadClick} type="button" title="上传资料">
            <Upload size={17} />
          </button>
          <button className="icon-button" onClick={onSearchSources} type="button" title="检索来源">
            {isSearching ? <Loader2 className="spin" size={17} /> : <Search size={17} />}
          </button>
        </div>
      </header>

      <section className="conversation" aria-label="Conversation">
        <div className="home-brief">
          <div>
            <h2>继续学习</h2>
            <p>PRD 的方向是把 Streamlit 的学习闭环迁回 React，同时保留工具、来源和工作流审计。</p>
          </div>
          <div className="quick-grid">
            {quickPrompts.map((prompt) => (
              <button key={prompt} onClick={() => onQuickPrompt(prompt)} type="button">
                {prompt}
              </button>
            ))}
          </div>
        </div>
        {messages.map((message, index) => {
          const avatarRole = message.avatarRole ?? (message.role === "user" ? "user" : "auto");
          const label = message.role === "user" ? "你" : roleLabel(avatarRole);
          return (
            <article className={`message ${message.role}`} key={`${message.role}-${index}`}>
              <RoleAvatar fallback={message.role === "user" ? "user" : "assistant"} roleId={avatarRole} />
              <div className="message-body">
                <span>{label}</span>
                <MarkdownMessage content={message.content} />
              </div>
            </article>
          );
        })}
      </section>

      <form className="composer" onSubmit={onSubmit}>
        <textarea
          aria-label="Message"
          onChange={(event) => setInput(event.target.value)}
          placeholder="输入你的问题，或让本地资料帮你解释一个概念..."
          value={input}
        />
        <button className="send-button" disabled={isSending || !input.trim()} type="submit">
          {isSending ? <Loader2 className="spin" size={17} /> : <Send size={17} />}
          {isSending ? "发送中" : "发送"}
        </button>
      </form>
    </main>
  );
}
