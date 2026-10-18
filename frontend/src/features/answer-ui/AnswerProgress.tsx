import { Loader2 } from "lucide-react";
import type { ChatResearchProgress } from "../../types";
import { approachFocus, approachSummary, isResearchActive } from "../web-lookup/researchApproach";

const stages: Record<string, string> = {
  planned: "正在规划查找范围", searching: "正在搜索资料", assessing: "正在筛选来源",
  reading: "正在阅读来源", synthesizing: "正在整理证据", gating: "正在核对答案与来源",
};

/**
 * The single, conversation-attached research status entry.
 *
 * Research progress belongs to the conversation timeline, not to a floating
 * debug bar, so this component is the only place that renders live and terminal
 * research state.  While this entry is on screen the standalone recovery
 * surface (`ChatResearchRecovery`) suppresses its duplicate status.
 *
 * Everything here is display-only: it never feeds the answer text or the copy
 * buffer. Source excerpts carry their own attribution and remain provisional.
 */
export function AnswerProgress({ hasContent, progress }: { hasContent: boolean; progress?: ChatResearchProgress | null }) {
  const researching = isResearchActive(progress);
  const cancelled = progress?.status === "cancelled";
  const failed = progress?.status === "failed";
  const summary = approachSummary(progress);
  const focus = approachFocus(progress);
  const findings = (progress?.findings ?? []).filter(finding =>
    finding.kind === "source_excerpt" && /^https?:\/\//i.test(finding.url)
  ).slice(-3);
  const candidate = progress?.interim_analysis;
  const analysis = candidate?.status === "provisional" && typeof candidate.text === "string" &&
    candidate.text.length > 0 && candidate.text.length <= 400 && Array.isArray(candidate.citations) &&
    candidate.citations.length > 0 && candidate.citations.length <= 3 &&
    candidate.citations.every(citation => typeof citation?.url === "string" &&
      /^https?:\/\//i.test(citation.url) && typeof citation.quote === "string") ? candidate : null;
  const statusText = researching
    ? stages[progress!.stage] ?? "正在查找资料"
    : cancelled
      ? "研究已停止"
      : failed
        ? "研究未能完成"
        : progress
          ? "研究过程已结束"
          : hasContent
            ? "回答正在补充，可以先阅读"
            : "正在组织回答";
  const read = progress?.read_count ?? 0;
  // Honest insufficiency: never dress "no usable text yet" up as progress.
  const insufficient = researching && read === 0 && findings.length === 0 && !analysis;
  const gaps = (progress?.reading_gaps ?? []).slice(0, 3);
  const groups = new Map<string, typeof findings>();
  for (const finding of findings) {
    const question = finding.question ?? "";
    groups.set(question, [...(groups.get(question) ?? []), finding]);
  }
  return <div className="answer-progress" role="status" aria-live="polite">
    {/* Terminal states must not keep spinning. */}
    {/* Research opening: display-only, never part of the answer text. */}
    {!analysis && summary ? <span className="answer-progress-approach">{summary}</span> : null}
    {!analysis && focus.length ? <span className="answer-progress-focus">{focus.join(" · ")}</span> : null}
    {!analysis ? <div className="research-status-line">
      {researching ? <Loader2 className="spin" size={13} /> : null}
      <span className="answer-progress-status">{statusText}</span>
      {researching ? <span className="answer-progress-counts">查询 {progress!.query_attempt_count} · 已读 {read}</span> : null}
    </div> : null}
    {insufficient ? <span className="answer-progress-note">暂未取得可用正文，正在尝试其他来源。</span> : null}
    {analysis ? <section className="research-interim-analysis" aria-label="阶段性分析">
      {analysis.text.split(/\n\s*\n|\n/).filter(paragraph => paragraph.trim()).map((paragraph, index) =>
        <p className="research-interim-text" key={index}>{paragraph}</p>)}
      <details className="research-interim-citations">
        <summary>来源与研究过程（{analysis.citations.length}）</summary>
        <p>{statusText} · 阶段性判断，可能随新资料调整</p>
        <ul>{analysis.citations.map((citation, index) => <li key={`${citation.url}:${index}`}>
          <a href={citation.url} target="_blank" rel="noopener noreferrer">{citation.title}</a>
          <blockquote>{citation.quote}</blockquote>
        </li>)}</ul>
        {gaps.length ? <p className="research-reading-gaps">暂无正文：{gaps.join("；")}</p> : null}
        {progress?.narration?.length ? <ol aria-label="研究过程">
          {progress.narration.map(block => <li key={block.block_id}>{block.text}</li>)}
        </ol> : null}
      </details>
    </section> : null}
    {!analysis && (findings.length || (gaps.length && (read > 0 || !researching))) ? <section className="research-findings" aria-label="已读资料摘录">
      <div className="research-findings-heading"><span>已读资料</span><span className="research-findings-note">原文摘录，尚非结论</span></div>
      {Array.from(groups, ([question, excerpts]) => <div className="research-finding-group" key={question}>
        {question ? <p className="research-finding-question">{question}</p> : null}
        <ul>{excerpts.map(finding => <li key={finding.id}>
            <a href={finding.url} target="_blank" rel="noopener noreferrer">{finding.title}</a>
            <blockquote>{finding.text}</blockquote>
        </li>)}</ul>
      </div>)}
      {gaps.length ? <p className="research-reading-gaps">暂无正文：{gaps.join("；")}</p> : null}
    </section> : null}
    {!analysis && progress?.narration?.length ? <details className="research-narration">
      <summary>查看搜索过程与失败原因</summary>
      <ol aria-label="研究过程">
        {progress.narration.map(block => <li key={block.block_id}>{block.text}</li>)}
      </ol>
    </details> : null}
  </div>;
}
