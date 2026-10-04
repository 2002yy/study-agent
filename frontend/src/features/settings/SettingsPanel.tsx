import { useEffect, useRef, useState } from "react";
import { BookOpen, CheckCircle2, Database, Loader2, SearchCheck, Settings, SlidersHorizontal } from "lucide-react";

import { checkSearchProviderHealth, saveRuntimeSettings } from "../../api";
import { humanizeUiError, labelFor } from "../../utils/uiLabels";
import { RoleAvatar } from "../../components/RoleAvatar";
import { StatusDot } from "../../components/StatusDot";
import { roleLabel, roleOptions } from "../roles/roleCatalog";
import type {
  ApiSnapshot,
  ChatResponse,
  ChatSettings,
  RagSettings,
  RoleResponse,
  SearchProviderHealthItem,
  SearchProviderHealthResponse,
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

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

// G17: composer send-key layout, persisted in runtime settings.
function ComposerSendKeySettings({
  runtimeSettings,
  disabled,
  onSaved,
}: {
  runtimeSettings: unknown;
  disabled?: boolean;
  onSaved: () => Promise<void> | void;
}) {
  const settings = asRecord(asRecord(runtimeSettings).settings);
  const [enterToSend, setEnterToSend] = useState(true);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    setEnterToSend(settings.enter_to_send !== false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settings.enter_to_send]);

  const update = async (checked: boolean) => {
    setEnterToSend(checked);
    setIsSaving(true);
    try {
      await saveRuntimeSettings({ enter_to_send: checked });
      await onSaved();
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <section className="side-section" aria-labelledby="composer-key-settings">
      <div className="section-title" id="composer-key-settings">
        <Settings size={15} />
        输入与发送
      </div>
      <label className="toggle-row">
        <input
          checked={enterToSend}
          disabled={disabled || isSaving}
          onChange={(event) => void update(event.target.checked)}
          type="checkbox"
        />
        <span>按回车键发送消息</span>
      </label>
      <small className="field-hint">
        {enterToSend
          ? "当前：回车键发送，按住上档键再按回车键换行。"
          : "当前：控制键 + 回车键发送，回车键换行。"}
      </small>
    </section>
  );
}

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
  费曼: "先由你解释，模型定位理解缺口，再补充并让你重新说明。",
  项目: "围绕当前项目阶段给出最小修改、实施顺序、验证方式和主要风险。",
};

const modelOptions = [
  ["auto", "自动"],
  ["flash", "快速档"],
  ["pro", "高质量档"],
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
  isSending: boolean;
  refresh: () => Promise<void>;
  lastChat: ChatResponse | null;
};

const providerLabels: Record<string, string> = {
  searxng: "SearXNG",
  bing_rss: "Bing RSS",
  duckduckgo_html: "DuckDuckGo",
};

function providerSummary(health: SearchProviderHealthResponse): string {
  const preferred = health.providers.find((provider) => provider.role === "preferred");
  const fallbacks = health.providers
    .filter((provider) => provider.role !== "preferred" && provider.enabled)
    .map((provider) => labelFor(providerLabels, provider.name, "其他搜索源"));
  const fallbackText = fallbacks.length > 0 ? `；可尝试 ${fallbacks.join("、")} 降级` : "";

  if (health.status === "ready") {
    return "首选搜索源可用，可以正常联网检索。";
  }
  if (health.status === "unavailable") {
    return "联网搜索不可用，提问时会明确返回未使用联网来源。";
  }
  if (preferred?.reachable && preferred.search_capable === false) {
    return `SearXNG 服务在线，但搜索引擎没有返回有效结果${fallbackText}。`;
  }
  if (preferred?.enabled && preferred.configured && preferred.reachable === false) {
    return `SearXNG 当前不可达${fallbackText}。`;
  }
  return `首选搜索源未就绪${fallbackText}。`;
}

function providerStateLabel(provider: SearchProviderHealthItem): string {
  if (!provider.enabled) return "未启用";
  if (!provider.configured) return "配置不完整";
  if (provider.status === "ready") return "可用";
  if (provider.reachable && provider.search_capable === false) return "服务在线，搜索异常";
  if (provider.reachable === false) return "不可达";
  return provider.role === "preferred" ? "待确认" : "已启用（按需降级）";
}

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

  const [providerHealth, setProviderHealth] = useState<SearchProviderHealthResponse | null>(null);
  const [providerHealthError, setProviderHealthError] = useState("");
  const [isCheckingProviders, setIsCheckingProviders] = useState(false);
  const providerCheckController = useRef<AbortController | null>(null);

  useEffect(() => () => providerCheckController.current?.abort(), []);

  const handleProviderCheck = async () => {
    providerCheckController.current?.abort();
    const controller = new AbortController();
    providerCheckController.current = controller;
    setIsCheckingProviders(true);
    setProviderHealthError("");
    try {
      setProviderHealth(await checkSearchProviderHealth({ signal: controller.signal }));
    } catch (error) {
      if (!controller.signal.aborted) {
        setProviderHealth(null);
        setProviderHealthError(humanizeUiError(error, "联网搜索检测失败，请稍后重试。"));
      }
    } finally {
      if (providerCheckController.current === controller) {
        providerCheckController.current = null;
        setIsCheckingProviders(false);
      }
    }
  };

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
          <span>默认只显示影响学习方式、资料使用、隐私和互动感受的选项</span>
        </div>
        <Settings size={18} />
      </div>

      <section className="side-section" aria-labelledby="ordinary-learning-settings">
        <div className="section-title" id="ordinary-learning-settings">
          <BookOpen size={15} />
          学习体验
        </div>
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

      <ComposerSendKeySettings
        runtimeSettings={snapshot.runtimeSettings}
        disabled={isSending}
        onSaved={refresh}
      />

      <section className="side-section" aria-labelledby="ordinary-material-settings">
        <div className="section-title" id="ordinary-material-settings">
          <Database size={15} />
          我的资料
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
      </section>

      <ExternalDataPolicySettings
        runtimeSettings={snapshot.runtimeSettings}
        disabled={isSending}
        onSaved={refresh}
      />

      <details className="settings-advanced settings-advanced-main">
        <summary>
          <SlidersHorizontal size={15} />
          高级设置
        </summary>
        <p className="field-hint">这些选项用于固定角色、模型和检索参数。大多数学习任务保持自动即可。</p>

        <section className="side-section advanced-settings-section" aria-labelledby="advanced-conversation-settings">
          <div className="section-title" id="advanced-conversation-settings">角色与运行方式</div>
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
        </section>

        <section className="side-section advanced-settings-section" aria-labelledby="advanced-retrieval-settings">
          <div className="section-title" id="advanced-retrieval-settings">资料检索参数</div>
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
        </section>
      </details>

      <section className="side-section">
        <div className="status-line">
          <StatusDot tone={apiTone} />
          <span>
            {snapshot.health?.status === "ok" ? "服务已连接" : "服务未连接"}
            {lastChat ? " · 当前会话已有回答" : " · 尚未开始对话"}
          </span>
        </div>
        <div className="provider-health-card" aria-live="polite">
          <div className="provider-health-heading">
            <span>联网搜索</span>
            {providerHealth ? (
              <span className={`provider-health-badge ${providerHealth.status}`}>
                {providerHealth.status === "ready" ? "可用" : providerHealth.status === "degraded" ? "降级" : "不可用"}
              </span>
            ) : null}
          </div>
          {providerHealth ? (
            <>
              <p className="provider-health-summary">{providerSummary(providerHealth)}</p>
              <ul className="provider-health-list" aria-label="联网搜索源状态">
                {providerHealth.providers.map((provider) => (
                  <li key={provider.name}>
                    <span>{labelFor(providerLabels, provider.name, "其他搜索源")}</span>
                    <strong>{providerStateLabel(provider)}</strong>
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className="provider-health-summary">
              {providerHealthError ? "检测失败，联网搜索当前不可确认。" : "仅在点击时检查，不影响应用启动和聊天。"}
            </p>
          )}
          {providerHealthError ? <small className="provider-health-error" role="alert">{providerHealthError}</small> : null}
          <button
            className="ghost-action compact"
            disabled={isCheckingProviders}
            onClick={() => void handleProviderCheck()}
            type="button"
          >
            {isCheckingProviders ? <Loader2 className="spin" size={15} /> : <SearchCheck size={15} />}
            {isCheckingProviders ? "正在检测…" : "检测联网搜索"}
          </button>
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
