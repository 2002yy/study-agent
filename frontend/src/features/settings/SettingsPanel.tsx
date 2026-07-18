import { BookOpen, CheckCircle2, Database, Loader2, Settings } from "lucide-react";

import { RoleAvatar } from "../../components/RoleAvatar";
import { StatusDot } from "../../components/StatusDot";
import { roleLabel, roleOptions } from "../roles/roleCatalog";
import type {
  ApiSnapshot,
  ChatResponse,
  ChatSettings,
  RagSettings,
  RoleResponse,
} from "../../types";
import { ExternalDataPolicySettings } from "./ExternalDataPolicySettings";

export const CHAT_SETTINGS_DEFAULTS: ChatSettings = {
  selectedRole: "auto",
  selectedMode: "auto",
  selectedModel: "auto",
  relationshipMode: "standard",
  contextMode: "",
};

export const RAG_SETTINGS_DEFAULTS: RagSettings = {
  retrievalMode: "hybrid",
  topK: 5,
  minScore: 0.01,
  chatTopK: 3,
};

const roleDescriptions: Record<string, string> = {
  auto: "后端根据问题自动选择合适角色。",
  march7: "更轻快、鼓励式的学习伙伴。",
  keqing: "偏执行、判断和推进项目。",
  nahida: "偏概念解释、连接知识脉络。",
  firefly: "偏陪伴、感受整理和收束。",
};

export const modeOptions = [
  ["auto", "自动"],
  ["普通", "直接讲解"],
  ["苏格拉底", "苏格拉底"],
  ["费曼", "费曼"],
  ["项目", "项目推进"],
] as const;

const modeDescriptions: Record<string, string> = {
  auto: "根据学习行为选择协议；需要直接解释时不会强制进入提问流程。",
  普通: "直接、完整地回答当前问题；必要时才澄清。",
  苏格拉底: "通过问题、反例和有限线索帮助你完成关键推理。",
  费曼: "先由你解释，AI定位理解缺口，再补充并让你重新说明。",
  项目: "围绕当前项目阶段给出最小修改、实施顺序、验证方式和主要风险。",
};

const modelOptions = [
  ["auto", "自动"],
  ["flash", "Flash"],
  ["pro", "Pro"],
] as const;

const modelDescriptions: Record<string, string> = {
  auto: "按当前任务自动选择模型。",
  flash: "响应更快，适合日常问答和轻量检索。",
  pro: "质量更高，适合复杂分析和长上下文。",
};

const contextModeOptions = [
  ["", "自动"],
  ["fast", "快速"],
  ["light", "标准"],
  ["deep", "深度"],
] as const;

const contextModeDescriptions: Record<string, string> = {
  "": "沿用系统当前运行档位。",
  fast: "优先速度，减少上下文和输出预算。",
  light: "平衡速度和质量，适合大多数学习对话。",
  deep: "读取更多上下文，适合复杂问题和复盘。",
};

const relationshipOptions = [
  ["standard", "自然"],
  ["warm", "温和"],
  ["close", "贴近"],
] as const;

const relationshipDescriptions: Record<string, string> = {
  standard: "自然克制，保持学习导向。",
  warm: "更鼓励、更柔和，但仍然聚焦任务。",
  close: "更有陪伴感，适合复盘和情绪整理。",
};

const retrievalOptions = [
  ["lexical", "关键词"],
  ["hybrid", "混合"],
  ["vector", "本地语义"],
  ["backend_vector", "增强语义"],
] as const;

const retrievalDescriptions: Record<string, string> = {
  lexical: "按关键词命中，稳定、可解释。",
  hybrid: "关键词和语义检索结合，通常最稳妥。",
  vector: "使用本地语义检索。",
  backend_vector: "使用当前可用的增强语义检索能力。",
};

type SettingsPanelProps = {
  snapshot: ApiSnapshot;
  ragEnabled: boolean;
  ragUploadMode: "upload" | "rebuild";
  setRagUploadMode: (mode: "upload" | "rebuild") => void;
  setRagEnabled: (value: boolean) => void;
  chatSettings: ChatSettings;
  setChatSettings: (value: ChatSettings) => void;
  ragSettings: RagSettings;
  setRagSettings: (value: RagSettings) => void;
  onSaveSettings: () => void;
  isSavingSettings: boolean;
  onLoadRole: () => void;
  roleDetail: RoleResponse | null;
  keepCurrentRole: boolean;
  setKeepCurrentRole: (value: boolean) => void;
  conversationInstruction: string;
  setConversationInstruction: (value: string) => void;
  onNewSession: () => void;
  isSending: boolean;
  refresh: () => Promise<void>;
  onUploadClick: () => void;
  uploadState: string;
  lastChat: ChatResponse | null;
};

export function SettingsPanel(props: SettingsPanelProps) {
  const {
    snapshot,
    ragEnabled,
    setRagEnabled,
    chatSettings,
    setChatSettings,
    ragSettings,
    setRagSettings,
    onSaveSettings,
    isSavingSettings,
    onLoadRole,
    roleDetail,
    keepCurrentRole,
    setKeepCurrentRole,
    conversationInstruction,
    setConversationInstruction,
    isSending,
    refresh,
    lastChat,
  } = props;

  const apiTone = snapshot.health?.status === "ok" ? "good" : snapshot.error ? "bad" : "neutral";
  const updateChatSetting = (key: keyof ChatSettings, value: string) => {
    setChatSettings({ ...chatSettings, [key]: value });
  };
  const updateRagSetting = <K extends keyof RagSettings>(key: K, value: RagSettings[K]) => {
    setRagSettings({ ...ragSettings, [key]: value });
  };

  return (
    <section className="settings-panel" aria-label="学习设置">
      <div className="panel-header">
        <div>
          <h2>设置</h2>
          <span>只保留会影响学习体验、资料使用和隐私的选项</span>
        </div>
        <Settings size={18} />
      </div>

      <section className="side-section">
        <div className="section-title">
          <BookOpen size={15} />
          学习体验
        </div>
        <label className="field-row">
          <span>角色</span>
          <select
            disabled={isSending}
            value={chatSettings.selectedRole}
            onChange={(event) => updateChatSetting("selectedRole", event.target.value)}
          >
            {roleOptions.map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </label>
        <small className="field-hint">{roleDescriptions[chatSettings.selectedRole]}</small>
        <div className="role-current">
          <RoleAvatar fallback="assistant" roleId={chatSettings.selectedRole} />
          <div>
            <strong>{roleLabel(chatSettings.selectedRole)}</strong>
            <span>{chatSettings.selectedRole === "auto" ? "按当前学习任务自动选择" : "当前手动指定角色"}</span>
          </div>
        </div>
        <button
          aria-pressed={keepCurrentRole}
          className={`ghost-action compact ${keepCurrentRole ? "active" : ""}`}
          disabled={chatSettings.selectedRole !== "auto" || isSending}
          onClick={() => setKeepCurrentRole(!keepCurrentRole)}
          type="button"
        >
          强制保持当前角色
        </button>
        <label className="field-row">
          <span>本会话微调</span>
          <textarea
            className="session-instruction"
            disabled={isSending}
            onChange={(event) => setConversationInstruction(event.target.value)}
            placeholder="例如：这次更重视原理推导，不要过快给结论。"
            rows={3}
            value={conversationInstruction}
          />
        </label>
        <small className="field-hint">只影响当前会话，不修改角色原始人设或全局默认。</small>
        {chatSettings.selectedRole !== "auto" ? (
          <button className="ghost-action compact" onClick={onLoadRole} type="button">
            <BookOpen size={15} />
            查看角色人设
          </button>
        ) : null}
        {roleDetail && roleDetail.id === chatSettings.selectedRole ? (
          <div className="role-preview">
            <strong>{roleDetail.label}</strong>
            <p>{roleDetail.description || roleDetail.summary}</p>
            <details>
              <summary>完整提示词</summary>
              <pre>{roleDetail.prompt}</pre>
            </details>
          </div>
        ) : null}

        <label className="field-row">
          <span>学习方式</span>
          <select
            disabled={isSending}
            value={chatSettings.selectedMode}
            onChange={(event) => updateChatSetting("selectedMode", event.target.value)}
          >
            {modeOptions.map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </label>
        <small className="field-hint">{modeDescriptions[chatSettings.selectedMode]}</small>

        <label className="field-row">
          <span>模型档位</span>
          <select
            disabled={isSending}
            value={chatSettings.selectedModel}
            onChange={(event) => updateChatSetting("selectedModel", event.target.value)}
          >
            {modelOptions.map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </label>
        <small className="field-hint">{modelDescriptions[chatSettings.selectedModel]}</small>

        <label className="field-row">
          <span>上下文深度</span>
          <select
            disabled={isSending}
            value={chatSettings.contextMode}
            onChange={(event) => updateChatSetting("contextMode", event.target.value)}
          >
            {contextModeOptions.map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </label>
        <small className="field-hint">{contextModeDescriptions[chatSettings.contextMode]}</small>

        <label className="field-row">
          <span>互动氛围</span>
          <select
            disabled={isSending}
            value={chatSettings.relationshipMode}
            onChange={(event) => updateChatSetting("relationshipMode", event.target.value)}
          >
            {relationshipOptions.map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </label>
        <small className="field-hint">{relationshipDescriptions[chatSettings.relationshipMode]}</small>
      </section>

      <section className="side-section">
        <div className="section-title">
          <Database size={15} />
          资料辅助
        </div>
        <label className="toggle-row">
          <input
            checked={ragEnabled}
            disabled={isSending}
            onChange={(event) => setRagEnabled(event.target.checked)}
            type="checkbox"
          />
          <span>回答时使用我的资料</span>
        </label>
        <small className="field-hint">开启后会按需检索已上传资料；关闭后只使用当前对话和模型知识。</small>

        <details className="settings-advanced">
          <summary>高级检索设置</summary>
          <small className="field-hint">大多数情况下保持默认即可。这些设置只影响资料检索范围，不改变学习目标。</small>
          <label className="field-row">
            <span>检索方式</span>
            <select
              disabled={isSending}
              value={ragSettings.retrievalMode}
              onChange={(event) => updateRagSetting("retrievalMode", event.target.value as RagSettings["retrievalMode"])}
            >
              {retrievalOptions.map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </label>
          <small className="field-hint">{retrievalDescriptions[ragSettings.retrievalMode]}</small>
          <div className="number-grid">
            <label className="field-row compact">
              <span>候选来源</span>
              <input
                min={1}
                max={20}
                disabled={isSending}
                onChange={(event) => updateRagSetting("topK", Number(event.target.value))}
                type="number"
                value={ragSettings.topK}
              />
            </label>
            <label className="field-row compact">
              <span>回答引用</span>
              <input
                disabled={isSending}
                min={1}
                max={20}
                onChange={(event) => updateRagSetting("chatTopK", Number(event.target.value))}
                type="number"
                value={ragSettings.chatTopK}
              />
            </label>
          </div>
          <label className="field-row">
            <span>最低相关度</span>
            <input
              min={0}
              disabled={isSending}
              onChange={(event) => updateRagSetting("minScore", Number(event.target.value))}
              step={0.01}
              type="number"
              value={ragSettings.minScore}
            />
          </label>
        </details>
      </section>

      <ExternalDataPolicySettings
        runtimeSettings={snapshot.runtimeSettings}
        disabled={isSending}
        onSaved={refresh}
      />

      <section className="side-section">
        <div className="status-line">
          <StatusDot tone={apiTone} />
          <span>
            {snapshot.health?.status === "ok" ? "服务已连接" : "服务未连接"}
            {lastChat ? " · 当前会话已有回答" : " · 尚未开始对话"}
          </span>
        </div>
        <button
          className="primary-action secondary"
          disabled={isSending || isSavingSettings}
          onClick={onSaveSettings}
          type="button"
        >
          {isSavingSettings ? <Loader2 className="spin" size={16} /> : <CheckCircle2 size={16} />}
          设为全局默认
        </button>
        <small className="field-hint">当前选择会立即影响本会话；保存后用于后续新会话。</small>
      </section>
    </section>
  );
}
