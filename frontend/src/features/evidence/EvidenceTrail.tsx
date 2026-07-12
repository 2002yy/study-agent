import { ChevronDown, ChevronRight, FileText, Search } from "lucide-react";
import { useState } from "react";
import { moveLabel, protocolLabel } from "../pedagogy/pedagogyLabels";
import { buildCitations, summarizeWebCalls } from "./evidenceHelpers";
import type { TurnEvidence } from "../../types";

export function EvidenceTrail({ evidence }: { evidence: TurnEvidence }) {
  const [open, setOpen] = useState(false);
  const pedagogy = evidence.pedagogy;
  const rag = evidence.rag;
  const web = rag
    ? summarizeWebCalls((rag.web_tools?.calls as never) ?? [])
    : { searches: [], reads: [] };
  const citations = rag ? buildCitations(rag) : [];
  const webUsed = Boolean(rag?.web_tools?.used);
  const webError = rag?.web_tools?.error;
  if (!pedagogy && citations.length === 0 && !webUsed && !webError) return null;
  return (
    <div className="evidence-trail">
      <button className="evidence-toggle" onClick={() => setOpen((v) => !v)} type="button">
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        证据轨迹
        {pedagogy ? (
          <span className="move-badge">
            {protocolLabel(pedagogy.mode)} · {moveLabel(pedagogy.move)}
          </span>
        ) : null}
        {webUsed ? <span className="web-flag">联网 {web.searches.length + web.reads.length}</span> : null}
        {citations.length ? <span className="cite-flag">引用 {citations.length}</span> : null}
      </button>
      {open ? (
        <div className="evidence-detail">
          {webError ? <div className="evidence-error">联网工具错误：{webError}</div> : null}
          {web.searches.map((s, i) => (
            <div key={`s${i}`} className="web-call-card">
              <div className="web-call-head">
                <Search size={13} /> 搜索 “{s.query}”
              </div>
              {s.results.slice(0, 3).map((r, j) => (
                <a key={j} className="web-result" href={r.url} target="_blank" rel="noreferrer">
                  {r.title || r.url}
                  {r.url ? <span className="web-url">{r.url}</span> : null}
                </a>
              ))}
            </div>
          ))}
          {web.reads.map((r, i) => (
            <div key={`r${i}`} className="web-call-card">
              <div className="web-call-head">
                <FileText size={13} /> 阅读 {r.url}
              </div>
              <p className="web-preview">{r.error ? `读取失败：${r.error}` : r.preview}</p>
            </div>
          ))}
          {citations.length ? (
            <ol className="citation-list">
              {citations.map((c, i) => (
                <li key={i}>
                  <strong>[{i + 1}]</strong> {c.title} <span className="cite-src">{c.source}</span>{" "}
                  <span className="cite-score">{c.score.toFixed(2)}</span>
                </li>
              ))}
            </ol>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
