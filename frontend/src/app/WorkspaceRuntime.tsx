import { useRef, useState } from "react";
import { FireflyLessonProvider } from "../features/learning/FireflyLessonContext";
import { useWorkspace } from "./WorkspaceProvider";
import { useWorkspaceBootstrap } from "./WorkspaceBootstrap";
import { useEvidenceRuntime } from "./useEvidenceRuntime";
import { useExtensionRuntime } from "./useExtensionRuntime";
import { useLearningSessionRuntime } from "./useLearningSessionRuntime";
import { useWorkspaceControllers } from "./useWorkspaceControllers";
import { useWorkspaceRecovery } from "./useWorkspaceRecovery";
import { WorkspaceView } from "./WorkspaceView";

export default function WorkspaceRuntime() {
  const { snapshot, setSnapshot, refresh, loadFeature } = useWorkspaceBootstrap();
  const { state: workspaceRuntime } = useWorkspace();
  const [input, setInput] = useState("");
  const [operationError, setOperationError] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  const evidence = useEvidenceRuntime({
    refresh,
    loadFeature,
    input,
    activeChatThreadId: workspaceRuntime.activeChatThreadId,
    setOperationError,
  });
  const webPolicy = String(
    snapshot.runtimeSettings?.settings?.web_policy ?? "auto",
  );
  // G16 decision 1: memory ask policy from runtime settings; availability
  // from the memory status file list. Consent state is resolved per-send
  // by the controller against the backend (authoritative source).
  const memoryPolicy = String(
    snapshot.runtimeSettings?.settings?.memory_policy ?? "auto",
  );
  const memoryAvailable = (snapshot.memoryStatus?.files ?? []).length > 0;
  const learning = useLearningSessionRuntime({
    refresh,
    sessions: snapshot.sessions,
    setInput,
    setOperationError,
    evidence: evidence.learning,
    webPolicy,
    memoryPolicy,
    memoryAvailable,
  });
  const extension = useExtensionRuntime({
    snapshot,
    setSnapshot,
    refresh,
    loadFeature,
    input,
    operationError: setOperationError,
    lastRagQuery: learning.chatController.lastChat?.rag?.query,
    chatSettings: learning.chatSettings,
    ragSettings: evidence.ragSettings,
    ragEnabled: evidence.ragEnabled,
    webLookup: {
      result: evidence.webLookupController.result,
      useInChat: evidence.webLookupController.useInChat,
      setUseInChat: evidence.webLookupController.setUseInChat,
    },
  });
  const controllers = useWorkspaceControllers({
    setSnapshot,
    refresh,
    loadFeature,
    operationError: setOperationError,
    evidence,
    learning,
    extension,
  });

  useWorkspaceRecovery({
    evidence: evidence.recovery,
    learning: learning.recovery,
    extension: extension.recovery,
    snapshot,
  });

  return (
    <FireflyLessonProvider controller={learning.fireflyLesson}>
      <WorkspaceView
        snapshot={snapshot}
        refresh={refresh}
        fileInputRef={fileInputRef}
        controllers={controllers}
        learningView={learning.view}
        extensionView={extension.view}
        ui={{
          input,
          setInput,
          ragEnabled: evidence.ragEnabled,
          setRagEnabled: evidence.setRagEnabled,
          chatSettings: learning.chatSettings,
          setChatSettings: learning.setChatSettings,
          ragSettings: evidence.ragSettings,
          setRagSettings: evidence.setRagSettings,
          keepCurrentRole: learning.keepCurrentRole,
          setKeepCurrentRole: learning.setKeepCurrentRole,
          conversationInstruction: learning.conversationInstruction,
          setConversationInstruction: learning.setConversationInstruction,
          operationError,
          setOperationError,
        }}
      />
    </FireflyLessonProvider>
  );
}
