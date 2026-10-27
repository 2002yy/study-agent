import { KeyRound } from "lucide-react";
import { useState } from "react";
import { clearAuthRequired } from "../../apiAuthState";
import { apiToken, setApiToken } from "../../apiToken";

/**
 * Where the operator pastes the server's `STUDY_AGENT_API_TOKEN`.
 *
 * The value lives in this browser only: it is never compiled into the bundle,
 * never fetched from the server, and never written into the shared settings
 * file. Without it every private request answers 401, so this field is the
 * documented way out of a locked deployment.
 */
export function ApiTokenSettings({ onSaved }: { onSaved?: () => void } = {}) {
  const [draft, setDraft] = useState(apiToken);
  const [saved, setSaved] = useState(() => Boolean(apiToken()));

  const save = () => {
    setApiToken(draft);
    const stored = apiToken();
    setDraft(stored);
    setSaved(Boolean(stored));
    // A 401 left the workspace locked; saving clears the notice and the refresh
    // below reloads the data without asking the user to reload the page.
    if (stored) clearAuthRequired();
    onSaved?.();
  };

  const clear = () => {
    setApiToken("");
    setDraft("");
    setSaved(false);
    onSaved?.();
  };

  return (
    <section className="side-section" aria-labelledby="api-token-settings">
      <div className="section-title" id="api-token-settings">
        <KeyRound size={15} />
        访问令牌
      </div>
      <label className="field-row">
        <span>API 令牌</span>
        <input
          aria-label="API 令牌"
          type="password"
          autoComplete="off"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        />
      </label>
      <div className="field-row">
        <button
          className="ghost-action"
          type="button"
          onClick={save}
          disabled={draft.trim() === apiToken()}
        >
          保存令牌
        </button>
        <button
          className="ghost-action"
          type="button"
          onClick={clear}
          disabled={!saved && !draft}
        >
          清除令牌
        </button>
      </div>
      <small className="field-hint">
        {saved
          ? "令牌已保存在本机浏览器，只会随请求发送给本服务。"
          : "未设置。服务端设置 STUDY_AGENT_API_TOKEN 后，在这里填入同一个值；未设置时所有私有接口返回 401。"}
      </small>
    </section>
  );
}
