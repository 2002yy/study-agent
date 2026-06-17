import { AlertTriangle, CheckCircle2, Loader2, Search } from "lucide-react";
import { useState, type FormEvent } from "react";
import { digestNewsStage, discussNewsStage, enrichNewsStage, searchNewsStage } from "../../api";
import type { ChatSettings } from "../../types";
import { displayValue } from "../../utils/format";

type DigestState = {
  digest: string;
  sourceBlock: string;
  warnings: string[];
};

function NewsItemCard({ item, index }: { item: Record<string, unknown>; index: number }) {
  const url = item.canonical_url || item.resolved_link || item.link;
  const href = typeof url === "string" ? url : "";
  const title = displayValue(item.title) || `来源 ${index + 1}`;
  return (
    <div className="news-item">
      {href ? (
        <a href={href} rel="noreferrer" target="_blank">
          {title}
        </a>
      ) : (
        <strong>{title}</strong>
      )}
      <span>
        {displayValue(item.source)} · {displayValue(item.published_at)}
      </span>
      <small>{item.article_text || item.article_excerpt ? "正文已读取" : "标题级线索"}</small>
    </div>
  );
}

export function NewsWorkspace({
  query,
  setQuery,
  readArticles,
  setReadArticles,
  chatSettings,
  sessionId,
  onDiscussed,
  onLookupNews,
  isLookupBusy
}: {
  query: string;
  setQuery: (value: string) => void;
  readArticles: boolean;
  setReadArticles: (value: boolean) => void;
  chatSettings: ChatSettings;
  sessionId?: string;
  onDiscussed: (sessionId: string) => void;
  onLookupNews: () => void;
  isLookupBusy: boolean;
}) {
  const [searchedItems, setSearchedItems] = useState<Array<Record<string, unknown>>>([]);
  const [enrichedItems, setEnrichedItems] = useState<Array<Record<string, unknown>>>([]);
  const [digestState, setDigestState] = useState<DigestState | null>(null);
  const [discussion, setDiscussion] = useState("");
  const [busyStage, setBusyStage] = useState("");
  const [error, setError] = useState("");

  const activeItems = enrichedItems.length ? enrichedItems : searchedItems;
  const canSearch = Boolean(query.trim()) && !busyStage;
  const canEnrich = searchedItems.length > 0 && !busyStage;
  const canDigest = activeItems.length > 0 && !busyStage;
  const canDiscuss = Boolean(digestState?.digest) && !busyStage;

  const runSearch = async (event?: FormEvent) => {
    event?.preventDefault();
    if (!canSearch) {
      return;
    }
    setBusyStage("search");
    setError("");
    setDigestState(null);
    setDiscussion("");
    try {
      const result = await searchNewsStage(query.trim());
      setSearchedItems(result.news_items);
      setEnrichedItems([]);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "新闻搜索失败");
    } finally {
      setBusyStage("");
    }
  };

  const runEnrich = async () => {
    if (!canEnrich) {
      return;
    }
    setBusyStage("enrich");
    setError("");
    try {
      const result = await enrichNewsStage({
        queryText: query.trim(),
        newsItems: searchedItems,
        maxArticles: readArticles ? 6 : 0
      });
      setEnrichedItems(result.news_items);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "正文读取失败");
    } finally {
      setBusyStage("");
    }
  };

  const runDigest = async () => {
    if (!canDigest) {
      return;
    }
    setBusyStage("digest");
    setError("");
    try {
      const result = await digestNewsStage({
        queryText: query.trim(),
        newsItems: activeItems,
        chatSettings
      });
      setDigestState({
        digest: result.digest,
        sourceBlock: result.source_block,
        warnings: result.warnings
      });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "摘要生成失败");
    } finally {
      setBusyStage("");
    }
  };

  const runDiscuss = async () => {
    if (!digestState || !canDiscuss) {
      return;
    }
    setBusyStage("discuss");
    setError("");
    try {
      const result = await discussNewsStage({
        digest: digestState.digest,
        sourceBlock: digestState.sourceBlock,
        sessionId,
        chatSettings
      });
      setDiscussion(result.discussion);
      onDiscussed(result.session_id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "群聊讨论生成失败");
    } finally {
      setBusyStage("");
    }
  };

  return (
    <div className="news-workspace">
      <form className="mini-form news-form" onSubmit={runSearch}>
        <label className="field-row">
          <span>联网检索</span>
          <input onChange={(event) => setQuery(event.target.value)} placeholder="最新新闻 when:1d" value={query} />
        </label>
        <label className="toggle-row">
          <input checked={readArticles} onChange={(event) => setReadArticles(event.target.checked)} type="checkbox" />
          <span>尝试读取正文</span>
        </label>
        <button className="primary-action secondary" disabled={!canSearch} type="submit">
          {busyStage === "search" ? <Loader2 className="spin" size={15} /> : <Search size={15} />}
          搜索
        </button>
        <button className="ghost-action compact lookup-action" disabled={isLookupBusy || !query.trim()} onClick={onLookupNews} type="button">
          仅搜索，用于下一轮聊天
        </button>
      </form>

      <div className="news-stage-actions">
        <button className="ghost-action compact" disabled={!canEnrich} onClick={runEnrich} type="button">
          {busyStage === "enrich" ? <Loader2 className="spin" size={14} /> : <CheckCircle2 size={14} />}
          读取正文
        </button>
        <button className="ghost-action compact" disabled={!canDigest} onClick={runDigest} type="button">
          {busyStage === "digest" ? <Loader2 className="spin" size={14} /> : <CheckCircle2 size={14} />}
          生成摘要
        </button>
        <button className="ghost-action compact" disabled={!canDiscuss} onClick={runDiscuss} type="button">
          {busyStage === "discuss" ? <Loader2 className="spin" size={14} /> : <CheckCircle2 size={14} />}
          发起群聊
        </button>
      </div>

      {error ? (
        <div className="memory-note warn">
          <AlertTriangle size={15} />
          <span>{error}</span>
        </div>
      ) : null}

      {activeItems.length ? (
        <details className="news-result" open>
          <summary>搜索结果 {activeItems.length} 条</summary>
          <div className="news-list">
            {activeItems.slice(0, 4).map((item, index) => (
              <NewsItemCard item={item} index={index} key={`${displayValue(item.title)}-${index}`} />
            ))}
          </div>
        </details>
      ) : null}

      {digestState ? (
        <details className="news-result" open>
          <summary>新闻摘要</summary>
          <pre>{digestState.digest}</pre>
          {digestState.warnings.length ? (
            <div className="memory-note warn">
              <AlertTriangle size={15} />
              <span>{digestState.warnings.join("；")}</span>
            </div>
          ) : null}
        </details>
      ) : null}

      {discussion ? (
        <details className="news-result">
          <summary>群聊讨论</summary>
          <pre>{discussion}</pre>
        </details>
      ) : null}
    </div>
  );
}
