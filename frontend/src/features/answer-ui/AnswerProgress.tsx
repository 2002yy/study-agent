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
  const insufficient = researching && read === 0 && findings.length === 0;
  return <div className="answer-progress" role="status" aria-live="polite">
    {/* Terminal states must not keep spinning. */}
    {researching ? <Loader2 className="spin" size={14} /> : null}
    {/* Research opening: display-only, never part of the answer text. */}
    {summary ? <span className="answer-progress-approach">{summary}</span> : null}
    {focus.length ? <span className="answer-progress-focus">{focus.join(" · ")}</span> : null}
    <span className="answer-progress-status">{statusText}</span>
    {researching ? <span className="answer-progress-counts">查询 {progress!.query_attempt_count} · 已读 {read}</span> : null}
    {insufficient ? <span className="answer-progress-note">暂未取得可用正文，正在尝试其他来源。</span> : null}
    {findings.length ? <section className="research-findings" aria-label="已读资料摘录">
      <strong>先看看已读到的内容</strong>
      <p className="research-findings-note">以下是来源原文摘录，仍在核对，不代表最终结论。</p>
      <ul>
        {findings.map(finding => <li key={finding.id}>
          <a href={finding.url} target="_blank" rel="noopener noreferrer">{finding.title}</a>
          <blockquote>{finding.text}</blockquote>
        </li>)}
      </ul>
    </section> : null}
    {progress?.narration?.length ? <details className="research-narration">
      <summary>查看搜索过程与失败原因</summary>
      <ol aria-label="研究过程">
        {progress.narration.map(block => <li key={block.block_id}>{block.text}</li>)}
      </ol>
    </details> : null}
  </div>;
}
