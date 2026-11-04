import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useMemo } from "react";
import { AnswerCardView } from "../features/answer-ui/AnswerCardView";
import { ConsentImage } from "./ConsentImage";
import { splitAnswerContent } from "../features/answer-ui/answerUiProtocol";

export function MarkdownMessage({ content, interactive = false, streaming = false, generation, onDraft, onRestoreBase, sessionId }: {
  content: string; interactive?: boolean; streaming?: boolean; generation?: unknown; onDraft?: (prompt: string) => void;
  onRestoreBase?: (target: { id: string; revision: number; title: string }) => void;
  sessionId?: string;
}) {
  const status = generation && typeof generation === "object" && "status" in generation ? generation.status : "unknown";
  const notices: Record<string, string> = {
    output_limit: "本次回答达到输出长度上限，内容可能尚未完整。",
    timeout: "生成请求超时，已保留收到的内容。",
    connection_error: "连接中断，已保留收到的内容。",
    cancelled: "已停止生成，已保留收到的内容。",
    provider_blocked: "模型服务未能提供完整内容。",
  };
  const notice = typeof status === "string" ? notices[status] : undefined;
  const parts = useMemo(() => interactive ? splitAnswerContent(content, streaming)
    : [{ kind: "markdown" as const, content, key: 0 }], [content, interactive, streaming]);
  return (
    <div className="markdown-message">
      {interactive && !streaming && notice ? <p role="status">{notice}</p> : null}
      {parts.map(part => part.kind === "card"
        ? <AnswerCardView key={`${part.key}:${JSON.stringify(part.card)}`} card={part.card} onDraft={onDraft} onRestoreBase={onRestoreBase} sessionId={sessionId} />
        : part.kind === "pending" ? <div className="answer-pending" role="status" key={part.key}>正在准备交互内容…</div>
        : part.kind === "html-source" ? <section className="answer-card" key={part.key} aria-label="尚未运行的网页源码">
          <p>这段内容是网页源码，尚未作为交互界面运行。</p>
          <button type="button" disabled={!onDraft} onClick={() => onDraft?.("请把刚才的网页源码生成为可运行的交互界面，保留核心功能与参数。使用 study-ui 代码块中的 interactive JSON，html 字段放精简、自包含且完整的页面；不要再返回普通 html 代码块。")}>生成可运行界面</button>
          <details className="interactive-source"><summary>查看网页源码</summary><pre>{part.content}</pre></details>
        </section>
        : part.kind === "incomplete" ? <section className="answer-card" key={part.key} aria-label="未完成的交互内容"><p>{status === "completed" ? "模型已结束回答，但交互格式不完整，暂时无法运行。" : "交互内容未完整生成，暂时无法运行。前面的文字仍然可以阅读。"}</p><button type="button" disabled={!onDraft} onClick={() => onDraft?.("刚才的交互界面没有完整生成，请给出精简、自包含的完整版本，保留原来的核心功能与参数。")}>生成完整界面</button><details className="interactive-source"><summary>查看未完成内容</summary><pre>{part.content}</pre></details></section>
        : (
      <ReactMarkdown
        key={part.key}
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ ...props }) => <a {...props} target="_blank" rel="noreferrer noopener" />,
          img: ({ src, alt }) => <ConsentImage src={src} alt={alt} />
        }}
      >
        {part.content}
      </ReactMarkdown>
      ))}
      {interactive && !streaming && status === "output_limit" && !parts.some(part => part.kind === "incomplete" || part.kind === "html-source") && onDraft
        ? <button type="button" onClick={() => onDraft("请只用文字继续刚才未完成的说明，避免重复已完成的内容。")}>继续未完成的说明</button> : null}
    </div>
  );
}
