import { FileText } from "lucide-react";
import { useMemo } from "react";
import type { ChatResponse, RagDebugResult, RagQueryResponse, RagResult } from "../../types";
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

function sourceRowsFromDebug(debugResults: RagDebugResult[] | undefined, fallbackResults: RagResult[]): SourceRow[] {
  if (debugResults?.length) {
    return debugResults.map((item, index) => ({
      key: `${item.source_path ?? "source"}-${item.rank ?? index}`,
      rank: item.rank ?? index + 1,
      title: item.title || basename(item.source_path ?? "未命名资料"),
      sourcePath: item.source_path ?? "未知来源",
      lineRange: item.line_range ?? "-",
      score: item.score ?? 0,
      matchedTerms: item.matched_terms ?? [],
      scoreBreakdown: item.score_breakdown ?? {}
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
      scoreBreakdown: {}
    };
  });
}

export function SourcesPanel({
  lastChat,
  ragSearch,
  isSearching
}: {
  lastChat: ChatResponse | null;
  ragSearch: RagQueryResponse | null;
  isSearching: boolean;
}) {
  const rows = useMemo(() => {
    const source = ragSearch ?? lastChat?.rag;
    return sourceRowsFromDebug(source?.debug.results, source?.results ?? []);
  }, [lastChat, ragSearch]);
  const activeSource = ragSearch ?? lastChat?.rag;
  const status = ragSearch ? `检索到 ${ragSearch.result_count} 条` : translateStatus(lastChat?.rag.status ?? "waiting");

  return (
    <section className="panel" id="sources">
      <div className="panel-header">
        <div>
          <h2>引用来源</h2>
          <span>{isSearching ? "正在检索" : status}</span>
        </div>
        <FileText size={18} />
      </div>
      <small className="field-hint">
        这里展示 RAG 找到的本地资料。分数越高越相关；“注入上下文”是实际送进回答的资料片段。
      </small>
      {rows.length ? (
        <div className="source-table" role="table" aria-label="检索到的引用来源">
          <div className="source-row header" role="row">
            <span>排序</span>
            <span>来源</span>
            <span>分数</span>
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
                    <summary>分数 breakdown</summary>
                    <pre>{JSON.stringify(row.scoreBreakdown, null, 2)}</pre>
                  </details>
                ) : null}
              </div>
              <span>{formatScore(row.score)}</span>
            </div>
          ))}
        </div>
      ) : (
        <div className="empty-state">还没有引用来源。开启“用于聊天回答”后提问，或点击顶部检索按钮。</div>
      )}
      {activeSource?.context || activeSource?.sources ? (
        <details className="debug-drawer">
          <summary>引用上下文与来源块</summary>
          <small className="field-hint">来源块偏向审计和定位文件；注入上下文偏向还原模型实际看到的内容。</small>
          {activeSource.sources ? (
            <>
              <strong>来源块</strong>
              <pre>{activeSource.sources}</pre>
            </>
          ) : null}
          {activeSource.context ? (
            <>
              <strong>注入上下文</strong>
              <pre>{activeSource.context}</pre>
            </>
          ) : null}
        </details>
      ) : null}
    </section>
  );
}
