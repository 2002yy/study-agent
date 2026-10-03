import {
  CheckCircle2,
  FileText,
  FolderOpen,
  RefreshCw,
  Settings2,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type {
  ChatResponse,
  RagDebugResult,
  RagQueryResponse,
  RagResult,
} from "../../types";
import { basename, formatScore, translateStatus } from "../../utils/format";
import {
  normalizeEvidence,
  type EvidenceRef,
} from "../evidence/evidenceHelpers";
import {
  setKnowledgeDocumentEvidenceStatus,
  type EvidenceKnowledgeDocumentListResponse,
  type EvidenceStatus,
} from "./evidenceEligibilityApi";
import { SessionAttachments } from "./SessionAttachments";
import { useReadingWorkspace } from "../reading/ReadingContext";

type SourceRow = {
  key: string;
  rank: number;
  title: string;
  sourcePath: string;
  lineRange: string;
  score: number;
  matchedTerms: string[];
  scoreBreakdown: Record<string, number>;
};

type SourcesTab = "answer" | "library" | "diagnostics";

const SOURCES_TABS: Array<{
  id: SourcesTab;
  label: string;
  description: string;
}> = [
  {
    id: "answer",
    label: "本次回答依据",
    description: "只展示回答实际采用或教学明确引用的证据。",
  },
  {
    id: "library",
    label: "我的资料",
    description: "管理长期资料及其是否参与后续回答。",
  },
  {
    id: "diagnostics",
    label: "检索诊断",
    description: "查看候选、排序、分数和模型上下文等调试信息。",
  },
];

function sourceRowsFromDebug(
  debugResults: RagDebugResult[] | undefined,
  fallbackResults: RagResult[],
): SourceRow[] {
  if (debugResults?.length) {
    return debugResults.map((item, index) => ({
      key: `${item.source_path ?? "source"}-${item.rank ?? index}`,
      rank: item.rank ?? index + 1,
      title: item.title || basename(item.source_path ?? "未命名资料"),
      sourcePath: item.source_path ?? "未知来源",
      lineRange: item.line_range ?? "-",
      score: item.score ?? 0,
      matchedTerms: item.matched_terms ?? [],
      scoreBreakdown: item.score_breakdown ?? {},
    }));
  }
  return fallbackResults.map((item, index) => {
    const chunk = item.chunk ?? {};
    return {
      key: chunk.chunk_id ?? `${chunk.source_path ?? "source"}-${index}`,
      rank: index + 1,
      title: chunk.title || basename(chunk.source_path ?? "未命名资料"),
      sourcePath: chunk.source_path ?? "未知来源",
      lineRange:
        typeof chunk.start_line === "number" && typeof chunk.end_line === "number"
          ? `L${chunk.start_line}-L${chunk.end_line}`
          : "-",
      score: item.score ?? 0,
      matchedTerms: item.matched_terms ?? [],
      scoreBreakdown: {},
    };
  });
}

function evidenceStatusLabel(status: EvidenceStatus): string {
  if (status === "superseded") return "旧版本 · 不参与回答";
  if (status === "excluded") return "已排除 · 不参与回答";
  return "当前资料 · 会参与回答";
}

function evidenceTypeLabel(type: EvidenceRef["type"]): string {
  if (type === "local") return "本地资料";
  if (type === "web_search") return "网页搜索";
  if (type === "web_read") return "网页阅读";
  return "联网研究";
}

function lifecycleLabel(status: EvidenceRef["status"]): string {
  if (status === "selected") return "已采用";
  if (status === "read") return "已阅读";
  if (status === "rejected") return "已排除";
  return "候选";
}

function EvidenceReference({
  evidence,
  supported,
  diagnostic = false,
}: {
  evidence: EvidenceRef;
  supported: boolean;
  diagnostic?: boolean;
}) {
  const title = evidence.title || evidence.source || evidence.url || "未命名证据";
  const location = evidence.url || evidence.source || evidence.domain;
  return (
    <div className={`sources-evidence-card${diagnostic ? " diagnostic" : ""}`}>
      <div className="sources-evidence-heading">
        <span>{evidenceTypeLabel(evidence.type)}</span>
        <strong>{title}</strong>
        <em>{supported ? "教学明确引用" : lifecycleLabel(evidence.status)}</em>
      </div>
      {location ? (
        evidence.url ? (
          <a href={evidence.url} target="_blank" rel="noreferrer">
            {location}
          </a>
        ) : (
          <small title={location}>{location}</small>
        )
      ) : null}
      {diagnostic ? (
        <div className="sources-evidence-meta">
          <span>生命周期：{lifecycleLabel(evidence.status)}</span>
          {evidence.score > 0 ? <span>分数：{formatScore(evidence.score)}</span> : null}
          {evidence.providerStatus ? <span>Provider：{evidence.providerStatus}</span> : null}
          {evidence.selectionReason ? <span>采用原因：{evidence.selectionReason}</span> : null}
          {evidence.rejectionReason ? <span>排除原因：{evidence.rejectionReason}</span> : null}
        </div>
      ) : null}
    </div>
  );
}

export function SourcesPanel({
  lastChat,
  ragSearch,
  isSearching,
  knowledgeBase,
  sessionId,
  onDeleteDocument,
  onSetEvidenceStatus,
  onRebuildKnowledge,
  initialTab = "answer",
}: {
  lastChat: ChatResponse | null;
  ragSearch: RagQueryResponse | null;
  isSearching: boolean;
  knowledgeBase?: EvidenceKnowledgeDocumentListResponse | null;
  sessionId?: string | null;
  onDeleteDocument?: (documentId: string) => void;
  onSetEvidenceStatus?: (
    documentId: string,
    status: EvidenceStatus,
  ) => Promise<void> | void;
  onRebuildKnowledge?: () => void;
  initialTab?: SourcesTab;
}) {
  const [activeTab, setActiveTab] = useState<SourcesTab>(initialTab);
  const reading = useReadingWorkspace();
  const [statusOverrides, setStatusOverrides] = useState<Record<string, EvidenceStatus>>({});
  const [evidenceError, setEvidenceError] = useState("");
  const activeSource = ragSearch ?? lastChat?.rag;
  const rows = useMemo(
    () => sourceRowsFromDebug(activeSource?.debug.results, activeSource?.results ?? []),
    [activeSource],
  );
  const answerEvidence = useMemo(() => {
    if (!lastChat) return [];
    return normalizeEvidence({
      pedagogy: lastChat.pedagogy,
      rag: lastChat.rag,
      route: lastChat.route,
    });
  }, [lastChat]);
  const supportedIds = useMemo(
    () => new Set(lastChat?.pedagogy?.evidence_ids ?? []),
    [lastChat?.pedagogy?.evidence_ids],
  );
  const adoptedEvidence = answerEvidence.filter(
    (evidence) => evidence.status === "selected" || supportedIds.has(evidence.id),
  );
  const status = ragSearch
    ? `检索到 ${ragSearch.result_count} 条`
    : translateStatus(lastChat?.rag.status ?? "waiting");

  useEffect(() => {
    setStatusOverrides({});
  }, [knowledgeBase?.index_version]);

  const effectiveStatus = (documentId: string, serverStatus?: EvidenceStatus): EvidenceStatus =>
    statusOverrides[documentId] ?? serverStatus ?? "active";
  const retrievableDocumentCount = knowledgeBase
    ? knowledgeBase.documents.filter(
        (document) => effectiveStatus(document.document_id, document.evidence_status) === "active",
      ).length
    : 0;

  const updateEvidenceStatus = async (documentId: string, nextStatus: EvidenceStatus) => {
    setEvidenceError("");
    try {
      if (onSetEvidenceStatus) {
        await onSetEvidenceStatus(documentId, nextStatus);
      } else {
        await setKnowledgeDocumentEvidenceStatus(documentId, nextStatus);
      }
      setStatusOverrides((current) => ({ ...current, [documentId]: nextStatus }));
    } catch (error) {
      setEvidenceError(
        `资料状态更新失败：${error instanceof Error ? error.message : "更新失败"}`,
      );
    }
  };

  const activeTabDefinition = SOURCES_TABS.find((tab) => tab.id === activeTab) ?? SOURCES_TABS[0];

  return (
    <section className="panel sources-panel" id="sources">
      <div className="panel-header">
        <div>
          <h2>资料与来源</h2>
          <span>
            {activeTab === "answer"
              ? adoptedEvidence.length
                ? `本次回答采用 ${adoptedEvidence.length} 条证据`
                : "本次回答暂无可核对依据"
              : activeTab === "library"
                ? knowledgeBase
                  ? `${knowledgeBase.documents.length} 份资料`
                  : "正在加载资料"
                : isSearching
                  ? "正在查找相关资料"
                  : status}
          </span>
        </div>
        <FileText size={18} />
      </div>

      <div className="sources-tabs" role="tablist" aria-label="资料与来源分层">
        {SOURCES_TABS.map((tab) => {
          const selected = tab.id === activeTab;
          const Icon = tab.id === "answer" ? CheckCircle2 : tab.id === "library" ? FolderOpen : Settings2;
          return (
            <button
              aria-controls={`sources-panel-${tab.id}`}
              aria-selected={selected}
              className={selected ? "active" : ""}
              id={`sources-tab-${tab.id}`}
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              role="tab"
              type="button"
            >
              <Icon size={14} />
              {tab.label}
            </button>
          );
        })}
      </div>
      <small className="sources-layer-hint">{activeTabDefinition.description}</small>

      <div
        aria-labelledby={`sources-tab-${activeTab}`}
        className="sources-tab-panel"
        id={`sources-panel-${activeTab}`}
        role="tabpanel"
      >
        {activeTab === "answer" ? (
          adoptedEvidence.length ? (
            <div className="sources-evidence-list" aria-label="本次回答采用的证据">
              {adoptedEvidence.map((evidence) => (
                <EvidenceReference
                  evidence={evidence}
                  key={evidence.id}
                  supported={supportedIds.has(evidence.id)}
                />
              ))}
            </div>
          ) : (
            <div className="empty-state">
              当前回答没有标记为已采用的证据。候选资料不会在这里冒充回答依据，可前往“检索诊断”核对检索过程。
            </div>
          )
        ) : null}

        {activeTab === "library" ? (
          knowledgeBase ? (
            <div className="sources-library">
              <SessionAttachments sessionId={sessionId} />
              <div className="sources-library-summary">
                <strong>已上传资料 {knowledgeBase.documents.length} 个</strong>
                <span>当前可用于回答 {retrievableDocumentCount} 个</span>
              </div>
              <small className="field-hint">
                “旧版本”和“已排除”资料仍会保留，但不会进入普通检索和回答证据。
              </small>
              {evidenceError ? <div className="inline-error">{evidenceError}</div> : null}
              {knowledgeBase.documents.length ? (
                <div className="session-list">
                  {knowledgeBase.documents.map((document) => {
                    const documentStatus = effectiveStatus(document.document_id, document.evidence_status);
                    return (
                      <div className="session-row" key={document.document_id}>
                        <strong>{document.title}</strong>
                        <span>{document.file_type} · {document.chunks} 个片段</span>
                        <span>{evidenceStatusLabel(documentStatus)}</span>
                        <em title={document.source_path}>{document.source_path}</em>
                        <div className="inline-actions">
                          {reading ? <button className="ghost-action compact" type="button"
                            onClick={() => reading.open({scope:"knowledge",documentId:document.document_id,
                              revision:document.revision_id,sourcePath:document.source_path})}>
                            <FileText size={14}/>阅读正文
                          </button> : null}
                          {documentStatus === "active" ? (
                            <>
                              <button
                                className="ghost-action compact"
                                onClick={() => void updateEvidenceStatus(document.document_id, "superseded")}
                                type="button"
                              >
                                标记为旧版本
                              </button>
                              <button
                                className="ghost-action compact"
                                onClick={() => void updateEvidenceStatus(document.document_id, "excluded")}
                                type="button"
                              >
                                不参与回答
                              </button>
                            </>
                          ) : (
                            <button
                              className="ghost-action compact"
                              onClick={() => void updateEvidenceStatus(document.document_id, "active")}
                              type="button"
                            >
                              恢复为当前资料
                            </button>
                          )}
                        </div>
                        {onDeleteDocument ? (
                          <button
                            className="ghost-action compact danger"
                            onClick={() => onDeleteDocument(document.document_id)}
                            type="button"
                          >
                            删除资料
                          </button>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="empty-state">还没有上传资料。可从学习工作台顶部选择“上传学习资料”。</div>
              )}
              {onRebuildKnowledge ? (
                <details className="knowledge-danger-zone">
                  <summary>知识管理危险操作</summary>
                  <small className="field-hint">
                    重建会用下一次选择的文件替换当前全部资料索引。普通添加资料不需要使用这个操作。
                  </small>
                  <button
                    className="ghost-action compact danger"
                    onClick={onRebuildKnowledge}
                    type="button"
                  >
                    <RefreshCw size={14} />
                    选择文件并重建全部资料
                  </button>
                </details>
              ) : null}
            </div>
          ) : (
            <div className="empty-state">正在加载已上传资料…</div>
          )
        ) : null}

        {activeTab === "diagnostics" ? (
          <div className="sources-diagnostics">
            {answerEvidence.length ? (
              <section aria-label="证据生命周期">
                <h3>证据生命周期</h3>
                <div className="sources-evidence-list diagnostic">
                  {answerEvidence.map((evidence) => (
                    <EvidenceReference
                      diagnostic
                      evidence={evidence}
                      key={evidence.id}
                      supported={supportedIds.has(evidence.id)}
                    />
                  ))}
                </div>
              </section>
            ) : null}

            {rows.length ? (
              <section aria-label="检索候选与排序">
                <h3>检索候选与排序</h3>
                <div className="source-table" role="table" aria-label="检索候选与排序表">
                  <div className="source-row header" role="row">
                    <span>排序</span>
                    <span>来源</span>
                    <span>相关度</span>
                  </div>
                  {rows.map((row) => (
                    <div className="source-row" role="row" key={row.key}>
                      <strong>#{row.rank}</strong>
                      <div>
                        <b>{row.title}</b>
                        <small>
                          {row.lineRange} · {row.matchedTerms.length ? row.matchedTerms.join(", ") : "暂无命中词"}
                        </small>
                        <em title={row.sourcePath}>{row.sourcePath}</em>
                        {Object.keys(row.scoreBreakdown).length ? (
                          <details className="inline-details">
                            <summary>查看检索评分详情</summary>
                            <pre>{JSON.stringify(row.scoreBreakdown, null, 2)}</pre>
                          </details>
                        ) : null}
                      </div>
                      <span>{formatScore(row.score)}</span>
                    </div>
                  ))}
                </div>
              </section>
            ) : null}

            {activeSource?.context || activeSource?.sources ? (
              <details className="debug-drawer">
                <summary>查看模型上下文与来源片段</summary>
                <small className="field-hint">用于诊断模型实际看到的资料片段和来源位置。</small>
                {activeSource.sources ? (
                  <>
                    <strong>来源片段</strong>
                    <pre>{activeSource.sources}</pre>
                  </>
                ) : null}
                {activeSource.context ? (
                  <>
                    <strong>回答上下文</strong>
                    <pre>{activeSource.context}</pre>
                  </>
                ) : null}
              </details>
            ) : null}

            {!answerEvidence.length && !rows.length && !activeSource?.context && !activeSource?.sources ? (
              <div className="empty-state">当前没有可展示的检索诊断数据。</div>
            ) : null}
          </div>
        ) : null}
      </div>
    </section>
  );
}
