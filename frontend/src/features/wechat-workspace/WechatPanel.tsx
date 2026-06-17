import { AlertTriangle, Loader2, MessageSquare, Search, Send, Sparkles } from "lucide-react";
import type { FormEvent } from "react";
import { useEffect, useState } from "react";
import { searchWechat } from "../../api";
import { RoleAvatar } from "../../components/RoleAvatar";
import type { ChatSettings, NewsLookupResponse, NewsSearchResponse, WechatSearchResponse, WechatStateResponse } from "../../types";
import { displayValue } from "../../utils/format";
import { NewsWorkspace } from "../news-workspace/NewsWorkspace";
import { speakerToRole } from "../roles/roleCatalog";

export function parseWechatMessages(content: string): Array<{ speaker: string; roleId: string; text: string }> {
  const blocks: Array<{ speaker: string; roleId: string; text: string }> = [];
  const pattern = /【([^】]+)】\s*\n?([\s\S]*?)(?=\n*【[^】]+】\s*$|\n*【[^】]+】\s*\n|$)/g;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(content)) !== null) {
    const speaker = match[1].trim();
    const text = match[2].trim();
    if (!text) {
      continue;
    }
    blocks.push({
      speaker,
      roleId: speakerToRole[speaker] ?? "",
      text
    });
  }
  return blocks;
}

function newsItemUrl(item: Record<string, unknown>): string {
  const value = item.canonical_url || item.resolved_link || item.link;
  return typeof value === "string" ? value : "";
}

function newsItemStatus(item: Record<string, unknown>): string {
  const status = typeof item.article_status === "string" ? item.article_status : "仅标题";
  const included = item.article_excerpt || String(status).startsWith("正文已读") ? "已进入摘要" : "标题级线索";
  return `${status} · ${included}`;
}

function NewsItemCard({ item, index }: { item: Record<string, unknown>; index: number }) {
  const url = newsItemUrl(item);
  const title = displayValue(item.title) || `来源 ${index + 1}`;
  return (
    <div className="news-item" key={`${title}-${index}`}>
      {url ? (
        <a href={url} rel="noreferrer" target="_blank">
          {title}
        </a>
      ) : (
        <strong>{title}</strong>
      )}
      <span>
        {displayValue(item.source)} · {displayValue(item.published_at)}
      </span>
      <small>{newsItemStatus(item)}</small>
    </div>
  );
}

function resultText(result: Record<string, unknown>): string {
  const text = result.text ?? result.content ?? result.message ?? result.preview;
  return typeof text === "string" ? text : JSON.stringify(result, null, 2);
}

function resultSpeaker(result: Record<string, unknown>): string {
  const speaker = result.speaker ?? result.role ?? result.name;
  return typeof speaker === "string" ? speaker : "群聊记录";
}

export function WechatPanel({
  wechat,
  newsResult,
  webLookup,
  useWebLookup,
  setUseWebLookup,
  wechatInput,
  setWechatInput,
  newsQuery,
  setNewsQuery,
  readArticles,
  setReadArticles,
  chatSettings,
  sessionId,
  onOpening,
  onReset,
  onMarkRead,
  onSendWechat,
  onStopWechat,
  onLookupNews,
  onNewsDiscussed,
  isWechatBusy,
  isNewsBusy
}: {
  wechat: WechatStateResponse | null;
  newsResult: NewsSearchResponse | null;
  webLookup: NewsLookupResponse | null;
  useWebLookup: boolean;
  setUseWebLookup: (value: boolean) => void;
  wechatInput: string;
  setWechatInput: (value: string) => void;
  newsQuery: string;
  setNewsQuery: (value: string) => void;
  readArticles: boolean;
  setReadArticles: (value: boolean) => void;
  chatSettings: ChatSettings;
  sessionId?: string;
  onOpening: () => void;
  onReset: () => void;
  onMarkRead: () => void;
  onSendWechat: (event: FormEvent) => void;
  onStopWechat?: () => void;
  onLookupNews: () => void;
  onNewsDiscussed: (sessionId: string) => void;
  isWechatBusy: boolean;
  isNewsBusy: boolean;
}) {
  const [wechatSearchQuery, setWechatSearchQuery] = useState("");
  const [wechatSearch, setWechatSearch] = useState<WechatSearchResponse | null>(null);
  const [isWechatSearching, setIsWechatSearching] = useState(false);
  const [wechatSearchError, setWechatSearchError] = useState("");

  // Clear search results when group content changes (new group / reset)
  useEffect(() => {
    setWechatSearch(null);
    setWechatSearchQuery("");
  }, [wechat?.content]);

  const latestNewsItems = newsResult?.news_items.slice(0, 4) ?? [];
  const latestLookupItems = webLookup?.news_items.slice(0, 4) ?? [];
  const wechatMessages = parseWechatMessages(wechat?.content ?? "");

  const handleWechatSearch = async (event: FormEvent) => {
    event.preventDefault();
    const keyword = wechatSearchQuery.trim();
    if (!keyword || isWechatSearching) {
      return;
    }
    setIsWechatSearching(true);
    setWechatSearchError("");
    try {
      setWechatSearch(await searchWechat(keyword));
    } catch (error) {
      setWechatSearch(null);
      setWechatSearchError(error instanceof Error ? error.message : "群聊搜索失败");
    } finally {
      setIsWechatSearching(false);
    }
  };

  return (
    <section className="panel" id="wechat">
      <div className="panel-header">
        <div>
          <h2>群聊与联网</h2>
          <span>{wechat ? `${wechat.message_count} 条消息 · 未读 ${wechat.unread_count}` : "等待 API"}</span>
        </div>
        <MessageSquare size={18} />
      </div>

      <div className="wechat-actions">
        <button className="ghost-action compact" disabled={isWechatBusy} onClick={onOpening} type="button">
          {isWechatBusy ? <Loader2 className="spin" size={14} /> : <Sparkles size={14} />}
          生成开场
        </button>
        <button className="ghost-action compact" disabled={isWechatBusy} onClick={onMarkRead} type="button">
          标记已读
        </button>
        <button className="ghost-action compact danger" disabled={isWechatBusy} onClick={onReset} type="button">
          新群聊
        </button>
      </div>

      <div className="wechat-thread">
        {wechatMessages.length ? (
          <div className="wechat-bubbles">
            {wechatMessages.map((message, index) => (
              <div className={`wechat-bubble ${message.roleId}`} key={`${message.speaker}-${index}`}>
                <RoleAvatar fallback={message.roleId === "user" ? "user" : "assistant"} roleId={message.roleId} />
                <div className="wechat-bubble-body">
                  <strong>{message.speaker}</strong>
                  <p>{message.text}</p>
                </div>
              </div>
            ))}
          </div>
        ) : wechat?.content ? (
          <pre>{wechat.content}</pre>
        ) : (
          <div className="empty-state">还没有群聊内容。先生成开场，或直接发送一句话。</div>
        )}
      </div>

      <form className="mini-form wechat-search-form" onSubmit={handleWechatSearch}>
        <label className="field-row">
          <span>搜索群聊记录</span>
          <input
            onChange={(event) => setWechatSearchQuery(event.target.value)}
            placeholder="例如：RAG、记忆闭环、某个角色说过的话"
            value={wechatSearchQuery}
          />
        </label>
        <button className="ghost-action compact lookup-action" disabled={isWechatSearching || !wechatSearchQuery.trim()} type="submit">
          {isWechatSearching ? <Loader2 className="spin" size={14} /> : <Search size={14} />}
          搜索群聊
        </button>
      </form>

      {wechatSearch ? (
        <div className="wechat-search-result">
          <div className="memory-preview-meta">
            <strong>命中 {wechatSearch.results.length} 条</strong>
            <span>关键词：{wechatSearch.keyword}</span>
          </div>
          {wechatSearch.results.length ? (
            <div className="wechat-search-list">
              {wechatSearch.results.map((result, index) => (
                <article className="wechat-search-item" key={`${wechatSearch.keyword}-${index}`}>
                  <strong>{resultSpeaker(result)}</strong>
                  <p>{resultText(result)}</p>
                  {typeof result.line === "number" || typeof result.score === "number" ? (
                    <span>
                      {typeof result.line === "number" ? `line ${result.line}` : ""}
                      {typeof result.line === "number" && typeof result.score === "number" ? " · " : ""}
                      {typeof result.score === "number" ? `score ${result.score.toFixed(3)}` : ""}
                    </span>
                  ) : null}
                </article>
              ))}
            </div>
          ) : (
            <div className="empty-state compact">没有找到匹配记录。</div>
          )}
        </div>
      ) : null}

      {wechatSearchError ? (
        <div className="memory-note warn">
          <AlertTriangle size={15} />
          <span>{wechatSearchError}</span>
        </div>
      ) : null}

      <form className="mini-form" onSubmit={onSendWechat}>
        <textarea
          onChange={(event) => setWechatInput(event.target.value)}
          placeholder="加入群聊说一句..."
          rows={3}
          value={wechatInput}
        />
        <div className="wechat-send-actions">
          <button className="primary-action secondary" disabled={isWechatBusy || !wechatInput.trim()} type="submit">
            {isWechatBusy ? <Loader2 className="spin" size={15} /> : <Send size={15} />}
            发送群聊
          </button>
          {isWechatBusy ? (
            <button className="ghost-action compact danger" onClick={(event) => { event.preventDefault(); onStopWechat?.(); }} type="button">
              停止
            </button>
          ) : null}
        </div>
      </form>

      <NewsWorkspace
        query={newsQuery}
        setQuery={setNewsQuery}
        readArticles={readArticles}
        setReadArticles={setReadArticles}
        chatSettings={chatSettings}
        sessionId={sessionId}
        onDiscussed={onNewsDiscussed}
        onLookupNews={onLookupNews}
        isLookupBusy={isNewsBusy}
      />

      {webLookup ? (
        <div className="news-result lookup-result">
          <label className="toggle-row">
            <input checked={useWebLookup} onChange={(event) => setUseWebLookup(event.target.checked)} type="checkbox" />
            <span>仅用于下一轮单人聊天</span>
          </label>
          <details open>
            <summary>单独联网结果 {webLookup.news_items.length} 条</summary>
            <div className="news-list">
              {latestLookupItems.map((item, index) => (
                <NewsItemCard item={item} index={index} key={`${displayValue(item.title)}-${index}`} />
              ))}
            </div>
          </details>
        </div>
      ) : null}

      {newsResult ? (
        <div className="news-result">
          <div className="metric-row">
            <span>耗时</span>
            <strong>{newsResult.elapsed_ms} ms</strong>
          </div>
          <details>
            <summary>新闻摘要</summary>
            <pre>{newsResult.digest}</pre>
          </details>
          <details>
            <summary>来源 {newsResult.news_items.length} 条</summary>
            <div className="news-list">
              {latestNewsItems.map((item, index) => (
                <NewsItemCard item={item} index={index} key={`${displayValue(item.title)}-${index}`} />
              ))}
            </div>
          </details>
          {newsResult.warnings.length ? (
            <div className="memory-note warn">
              <AlertTriangle size={15} />
              <span>{newsResult.warnings.join("；")}</span>
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
