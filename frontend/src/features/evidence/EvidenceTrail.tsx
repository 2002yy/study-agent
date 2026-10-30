import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clipboard,
  FileText,
  Search,
  Settings2,
  XCircle,
} from "lucide-react";
import { useState } from "react";
import { uiStatusLabel, uiReasonLabel } from "../../utils/uiLabels";
import type { TurnEvidence } from "../../types";
import { moveLabel, protocolLabel } from "../pedagogy/pedagogyLabels";
import {
  buildCitations,
  normalizeEvidence,
  summarizeWebCalls,
  uncitedReadSources,
  verifiedCitations,
} from "./evidenceHelpers";
import type { EvidenceRef } from "./evidenceHelpers";
import { ExternalDataDisclosure } from "./ExternalDataDisclosure";
import "./evidenceTrail.css";
import { useReadingWorkspace } from "../reading/ReadingContext";

const STATUS_LABELS: Record<EvidenceRef["status"], string> = {
  selected: "已选中",
  read: "已读取",
  candidate: "候选",
  rejected: "已排除",
};

const STATUS_ORDER: EvidenceRef["status"][] = [
  "selected",
  "read",
  "candidate",
  "rejected",
];

type CopyTarget = "cited" | "diagnostics";
type CopyState = "idle" | "success" | "error";

const CITATION_LABEL = "已核验引用";

function evidenceTypeLabel(type: EvidenceRef["type"]): string {
  if (type === "local") return "本地";
  if (type === "web_search") return "搜索";
  if (type === "web_read") return "阅读";
  return "研究";
}

export function formatEvidencePlainText(
  pedagogy: TurnEvidence["pedagogy"],
  refs: EvidenceRef[],
  includeDiagnostics = false,
): string {
  const lines: string[] = [includeDiagnostics ? "证据诊断" : CITATION_LABEL];
  if (pedagogy) {
    lines.push(`${protocolLabel(pedagogy.mode)} · ${moveLabel(pedagogy.move)}`);
  }
  lines.push("");
  for (const ref of refs) {
    const link = ref.url || ref.source || ref.title;
    const title = ref.title || link;
    if (!includeDiagnostics) {
      lines.push(`${title}（${evidenceTypeLabel(ref.type)}）${ref.url ? ` ${ref.url}` : ""}`);
      continue;
    }
    const score = ref.score > 0 ? ` 相关度：${ref.score.toFixed(2)}` : "";
    const provider = ref.providerStatus ? ` 来源状态：${uiStatusLabel(ref.providerStatus)}` : "";
    const reason = ref.rejectionReason || ref.selectionReason;
    lines.push(
      `[${STATUS_LABELS[ref.status]}] ${title}（${evidenceTypeLabel(ref.type)}）${
        ref.url ? ` ${ref.url}` : ""
      }${score}${provider}${reason ? ` ${ref.rejectionReason ? "排除" : "采用"}原因：${uiReasonLabel(reason)}` : ""}`,
    );
  }
  return lines.join("\n");
}

function copyButtonLabel(target: CopyTarget, state: CopyState): string {
  if (state === "success") return "已复制";
  if (state === "error") return "复制失败";
  return target === "diagnostics" ? "复制诊断" : "复制引用";
}

function EvidenceRow({
  ref,
  supported,
  diagnostic = false,
  citationLabel = "",
  onRead,
}: {
  ref: EvidenceRef;
  supported: boolean;
  diagnostic?: boolean;
  citationLabel?: string;
  onRead?: () => void;
}) {
  return (
    <div className={`evidence-ref-row${diagnostic ? " is-diagnostic" : ""}`}>
      {supported ? (
        <span className="evidence-ref-supported" title="教学法引用">
          引
        </span>
      ) : null}
      {citationLabel ? (
        <span className="evidence-ref-citation">{citationLabel}</span>
      ) : null}
      <span className="evidence-ref-type">{evidenceTypeLabel(ref.type)}</span>
      {ref.url ? (
        <a
          className="evidence-ref-link"
          href={ref.url}
          target="_blank"
          rel="noreferrer"
        >
          {ref.title || ref.url}
        </a>
      ) : (
        <span className="evidence-ref-title">{ref.title || ref.source}</span>
      )}
      {diagnostic && ref.score > 0 ? (
        <span className="evidence-ref-score">相关度：{ref.score.toFixed(2)}</span>
      ) : null}
      {onRead ? <button className="evidence-reading-link" type="button" onClick={onRead}>{ref.type === "local" ? "定位正文" : "阅读网页"}</button> : null}
      {diagnostic && (ref.providerStatus || ref.selectionReason || ref.rejectionReason) ? (
        <span className="evidence-ref-meta">
          {[
            ref.providerStatus ? `来源状态：${uiStatusLabel(ref.providerStatus)}` : "",
            ref.selectionReason ? `采用原因：${uiReasonLabel(ref.selectionReason)}` : "",
            ref.rejectionReason ? `排除原因：${uiReasonLabel(ref.rejectionReason)}` : "",
          ]
            .filter(Boolean)
            .join(" · ")}
        </span>
      ) : null}
    </div>
  );
}

export function EvidenceTrail({ evidence }: { evidence: TurnEvidence }) {
  const reading = useReadingWorkspace();
  const [open, setOpen] = useState(false);
  const [diagnosticsOpen, setDiagnosticsOpen] = useState(false);
  const [copyResult, setCopyResult] = useState<{ target: CopyTarget; state: CopyState } | null>(null);
  const [copyAnnouncement, setCopyAnnouncement] = useState("");
  const pedagogy = evidence.pedagogy;
  const rag = evidence.rag;
  const web = rag
    ? summarizeWebCalls(rag.web_tools?.calls ?? [])
    : { searches: [], reads: [] };
  const citations = rag ? buildCitations(rag) : [];
  const evidenceRefs = normalizeEvidence(evidence);
  const supportedIds = new Set(pedagogy?.evidence_ids ?? []);
  const readAction = (ref: EvidenceRef) => {
    const target = ref.type === "local" ? reading?.citation(ref.id,ref.source,rag?.results ?? [])
      : ref.type !== "web_search" && (ref.status === "read" || ref.status === "selected")
        ? reading?.webCitation(ref.url || "",evidence) : null;
    return target && reading ? () => reading.open(target) : undefined;
  };
  const citedRefs = verifiedCitations(evidenceRefs);
  const uncitedRefs = uncitedReadSources(evidenceRefs);
  const webError = rag?.web_tools?.error;
  const recoveredResearchUsed = Boolean(rag?.web_context?.used && rag.web_context.run_id);
  const hasExternalDataPolicy = Boolean(
    rag?.external_data_policy || evidence.route?.external_data_policy,
  );
  const hasDiagnostics = Boolean(
    evidenceRefs.length ||
      web.searches.length ||
      web.reads.length ||
      citations.length ||
      webError ||
      recoveredResearchUsed ||
      hasExternalDataPolicy,
  );

  const copyEvidence = async (target: CopyTarget, text: string) => {
    try {
      if (!navigator.clipboard?.writeText) throw new Error("clipboard unavailable");
      await navigator.clipboard.writeText(text);
      setCopyResult({ target, state: "success" });
      setCopyAnnouncement(target === "diagnostics" ? "证据诊断已复制" : "已核验引用已复制");
    } catch {
      setCopyResult({ target, state: "error" });
      setCopyAnnouncement("复制失败，请检查浏览器剪贴板权限后重试");
    }
    window.setTimeout(() => {
      setCopyResult((current) => (current?.target === target ? null : current));
      setCopyAnnouncement("");
    }, 2400);
  };

  const stateFor = (target: CopyTarget): CopyState =>
    copyResult?.target === target ? copyResult.state : "idle";

  if (!pedagogy && !hasDiagnostics) return null;

  return (
    <div className="evidence-trail">
      {copyAnnouncement ? (
        <span className="visually-hidden" aria-live="polite" role="status">
          {copyAnnouncement}
        </span>
      ) : null}
      <button
        className="evidence-toggle"
        onClick={() => setOpen((value) => !value)}
        type="button"
        aria-expanded={open}
      >
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        证据轨迹
        {pedagogy ? (
          <span className="move-badge">
            {protocolLabel(pedagogy.mode)} · {moveLabel(pedagogy.move)}
          </span>
        ) : null}
        {citedRefs.length ? (
          <span className="evidence-summary-flag">已核验引用 {citedRefs.length}</span>
        ) : null}
      </button>

      {open ? (
        <div className="evidence-detail">
          {citedRefs.length ? (
            <section className="evidence-primary" aria-label={CITATION_LABEL}>
              <div className="evidence-unified-header">
                <span>{CITATION_LABEL}（{citedRefs.length} 条）</span>
                <button
                  className={`ghost-action compact evidence-copy${stateFor("cited") === "error" ? " copy-error" : ""}`}
                  onClick={() =>
                    void copyEvidence("cited", formatEvidencePlainText(pedagogy, citedRefs))
                  }
                  type="button"
                  title="复制已核验引用"
                >
                  <Clipboard size={12} /> {copyButtonLabel("cited", stateFor("cited"))}
                </button>
              </div>
              <div className="evidence-primary-list">
                {citedRefs.map((ref) => (
                  <EvidenceRow
                    key={`${ref.id}-cited`}
                    ref={ref}
                    supported={false}
                    citationLabel={CITATION_LABEL}
                    onRead={readAction(ref)}
                  />
                ))}
              </div>
            </section>
          ) : hasDiagnostics ? (
            <p className="evidence-empty-note">
              本轮没有通过发布校验的引用。
            </p>
          ) : null}

          {uncitedRefs.length ? (
            <section className="evidence-uncited" aria-label="已读取但未引用">
              <div className="evidence-unified-header">
                <span>已读取但未引用（{uncitedRefs.length} 条）</span>
              </div>
              <div className="evidence-primary-list">
                {uncitedRefs.map((ref) => (
                  <EvidenceRow
                    key={`${ref.id}-uncited`}
                    ref={ref}
                    supported={false}
                    citationLabel={STATUS_LABELS[ref.status]}
                    onRead={readAction(ref)}
                  />
                ))}
              </div>
            </section>
          ) : null}

          {hasDiagnostics ? (
            <section className="evidence-diagnostics">
              <button
                className="evidence-diagnostics-toggle"
                type="button"
                onClick={() => setDiagnosticsOpen((value) => !value)}
                aria-expanded={diagnosticsOpen}
              >
                <Settings2 size={13} />
                {diagnosticsOpen ? "收起诊断详情" : "显示诊断详情"}
              </button>

              {diagnosticsOpen ? (
                <div className="evidence-diagnostics-body">
                  <div className="evidence-diagnostics-header">
                    <strong>完整证据生命周期</strong>
                    {evidenceRefs.length ? (
                      <button
                        className={`ghost-action compact evidence-copy${stateFor("diagnostics") === "error" ? " copy-error" : ""}`}
                        onClick={() =>
                          void copyEvidence(
                            "diagnostics",
                            formatEvidencePlainText(pedagogy, evidenceRefs, true),
                          )
                        }
                        type="button"
                        title="复制诊断详情"
                      >
                        <Clipboard size={12} /> {copyButtonLabel("diagnostics", stateFor("diagnostics"))}
                      </button>
                    ) : null}
                  </div>

                  {webError ? (
                    <div className="evidence-error">联网来源暂不可用，请稍后重试。</div>
                  ) : null}

                  <ExternalDataDisclosure evidence={evidence} />

                  {recoveredResearchUsed ? (
                    <div
                      className="web-call-card"
                      data-research-run-id={rag?.web_context?.run_id}
                    >
                      本轮使用了已恢复的联网研究来源。
                    </div>
                  ) : null}

                  {evidenceRefs.length ? (
                    <div className="evidence-unified">
                      {STATUS_ORDER.filter((status) =>
                        evidenceRefs.some((ref) => ref.status === status),
                      ).map((status) => (
                        <div key={status} className="evidence-status-group">
                          <div className="evidence-status-label">
                            {status === "selected" ? (
                              <CheckCircle2 size={12} />
                            ) : status === "rejected" ? (
                              <XCircle size={12} />
                            ) : null}
                            {STATUS_LABELS[status]}
                          </div>
                          {evidenceRefs
                            .filter((ref) => ref.status === status)
                            .map((ref) => (
                              <EvidenceRow
                                key={ref.id}
                                ref={ref}
                                supported={supportedIds.has(ref.id)}
                                diagnostic
                                onRead={readAction(ref)}
                              />
                            ))}
                        </div>
                      ))}
                    </div>
                  ) : null}

                  {web.searches.map((search, index) => (
                    <div key={`s${index}`} className="web-call-card">
                      <div className="web-call-head">
                        <Search size={13} /> 搜索 “{search.query}” · 候选（预览{" "}
                        {Math.min(3, search.results.length)}/{search.results.length}）
                      </div>
                      {search.results.length ? (
                        <>
                          {search.results.slice(0, 3).map((result, resultIndex) => (
                            <a
                              key={`${result.url ?? result.title ?? resultIndex}`}
                              className="web-result"
                              href={result.url}
                              target="_blank"
                              rel="noreferrer"
                            >
                              {result.title || result.url}
                              {result.url ? (
                                <span className="web-url">{result.url}</span>
                              ) : null}
                            </a>
                          ))}
                          {search.results.length > 3 ? (
                            <details className="web-result-overflow">
                              <summary>查看其余 {search.results.length - 3} 条候选</summary>
                              {search.results.slice(3).map((result, resultIndex) => (
                                <a
                                  key={`${result.url ?? result.title ?? resultIndex + 3}`}
                                  className="web-result"
                                  href={result.url}
                                  target="_blank"
                                  rel="noreferrer"
                                >
                                  {result.title || result.url}
                                  {result.url ? (
                                    <span className="web-url">{result.url}</span>
                                  ) : null}
                                </a>
                              ))}
                            </details>
                          ) : null}
                        </>
                      ) : (
                        <p className="web-preview">本次查询没有返回可展示的结果。</p>
                      )}
                    </div>
                  ))}

                  {web.reads.map((read, index) => (
                    <div key={`r${index}`} className="web-call-card">
                      <div className="web-call-head">
                        <FileText size={13} /> 阅读 {read.url}
                      </div>
                      <p className="web-preview">
                        {read.error ? "来源读取失败，请稍后重试。" : read.preview}
                      </p>
                    </div>
                  ))}

                  {citations.length ? (
                    <div className="evidence-legacy-citations">
                      <strong>旧版本地引用兼容数据</strong>
                      <ol className="citation-list">
                        {citations.map((citation, index) => (
                          <li key={`${citation.source}-${citation.title}`}>
                            <strong>[{index + 1}]</strong> {citation.title}{" "}
                            <span className="cite-src">{citation.source}</span>{" "}
                            <span className="cite-score">
                              {citation.score.toFixed(2)}
                            </span>
                          </li>
                        ))}
                      </ol>
                    </div>
                  ) : null}
                </div>
              ) : null}
            </section>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
