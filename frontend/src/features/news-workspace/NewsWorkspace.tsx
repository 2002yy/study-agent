import { AlertTriangle, CheckCircle2, Loader2, Search } from "lucide-react";
import { displayValue } from "../../utils/format";
import type { NewsController } from "./newsController";

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
  controller,
  onLookupNews,
  isLookupBusy
}: {
  query: string;
  setQuery: (value: string) => void;
  readArticles: boolean;
  setReadArticles: (value: boolean) => void;
  controller: NewsController;
  onLookupNews: () => void;
  isLookupBusy: boolean;
}) {
  const activeItems = controller.run?.items ?? [];
  const searchedQuery = controller.run?.query ?? "";
  const enriched = controller.run?.stage === "enriched";

  return (
    <div className="news-workspace">
      <form className="mini-form news-form" onSubmit={controller.search}>
        <label className="field-row">
          <span>联网检索</span>
          <input onChange={(event) => setQuery(event.target.value)} placeholder="最新新闻 when:1d" value={query} />
        </label>
        <label className="toggle-row">
          <input checked={readArticles} onChange={(event) => setReadArticles(event.target.checked)} type="checkbox" />
          <span>尝试读取正文</span>
        </label>
        <button className="primary-action secondary" disabled={!controller.canSearch} type="submit">
          {controller.busyStage === "search" ? <Loader2 className="spin" size={15} /> : <Search size={15} />}
          搜索
        </button>
        {controller.queryChanged ? (
          <small className="field-hint">搜索词已变化，请重新搜索后再执行后续操作。</small>
        ) : null}
        <button className="ghost-action compact lookup-action" disabled={isLookupBusy || !query.trim()} onClick={onLookupNews} type="button">
          仅搜索，用于下一轮聊天
        </button>
      </form>

      {activeItems.length ? (
        <div className="news-stage-summary">
          已读取正文 {controller.articlesReadCount}/{activeItems.length} 篇
          {readArticles && !enriched ? " · 点击「生成摘要」将自动先读取正文" : ""}
          {!readArticles ? " · 已跳过正文读取，将仅根据标题生成摘要" : ""}
        </div>
      ) : null}

      <div className="news-stage-actions">
        <button className="ghost-action compact" disabled={!controller.canEnrich} onClick={controller.enrich} type="button">
          {controller.busyStage === "enrich" ? <Loader2 className="spin" size={14} /> : <CheckCircle2 size={14} />}
          读取正文
        </button>
        <button className="ghost-action compact" disabled={!controller.canDigest} onClick={controller.digest} type="button">
          {controller.busyStage === "digest" ? <Loader2 className="spin" size={14} /> : <CheckCircle2 size={14} />}
          生成摘要
        </button>
        <button className="ghost-action compact" disabled={!controller.canDiscuss} onClick={controller.discuss} type="button">
          {controller.busyStage === "discuss" ? <Loader2 className="spin" size={14} /> : <CheckCircle2 size={14} />}
          发起群聊
        </button>
      </div>

      {controller.run?.stage === "enrich_skipped" ? (
        <div className="memory-note warn">
          <AlertTriangle size={15} />
          <span>
            正文读取已跳过：
            {controller.run.warnings[controller.run.warnings.length - 1] ?? "运行策略限制"}
          </span>
        </div>
      ) : null}

      {controller.queryChanged ? (
        <div className="memory-note warn">
          <AlertTriangle size={15} />
          <span>搜索词已变化，后续阶段将使用已冻结的搜索词「{searchedQuery}」；如需更换主题请重新搜索。</span>
        </div>
      ) : null}

      {controller.error ? (
        <div className="memory-note warn">
          <AlertTriangle size={15} />
          <span>{controller.error}</span>
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

      {controller.run?.digest ? (
        <details className="news-result" open>
          <summary>新闻摘要</summary>
          <pre>{controller.run.digest}</pre>
          {controller.run.warnings.length ? (
            <div className="memory-note warn">
              <AlertTriangle size={15} />
              <span>{controller.run.warnings.join("；")}</span>
            </div>
          ) : null}
        </details>
      ) : null}

      {controller.run?.discussion ? (
        <details className="news-result">
          <summary>群聊讨论</summary>
          <pre>{controller.run.discussion}</pre>
        </details>
      ) : null}
    </div>
  );
}
