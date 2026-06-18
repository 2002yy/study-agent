import { AlertTriangle, CheckCircle2, Loader2, Search } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
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
  onRunStarted,
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
  onRunStarted?: (runId: string) => void;
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
  const [searchedQuery, setSearchedQuery] = useState("");
  const newsRunIdRef = useRef(0);
  const newsAbortRef = useRef<AbortController | null>(null);

  const activeItems = enrichedItems.length ? enrichedItems : searchedItems;
  const queryChanged = Boolean(query.trim()) && query.trim() !== searchedQuery;
  const canSearch = Boolean(query.trim()) && !busyStage;
  const canEnrich = searchedItems.length > 0 && !busyStage && !queryChanged;
  const canDigest = activeItems.length > 0 && !busyStage && !queryChanged;
  const canDiscuss = Boolean(digestState?.digest) && !busyStage && !queryChanged;
  const articlesReadCount = enrichedItems.filter(
    (item) => typeof item.article_text === "string" || typeof item.article_excerpt === "string"
  ).length;

  // Clear staged news state when the owning workspace changes or cancels work.
  useEffect(() => {
    newsAbortRef.current?.abort();
    newsRunIdRef.current++;
    setSearchedItems([]);
    setEnrichedItems([]);
    setDigestState(null);
    setDiscussion("");
    setBusyStage("");
    setError("");
    setSearchedQuery("");
  }, [sessionId]);

  const clearDownstream = (from: "search" | "enrich" | "digest") => {
    if (from === "search") {
      setEnrichedItems([]);
      setDigestState(null);
      setDiscussion("");
      setError("");
    } else if (from === "enrich") {
      setDigestState(null);
      setDiscussion("");
      setError("");
    } else if (from === "digest") {
      setDiscussion("");
      setError("");
    }
  };

  const runSearch = async (event?: FormEvent) => {
    event?.preventDefault();
    if (!canSearch) {
      return;
    }
    const frozenQuery = query.trim();
    const runId = ++newsRunIdRef.current;
    onRunStarted?.(`news-${runId}`);
    const abortController = new AbortController();
    newsAbortRef.current?.abort();
    newsAbortRef.current = abortController;
    setBusyStage("search");
    setError("");
    clearDownstream("search");
    try {
      const result = await searchNewsStage(frozenQuery, 10, { signal: abortController.signal });
      if (newsRunIdRef.current !== runId) { return; }
      setSearchedItems(result.news_items);
      setEnrichedItems([]);
      setSearchedQuery(frozenQuery);
    } catch (caught) {
      if (newsRunIdRef.current !== runId || (caught instanceof DOMException && caught.name === "AbortError")) { return; }
      setError(caught instanceof Error ? caught.message : "新闻搜索失败");
    } finally {
      if (newsRunIdRef.current === runId) { setBusyStage(""); }
    }
  };

  const runEnrich = async () => {
    if (!canEnrich) {
      return;
    }
    const frozenQuery = searchedQuery || query.trim();
    const runId = ++newsRunIdRef.current;
    onRunStarted?.(`news-${runId}`);
    const abortController = new AbortController();
    newsAbortRef.current?.abort();
    newsAbortRef.current = abortController;
    setBusyStage("enrich");
    clearDownstream("enrich");
    try {
      const result = await enrichNewsStage({
        queryText: frozenQuery,
        newsItems: searchedItems,
        maxArticles: readArticles ? 6 : 0
      }, { signal: abortController.signal });
      if (newsRunIdRef.current !== runId) { return; }
      setEnrichedItems(result.news_items);
    } catch (caught) {
      if (newsRunIdRef.current !== runId || (caught instanceof DOMException && caught.name === "AbortError")) { return; }
      setError(caught instanceof Error ? caught.message : "正文读取失败");
    } finally {
      if (newsRunIdRef.current === runId) { setBusyStage(""); }
    }
  };

  const runDigest = async () => {
    if (!canDigest) {
      return;
    }
    const frozenQuery = searchedQuery || query.trim();
    const runId = ++newsRunIdRef.current;
    onRunStarted?.(`news-${runId}`);
    const abortController = new AbortController();
    newsAbortRef.current?.abort();
    newsAbortRef.current = abortController;
    // If readArticles is enabled but no articles enriched yet, auto-run enrich first
    let items = activeItems;
    if (readArticles && !enrichedItems.length && searchedItems.length) {
      setBusyStage("enrich");
      try {
        const enrichResult = await enrichNewsStage({
          queryText: frozenQuery,
          newsItems: searchedItems,
          maxArticles: 6
        }, { signal: abortController.signal });
        if (newsRunIdRef.current !== runId) { return; }
        items = enrichResult.news_items;
        setEnrichedItems(enrichResult.news_items);
      } catch (caught) {
        if (newsRunIdRef.current !== runId || (caught instanceof DOMException && caught.name === "AbortError")) { return; }
        setError(caught instanceof Error ? caught.message : "正文预读取失败，将仅根据标题生成摘要");
      } finally {
        if (newsRunIdRef.current === runId) { setBusyStage(""); }
      }
    }
    setBusyStage("digest");
    clearDownstream("digest");
    try {
      const result = await digestNewsStage({
        queryText: frozenQuery,
        newsItems: items,
        chatSettings
      }, { signal: abortController.signal });
      if (newsRunIdRef.current !== runId) { return; }
      setDigestState({
        digest: result.digest,
        sourceBlock: result.source_block,
        warnings: result.warnings
      });
    } catch (caught) {
      if (newsRunIdRef.current !== runId || (caught instanceof DOMException && caught.name === "AbortError")) { return; }
      setError(caught instanceof Error ? caught.message : "摘要生成失败");
    } finally {
      if (newsRunIdRef.current === runId) { setBusyStage(""); }
    }
  };

  const runDiscuss = async () => {
    if (!digestState || !canDiscuss) {
      return;
    }
    const runId = ++newsRunIdRef.current;
    onRunStarted?.(`news-${runId}`);
    const abortController = new AbortController();
    newsAbortRef.current?.abort();
    newsAbortRef.current = abortController;
    setBusyStage("discuss");
    clearDownstream("digest");
    try {
      const result = await discussNewsStage({
        digest: digestState.digest,
        sourceBlock: digestState.sourceBlock,
        sessionId,
        chatSettings
      }, { signal: abortController.signal });
      if (newsRunIdRef.current !== runId) { return; }
      setDiscussion(result.discussion);
      onDiscussed(result.session_id);
    } catch (caught) {
      if (newsRunIdRef.current !== runId || (caught instanceof DOMException && caught.name === "AbortError")) { return; }
      setError(caught instanceof Error ? caught.message : "群聊讨论生成失败");
    } finally {
      if (newsRunIdRef.current === runId) { setBusyStage(""); }
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
        {queryChanged ? (
          <small className="field-hint">搜索词已变化，请重新搜索后再执行后续操作。</small>
        ) : null}
        <button className="ghost-action compact lookup-action" disabled={isLookupBusy || !query.trim()} onClick={onLookupNews} type="button">
          仅搜索，用于下一轮聊天
        </button>
      </form>

      {activeItems.length ? (
        <div className="news-stage-summary">
          已读取正文 {articlesReadCount}/{activeItems.length} 篇
          {readArticles && !enrichedItems.length && searchedItems.length ? " · 点击「生成摘要」将自动先读取正文" : ""}
          {!readArticles ? " · 已跳过正文读取，将仅根据标题生成摘要" : ""}
        </div>
      ) : null}

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

      {queryChanged ? (
        <div className="memory-note warn">
          <AlertTriangle size={15} />
          <span>搜索词已变化，后续阶段将使用已冻结的搜索词「{searchedQuery}」；如需更换主题请重新搜索。</span>
        </div>
      ) : null}

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
