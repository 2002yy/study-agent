import { useState, type FormEvent } from "react";

import {
  createWechatOpening,
  markWechatRead,
  resetWechat,
  sendWechatMessageStream,
} from "../../api";
import { operationRegistry } from "../../app/operationRegistry";
import { useWorkspace } from "../../app/WorkspaceProvider";
import type {
  ChatSettings,
  RagSettings,
  WechatStateResponse,
} from "../../types";

type GroupControllerOptions = {
  wechat: WechatStateResponse | null;
  setWechat: (wechat: WechatStateResponse) => void;
  chatSettings: ChatSettings;
  ragSettings: RagSettings;
  ragEnabled: boolean;
  clearAssociatedNews: () => void;
};

export function useGroupChatController(options: GroupControllerOptions) {
  const { state, dispatch } = useWorkspace();
  const [input, setInput] = useState("");
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState("");
  const threadId = state.activeGroupThreadId ?? options.wechat?.group_thread_id;

  const setThreadId = (next?: string) =>
    dispatch({ type: "SET_ACTIVE_GROUP_THREAD", threadId: next });

  const opening = async () => {
    if (isBusy) return;
    if ((options.wechat?.message_count ?? 0) > 0) {
      setError("群聊已有历史内容，请先使用「新群聊」。");
      return;
    }
    setIsBusy(true);
    setError("");
    try {
      const wechat = await createWechatOpening(options.chatSettings, threadId);
      setThreadId(wechat.group_thread_id);
      options.setWechat(wechat);
    } catch (caught) {
      setError(`微信群开场生成失败：${messageOf(caught)}`);
    } finally {
      setIsBusy(false);
    }
  };

  const reset = async () => {
    if (isBusy) return;
    const count = options.wechat?.message_count ?? 0;
    const confirmed = window.confirm(
      count > 0
        ? `当前群聊有 ${count} 条消息，将先归档再创建新群聊。继续吗？`
        : "创建一个新的空群聊？"
    );
    if (!confirmed) return;
    setIsBusy(true);
    setError("");
    try {
      const wechat = await resetWechat(threadId);
      dispatch({ type: "RESET_GROUP_THREAD", threadId: wechat.group_thread_id });
      options.clearAssociatedNews();
      options.setWechat(wechat);
    } catch (caught) {
      setError(`新群聊创建失败：${messageOf(caught)}`);
    } finally {
      setIsBusy(false);
    }
  };

  const markRead = async () => {
    try {
      const wechat = await markWechatRead(threadId);
      setThreadId(wechat.group_thread_id);
      options.setWechat(wechat);
      setError("");
    } catch (caught) {
      setError(`标记已读失败：${messageOf(caught)}`);
    }
  };

  const send = async (event: FormEvent) => {
    event.preventDefault();
    const question = input.trim();
    if (!question || isBusy) return;

    const baseWechat = options.wechat;
    const operation = operationRegistry.start("group", threadId);
    const isCurrent = () =>
      operationRegistry.isCurrent(
        operation.operationId,
        operation.generationId,
        threadId
      );
    const isOwned = () =>
      operationRegistry.isOwned(
        operation.operationId,
        operation.generationId,
        threadId
      );
    setIsBusy(true);
    setError("");
    let streamedReply = "";
    try {
      const baseContent = baseWechat?.content ?? "";
      if (baseWechat) {
        options.setWechat({
          ...baseWechat,
          content: `${baseContent}${baseContent.trim() ? "\n\n" : ""}【用户】\n${question}\n\n【群聊】\n她们正在输入…`,
          message_count: baseWechat.message_count + 1,
        });
      }
      const response = await sendWechatMessageStream(
        question,
        {
          groupThreadId: threadId,
          ragEnabled: options.ragEnabled,
          chatSettings: options.chatSettings,
          ragSettings: options.ragSettings,
        },
        {
          onSession: (meta) => {
            if (isCurrent()) setThreadId(meta.groupThreadId);
          },
          onToken: (token) => {
            if (!isCurrent() || !baseWechat) return;
            streamedReply += token;
            options.setWechat({
              ...baseWechat,
              content: `${baseContent}${baseContent.trim() ? "\n\n" : ""}【用户】\n${question}\n\n${streamedReply}`,
              message_count: baseWechat.message_count + 1,
            });
          },
        },
        { signal: operation.controller.signal }
      );
      if (!isCurrent()) return;
      setThreadId(response.group_thread_id);
      setInput("");
      options.setWechat({
        ...baseWechat,
        ...response,
        group_thread_id: response.group_thread_id,
        unread: baseWechat?.unread ?? "",
        unread_count: response.unread_count ?? baseWechat?.unread_count ?? 0,
        has_unread: response.has_unread ?? baseWechat?.has_unread ?? false,
        started: true,
        message_count: response.message_count ?? baseWechat?.message_count ?? 0,
        summary: response.content.slice(-500),
      });
    } catch (caught) {
      if (!isOwned()) return;
      const aborted = caught instanceof DOMException && caught.name === "AbortError";
      const reason = aborted ? "已停止生成" : messageOf(caught);
      if (baseWechat) options.setWechat(baseWechat);
      setError(`微信群回复生成失败：${reason}`);
    } finally {
      const ownsSettlement = isOwned();
      operationRegistry.complete(operation.operationId);
      if (ownsSettlement) setIsBusy(false);
    }
  };

  const stop = () => operationRegistry.abort("group");
  const cancelWorkspace = () => {
    operationRegistry.invalidate("group");
    setIsBusy(false);
  };

  return {
    threadId,
    input,
    setInput,
    isBusy,
    error,
    opening,
    reset,
    markRead,
    send,
    stop,
    cancelWorkspace,
  };
}

function messageOf(caught: unknown): string {
  return caught instanceof Error ? caught.message : "群聊操作失败";
}
