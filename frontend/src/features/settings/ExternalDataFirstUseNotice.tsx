import { ChevronDown, ShieldCheck, X } from "lucide-react";
import { useState } from "react";

export const EXTERNAL_DATA_NOTICE_KEY = "study-agent:external-data-notice:v1";

export function ExternalDataFirstUseNotice({
  webPolicy,
  cloudContextPolicy,
  onOpenSettings,
}: {
  webPolicy: string;
  cloudContextPolicy: string;
  onOpenSettings: () => void;
}) {
  const [open, setOpen] = useState(
    () => window.localStorage.getItem(EXTERNAL_DATA_NOTICE_KEY) !== "acknowledged",
  );

  const acknowledge = () => {
    window.localStorage.setItem(EXTERNAL_DATA_NOTICE_KEY, "acknowledged");
    setOpen(false);
  };

  if (!open) return null;

  return (
      <aside
        aria-labelledby="external-data-first-use-title"
        className="external-data-first-use"
      >
        <ShieldCheck aria-hidden="true" size={16} />
        <details className="external-data-first-use-copy">
          <summary id="external-data-first-use-title" aria-label="联网与模型上下文说明">
            <span>联网与上下文</span>
            <small>{webPolicy === "auto" ? "按需联网" : webPolicy === "ask" ? "联网前询问" : "联网已关闭"}</small>
            <ChevronDown size={13} aria-hidden="true" />
          </summary>
          <p>
            当前联网策略：{webPolicy === "auto" ? "任务需要时自动联网" : webPolicy === "ask" ? "每次联网前询问" : "关闭联网"}；
            模型上下文：
            {cloudContextPolicy === "question_only"
              ? "仅当前问题"
              : cloudContextPolicy === "recent_chat"
                ? "当前问题与最近对话"
                : "当前问题、最近对话及相关本地资料片段"}。每轮“证据轨迹”会显示实际数据类型、搜索词与搜索源，不展示本地正文。
          </p>
        </details>
        <div className="external-data-first-use-actions">
          <button
            className="ghost-action"
            aria-label="查看隐私设置"
            onClick={() => {
              acknowledge();
              onOpenSettings();
            }}
            type="button"
          >
            隐私设置
          </button>
          <button className="notice-dismiss" aria-label="我知道了" title="关闭提示" onClick={acknowledge} type="button">
            <X size={14} aria-hidden="true" />
          </button>
        </div>
      </aside>
  );
}
