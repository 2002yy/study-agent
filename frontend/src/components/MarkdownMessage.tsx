import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useMemo } from "react";
import { AnswerCardView } from "../features/answer-ui/AnswerCardView";
import { ConsentImage } from "./ConsentImage";
import { splitAnswerContent } from "../features/answer-ui/answerUiProtocol";

export function MarkdownMessage({ content, interactive = false, streaming = false, onDraft }: {
  content: string; interactive?: boolean; streaming?: boolean; onDraft?: (prompt: string) => void;
}) {
  const parts = useMemo(() => interactive ? splitAnswerContent(content, streaming)
    : [{ kind: "markdown" as const, content, key: 0 }], [content, interactive, streaming]);
  return (
    <div className="markdown-message">
      {parts.map(part => part.kind === "card"
        ? <AnswerCardView key={`${part.key}:${JSON.stringify(part.card)}`} card={part.card} onDraft={onDraft} />
        : part.kind === "pending" ? <div className="answer-pending" role="status" key={part.key}>正在准备交互内容…</div>
        : part.kind === "incomplete" ? <section className="answer-card" key={part.key} aria-label="未完成的交互内容"><p>交互内容未完整生成，暂时无法运行。前面的文字仍然可以阅读。</p><button type="button" disabled={!onDraft} onClick={() => onDraft?.("刚才的交互界面没有完整生成，请给出自包含的完整版本，保留原来的功能与参数。")}>生成完整界面</button><details className="interactive-source"><summary>查看未完成内容</summary><pre>{part.content}</pre></details></section>
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
    </div>
  );
}
