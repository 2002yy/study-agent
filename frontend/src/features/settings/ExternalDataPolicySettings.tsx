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

type WebPolicy = (typeof WEB_OPTIONS)[number][0];
type CloudContextPolicy = (typeof CONTEXT_OPTIONS)[number][0];

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function normalizeWebPolicy(value: unknown): WebPolicy {
  return WEB_OPTIONS.some(([option]) => option === value) ? (value as WebPolicy) : "auto";
}

function normalizeCloudContextPolicy(value: unknown): CloudContextPolicy {
  return CONTEXT_OPTIONS.some(([option]) => option === value)
    ? (value as CloudContextPolicy)
    : "allow_local_evidence";
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
  const [webPolicy, setWebPolicy] = useState<WebPolicy>("auto");
  const [cloudContextPolicy, setCloudContextPolicy] =
    useState<CloudContextPolicy>("allow_local_evidence");
  const [isSaving, setIsSaving] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    setWebPolicy(normalizeWebPolicy(settings.web_policy));
    setCloudContextPolicy(normalizeCloudContextPolicy(settings.cloud_context_policy));
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
          onChange={(event) => setWebPolicy(normalizeWebPolicy(event.target.value))}
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
          onChange={(event) =>
            setCloudContextPolicy(normalizeCloudContextPolicy(event.target.value))
          }
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
