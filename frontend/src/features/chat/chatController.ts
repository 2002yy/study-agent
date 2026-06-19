import { useCallback, type Dispatch, type SetStateAction } from "react";
import { operationRegistry } from "../../app/operationRegistry";
import { useWorkspace } from "../../app/WorkspaceProvider";
import type { StreamRecoveryState } from "../../app/workspaceReducer";
import type { ChatMessage, ChatResponse } from "../../types";

export function useChatController() {
  const { state, dispatch } = useWorkspace();

  const setMessages: Dispatch<SetStateAction<ChatMessage[]>> = useCallback(
    (value) => dispatch({ type: "SET_CHAT_MESSAGES", value }),
    [dispatch]
  );
  const setLastChat: Dispatch<SetStateAction<ChatResponse | null>> = useCallback(
    (value) => dispatch({ type: "SET_LAST_CHAT", value }),
    [dispatch]
  );
  const setStreamRecovery = useCallback(
    (value: StreamRecoveryState | null) => dispatch({ type: "SET_STREAM_RECOVERY", value }),
    [dispatch]
  );
  const setThreadId = useCallback(
    (threadId?: string) => dispatch({ type: "SET_ACTIVE_CHAT_THREAD", threadId }),
    [dispatch]
  );
  const transitionSession = useCallback(
    (
      threadId: string,
      messages: ChatMessage[],
      lastChat: ChatResponse | null,
      streamRecovery: StreamRecoveryState | null = null
    ) =>
      dispatch({
        type: "TRANSITION_CHAT_SESSION",
        threadId,
        messages,
        lastChat,
        streamRecovery
      }),
    [dispatch]
  );

  return {
    threadId: state.activeChatThreadId,
    messages: state.chatMessages,
    lastChat: state.lastChat,
    streamRecovery: state.streamRecovery,
    setMessages,
    setLastChat,
    setStreamRecovery,
    setThreadId,
    transitionSession,
    startOperation: () => operationRegistry.start("chat", state.activeChatThreadId),
    isCurrentOperation: (operationId: string, generationId: number) =>
      operationRegistry.isCurrent(operationId, generationId, state.activeChatThreadId),
    completeOperation: (operationId: string) => operationRegistry.complete(operationId),
    cancelOperation: () => operationRegistry.cancel("chat")
  };
}
