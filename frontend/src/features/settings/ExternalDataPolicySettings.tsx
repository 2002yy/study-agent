import { humanizeUiError } from "../../utils/uiLabels";
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

// G16 decision 1: independent read gate for cross-session memory.
const MEMORY_OPTIONS = [
  ["off", "不使用记忆"],
  ["ask", "每次会话询问"],
  ["auto", "自动使用"],
] as const;

// G18 decision 4: deep-research auto-escalation sensitivity.
const DEEP_SENSITIVITY_OPTIONS = [
  ["conservative", "保守（仅明确要求时深度调研）"],
  ["balanced", "平衡"],
  ["eager", "积极"],
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

type MemoryPolicy = (typeof MEMORY_OPTIONS)[number][0];

function normalizeMemoryPolicy(value: unknown): MemoryPolicy {
  return MEMORY_OPTIONS.some(([option]) => option === value)
    ? (value as MemoryPolicy)
    : "auto";
}

function normalizeDeepSensitivity(value: unknown) {
  return DEEP_SENSITIVITY_OPTIONS.some(([option]) => option === value)
    ? (value as (typeof DEEP_SENSITIVITY_OPTIONS)[number][0])
    : "balanced";
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
  const [memoryPolicy, setMemoryPolicy] = useState<MemoryPolicy>("auto");
  const [deepSensitivity, setDeepSensitivity] =
    useState("balanced" as (typeof DEEP_SENSITIVITY_OPTIONS)[number][0]);
  // G14 gate 6: independent image-understanding authorization.
  const [visionEnabled, setVisionEnabled] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    setWebPolicy(normalizeWebPolicy(settings.web_policy));
    setCloudContextPolicy(normalizeCloudContextPolicy(settings.cloud_context_policy));
    setMemoryPolicy(normalizeMemoryPolicy(settings.memory_policy));
    setDeepSensitivity(normalizeDeepSensitivity(settings.deep_research_sensitivity));
    setVisionEnabled(Boolean(settings.attachment_vision_enabled));
  }, [settings.web_policy, settings.cloud_context_policy]);

  const save = async () => {
    setIsSaving(true);
    setMessage("");
    try {
      await saveRuntimeSettings({
        web_policy: webPolicy,
        cloud_context_policy: cloudContextPolicy,
        memory_policy: memoryPolicy,
        deep_research_sensitivity: deepSensitivity,
        attachment_vision_enabled: visionEnabled,
      });
      await onSaved();
      setMessage("外发数据策略已保存");
    } catch (error) {
      setMessage(humanizeUiError(error, "策略保存失败，请稍后重试。"));
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
      <label className="field-row">
        <span>跨会话记忆</span>
        <select
          disabled={disabled || isSaving}
          onChange={(event) =>
            setMemoryPolicy(normalizeMemoryPolicy(event.target.value))
          }
          value={memoryPolicy}
        >
          {MEMORY_OPTIONS.map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>
      </label>
      <small className="field-hint">
        控制长期记忆（如学习者画像）进入回答上下文。“每次会话询问”会在新会话首次使用前确认，且需同时允许本地资料片段。
      </small>
      <label className="field-row">
        <span>深度调研灵敏度</span>
        <select
          disabled={disabled || isSaving}
          onChange={(event) =>
            setDeepSensitivity(
              normalizeDeepSensitivity(event.target.value),
            )
          }
          value={deepSensitivity}
        >
          {DEEP_SENSITIVITY_OPTIONS.map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>
      </label>
      <small className="field-hint">
        控制复杂问题自动进入深度调研的频率；“保守”只在明确要求时触发。
      </small>
      <label className="toggle-row">
        <input
          checked={visionEnabled}
          disabled={disabled || isSaving}
          onChange={(event) => setVisionEnabled(event.target.checked)}
          type="checkbox"
        />
        <span>允许云端图片理解（临时附件）</span>
      </label>
      <small className="field-hint">
        默认关闭：图片附件只保存不解析。开启后，上传的图片会发送给
        DeepSeek 视觉模型生成文字描述用于检索，每次调用都会记录审计。
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
