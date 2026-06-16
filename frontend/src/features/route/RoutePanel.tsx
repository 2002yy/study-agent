import { Activity } from "lucide-react";
import type { ChatResponse } from "../../types";
import { displayValue, translateStatus } from "../../utils/format";

export function RoutePanel({ lastChat }: { lastChat: ChatResponse | null }) {
  const routeRows: Array<[string, unknown]> = [
    ["实际角色", lastChat?.route.role],
    ["实际模式", lastChat?.route.mode],
    ["实际模型", lastChat?.route.model_profile],
    ["人工覆盖", lastChat?.route.manual_override],
    ["置信度", lastChat?.route.confidence],
    ["命中关键词", lastChat?.route.matched_keywords],
    ["LLM 路由", lastChat?.route.llm_router_used],
    ["路由原因", lastChat?.route.reason]
  ];
  return (
    <section className="panel" id="route">
      <div className="panel-header">
        <div>
          <h2>回答检查器</h2>
          <span>{lastChat ? `Session ${lastChat.session_id}` : "等待第一轮回答"}</span>
        </div>
        <Activity size={18} />
      </div>
      {lastChat ? (
        <div className="route-grid">
          {routeRows.map(([label, value]) => (
            <div className="metric-row" key={label}>
              <span>{label}</span>
              <strong title={displayValue(value)}>{displayValue(value)}</strong>
            </div>
          ))}
          <div className="metric-row">
            <span>RAG 状态</span>
            <strong>{translateStatus(lastChat.rag?.status)}</strong>
          </div>
          <div className="metric-row">
            <span>引用数量</span>
            <strong>{lastChat.rag?.result_count ?? 0}</strong>
          </div>
        </div>
      ) : (
        <div className="empty-state">发送一条消息后，这里会展示后端返回的角色、模式、模型、路由原因和 RAG 状态。</div>
      )}
    </section>
  );
}
