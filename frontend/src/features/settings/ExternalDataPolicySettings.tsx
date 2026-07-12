import { CheckCircle2, Loader2, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";

import { saveRuntimeSettings } from "../../api";

const WEB_OPTIONS = [
  ["off", "关闭联网"],
  ["ask", "每次询问"],
  ["auto", "自动联网"],
] as const;

const CONTEXT_OPTIONS = [
  ["question_only", "仅当前问题"],
  ["recent_chat", "最近对话"],
  ["allow_local_evidence", "允许本地资料片段"],
] as const;

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

export function ExternalDataPolicySettings({
  runtimeSettings,
  disabled,
  onSaved,
}: {
  runtimeSettings: unknown;
  disabled?: boolean;
  onSaved: () => Promise<void> | void;
}) {
  const settings = asRecord(asRecord(runtimeSettings).settings);
  const [webPolicy, setWebPolicy] = useState("auto");
  const [cloudContextPolicy, setCloudContextPolicy] = useState("allow_local_evidence");
  const [isSaving, setIsSaving] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    setWebPolicy(String(settings.web_policy ?? "auto"));
    setCloudContextPolicy(
      String(settings.cloud_context_policy ?? "allow_local_evidence")
    );
  }, [settings.web_policy, settings.cloud_context_policy]);

  const save = async () => {
    setIsSaving(true);
    setMessage("");
    try {
      await saveRuntimeSettings({
        web_policy: webPolicy,
        cloud_context_policy: cloudContextPolicy,
      });
      await onSaved();
      setMessage("外发数据策略已保存");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "策略保存失败");
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <section className="side-section external-data-settings">
      <div className="section-title">
        <ShieldCheck size={15} />
        外发数据与联网
      </div>
      <label className="field-row">
        <span>联网策略</span>
        <select
          disabled={disabled || isSaving}
          onChange={(event) => setWebPolicy(event.target.value)}
          value={webPolicy}
        >
          {WEB_OPTIONS.map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>
      </label>
      <small className="field-hint">
        “每次询问”会在发送前确认；关闭后模型不会启动联网搜索。
      </small>
      <label className="field-row">
        <span>模型上下文</span>
        <select
          disabled={disabled || isSaving}
          onChange={(event) => setCloudContextPolicy(event.target.value)}
          value={cloudContextPolicy}
        >
          {CONTEXT_OPTIONS.map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>
      </label>
      <small className="field-hint">
        “仅当前问题”不发送历史、长期记忆或本地检索片段；“最近对话”仍不发送本地资料。
      </small>
      <button
        className="primary-action secondary"
        disabled={disabled || isSaving}
        onClick={() => void save()}
        type="button"
      >
        {isSaving ? <Loader2 className="spin" size={16} /> : <CheckCircle2 size={16} />}
        保存外发策略
      </button>
      {message ? <small className="field-hint">{message}</small> : null}
    </section>
  );
}
