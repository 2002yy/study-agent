import { FileText, RefreshCw } from "lucide-react";
import { useMemo } from "react";

import type {
  ChatResponse,
  KnowledgeDocumentListResponse,
  RagDebugResult,
  RagQueryResponse,
  RagResult,
} from "../../types";
import { basename, formatScore, translateStatus } from "../../utils/format";

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

export function SourcesPanel({
  lastChat,
  ragSearch,
  isSearching,
  knowledgeBase,
  onDeleteDocument,
  onRebuildKnowledge,
}: {
  lastChat: ChatResponse | null;
  ragSearch: RagQueryResponse | null;
  isSearching: boolean;
  knowledgeBase?: KnowledgeDocumentListResponse | null;
  onDeleteDocument?: (documentId: string) => void;
  onRebuildKnowledge?: () => void;
}) {
  const rows = useMemo(() => {
    const source = ragSearch ?? lastChat?.rag;
    return sourceRowsFromDebug(source?.debug.results, source?.results ?? []);
  }, [lastChat, ragSearch]);
  const activeSource = ragSearch ?? lastChat?.rag;
  const status = ragSearch
    ? `检索到 ${ragSearch.result_count} 条`
    : translateStatus(lastChat?.rag.status ?? "waiting");

  return (
    <section className="panel" id="sources">
      <div className="panel-header">
        <div>
          <h2>资料与来源</h2>
          <span>{isSearching ? "正在查找相关资料" : status}</span>
        </div>
        <FileText size={18} />
      </div>
      <small className="field-hint">
        这里展示回答实际使用或检索到的资料，帮助你核对结论来自哪里。
      </small>
      {rows.length ? (
        <div className="source-table" role="table" aria-label="检索到的引用来源">
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
      ) : (
        <div className="empty-state">
          还没有可展示的资料来源。开启“回答时使用我的资料”后继续提问，系统会在需要时自动查找。
        </div>
      )}
      {activeSource?.context || activeSource?.sources ? (
        <details className="debug-drawer">
          <summary>查看本次引用详情</summary>
          <small className="field-hint">用于核对模型实际看到的资料片段和来源位置。</small>
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
      {knowledgeBase ? (
        <>
          <details className="debug-drawer">
            <summary>已上传资料 {knowledgeBase.documents.length} 个</summary>
            <div className="session-list">
              {knowledgeBase.documents.map((document) => (
                <div className="session-row" key={document.document_id}>
                  <strong>{document.title}</strong>
                  <span>{document.file_type} · {document.chunks} 个片段</span>
                  <em title={document.source_path}>{document.source_path}</em>
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
              ))}
            </div>
          </details>
          {onRebuildKnowledge ? (
            <details className="knowledge-danger-zone">
              <summary>知识管理危险操作</summary>
              <small className="field-hint">
                重建会用下一次选择的文件替换当前全部资料索引。普通添加资料不需要使用这个操作。
              </small>
              <button className="ghost-action compact danger" onClick={onRebuildKnowledge} type="button">
                <RefreshCw size={14} />
                选择文件并重建全部资料
              </button>
            </details>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
