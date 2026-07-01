import { useState } from "react";

import { saveRuntimeSettings } from "../../api";
import { serverQueryCache } from "../../app/serverQueryCache";
import type { ChatSettings, RagSettings, RuntimeSettingsResponse } from "../../types";

export function useSettingsController(options: {
  chatSettings: ChatSettings;
  ragSettings: RagSettings;
  ragEnabled: boolean;
  setRuntimeSettings: (value: RuntimeSettingsResponse) => void;
  setOperationError: (value: string) => void;
  refresh: () => Promise<void>;
}) {
  const [isSaving, setIsSaving] = useState(false);
  const save = async () => {
    setIsSaving(true);
    options.setOperationError("");
    try {
      const response = await saveRuntimeSettings({
        selected_role: options.chatSettings.selectedRole,
        selected_mode: options.chatSettings.selectedMode,
        selected_model: options.chatSettings.selectedModel,
        relationship_mode: options.chatSettings.relationshipMode,
        performance_mode:
          options.chatSettings.contextMode === "fast"
            ? "fast"
            : options.chatSettings.contextMode === "deep"
              ? "deep"
              : options.chatSettings.contextMode === "light"
                ? "standard"
                : undefined,
        rag_enabled: options.ragEnabled,
        rag_retrieval_mode: options.ragSettings.retrievalMode,
        rag_search_top_k: options.ragSettings.topK,
        rag_chat_top_k: options.ragSettings.chatTopK,
        rag_min_score: options.ragSettings.minScore,
      });
      options.setRuntimeSettings(response);
      serverQueryCache.invalidate("snapshot");
      await options.refresh();
    } catch (error) {
      options.setOperationError(
        `设置保存失败：${error instanceof Error ? error.message : "设置保存失败"}`
      );
    } finally {
      setIsSaving(false);
    }
  };
  return { isSaving, save };
}
