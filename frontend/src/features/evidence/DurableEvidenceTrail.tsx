import { ChevronDown, FileText } from "lucide-react";

import type { LearningResumeEvidence } from "../learning/learningResumeApi";
import "./evidenceTrail.css";

function lineLabel(source: LearningResumeEvidence): string {
  const start = source.start_line;
  const end = source.end_line;
  if (typeof start !== "number") return "";
  if (typeof end === "number" && end !== start) return `第 ${start}–${end} 行`;
  return `第 ${start} 行`;
}

function sourceUrl(source: LearningResumeEvidence): string {
  if (!source.repository || !source.commit_sha || !source.path) return "";
  const encodedPath = source.path
    .split("/")
    .map((part) => encodeURIComponent(part))
    .join("/");
  const line = typeof source.start_line === "number" ? `#L${source.start_line}` : "";
  return `https://github.com/${source.repository}/blob/${source.commit_sha}/${encodedPath}${line}`;
}

function SourceRow({ source }: { source: LearningResumeEvidence }) {
  const url = sourceUrl(source);
  const title = source.symbol || source.path || "源码证据";
  const location = [source.path, lineLabel(source)].filter(Boolean).join(":");
  const commit = source.commit_sha ? source.commit_sha.slice(0, 8) : "";

  return (
    <div className="evidence-ref-row durable-source-row">
      <FileText size={12} />
      <div className="durable-source-copy">
        {url ? (
          <a className="evidence-ref-link" href={url} target="_blank" rel="noreferrer">
            {title}
          </a>
        ) : (
          <span className="evidence-ref-title">{title}</span>
        )}
        <span className="evidence-ref-meta">
          {[location, commit ? `commit ${commit}` : ""].filter(Boolean).join(" · ")}
        </span>
      </div>
    </div>
  );
}

export function DurableEvidenceTrail({
  primary,
  supporting,
}: {
  primary: LearningResumeEvidence;
  supporting: LearningResumeEvidence[];
}) {
  const hasPrimary = Boolean(primary.path || primary.symbol || primary.evidence_id);
  if (!hasPrimary && !supporting.length) return null;

  return (
    <div className="evidence-trail durable-evidence-trail" aria-label="学习命题源码证据">
      {hasPrimary ? (
        <section className="evidence-primary" aria-label="主要证据">
          <div className="evidence-unified-header">
            <span>主要证据</span>
          </div>
          <div className="evidence-primary-list">
            <SourceRow source={primary} />
          </div>
        </section>
      ) : null}

      {supporting.length ? (
        <details className="evidence-diagnostics durable-supporting">
          <summary className="evidence-diagnostics-toggle">
            <ChevronDown size={13} /> 补充证据 {supporting.length}
          </summary>
          <div className="evidence-diagnostics-body">
            {supporting.map((source, index) => (
              <SourceRow
                key={source.evidence_id || `${source.commit_sha}-${source.path}-${index}`}
                source={source}
              />
            ))}
          </div>
        </details>
      ) : null}
    </div>
  );
}
