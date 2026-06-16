import { AlertTriangle, Loader2, MessageSquare, Search, Send, Sparkles } from "lucide-react";
import type { FormEvent } from "react";
import { RoleAvatar } from "../../components/RoleAvatar";
import type { NewsLookupResponse, NewsSearchResponse, WechatStateResponse } from "../../types";
import { displayValue } from "../../utils/format";
import { speakerToRole } from "../roles/roleCatalog";

export function parseWechatMessages(content: string): Array<{ speaker: string; roleId: string; text: string }> {
  const blocks: Array<{ speaker: string; roleId: string; text: string }> = [];
  const pattern = /【([^】]+)】\s*\n?([\s\S]*?)(?=\n*【[^】]+】|\s*$)/g;
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
  onOpening,
  onReset,
  onMarkRead,
  onSendWechat,
  onRunNews,
  onLookupNews,
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
  onOpening: () => void;
  onReset: () => void;
  onMarkRead: () => void;
  onSendWechat: (event: FormEvent) => void;
  onRunNews: (event: FormEvent) => void;
  onLookupNews: () => void;
  isWechatBusy: boolean;
  isNewsBusy: boolean;
}) {
  const latestNewsItems = newsResult?.news_items.slice(0, 4) ?? [];
  const latestLookupItems = webLookup?.news_items.slice(0, 4) ?? [];
  const wechatMessages = parseWechatMessages(wechat?.content ?? "");
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

      <form className="mini-form" onSubmit={onSendWechat}>
        <textarea
          onChange={(event) => setWechatInput(event.target.value)}
          placeholder="加入群聊说一句..."
          rows={3}
          value={wechatInput}
        />
        <button className="primary-action secondary" disabled={isWechatBusy || !wechatInput.trim()} type="submit">
          {isWechatBusy ? <Loader2 className="spin" size={15} /> : <Send size={15} />}
          发送群聊
        </button>
      </form>

      <form className="mini-form news-form" onSubmit={onRunNews}>
        <label className="field-row">
          <span>联网检索</span>
          <input onChange={(event) => setNewsQuery(event.target.value)} placeholder="最新新闻 when:1d" value={newsQuery} />
        </label>
        <label className="toggle-row">
          <input checked={readArticles} onChange={(event) => setReadArticles(event.target.checked)} type="checkbox" />
          <span>尝试读取正文</span>
        </label>
        <button className="primary-action secondary" disabled={isNewsBusy || !newsQuery.trim()} type="submit">
          {isNewsBusy ? <Loader2 className="spin" size={15} /> : <Search size={15} />}
          联网查并讨论
        </button>
        <button className="ghost-action compact lookup-action" disabled={isNewsBusy || !newsQuery.trim()} onClick={onLookupNews} type="button">
          仅搜索，用于单人聊天
        </button>
      </form>

      {webLookup ? (
        <div className="news-result lookup-result">
          <label className="toggle-row">
            <input checked={useWebLookup} onChange={(event) => setUseWebLookup(event.target.checked)} type="checkbox" />
            <span>用于下一次单人聊天</span>
          </label>
          <details open>
            <summary>单独联网结果 {webLookup.news_items.length} 条</summary>
            <div className="news-list">
              {latestLookupItems.map((item, index) => (
                <div className="news-item" key={`${displayValue(item.title)}-${index}`}>
                  <strong>{displayValue(item.title)}</strong>
                  <span>
                    {displayValue(item.source)} · {displayValue(item.published_at)}
                  </span>
                </div>
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
                <div className="news-item" key={`${displayValue(item.title)}-${index}`}>
                  <strong>{displayValue(item.title)}</strong>
                  <span>
                    {displayValue(item.source)} · {displayValue(item.published_at)}
                  </span>
                </div>
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
