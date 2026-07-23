// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ApiSnapshot, ChatResponse } from "../types";
import {
  CHAT_SETTINGS_DEFAULTS,
  RAG_SETTINGS_DEFAULTS,
  Sidebar,
} from "./Sidebar";

describe("focused learning settings", () => {
  it("keeps the settings drawer limited to learning experience, materials, and privacy", () => {
    const snapshot = {
      health: { status: "ok", service: "provider-secret-service" },
      error: null,
      ragStatus: {
        documents: 3,
        chunks: 12,
        vector_backend: { name: "secret-vector-provider", available: true },
      },
      runtimeSettings: { settings: {} },
    } as unknown as ApiSnapshot;
    const lastChat = {
      session_id: "session-secret-id",
      route: {
        role: "route-secret-role",
        mode: "route-secret-mode",
        model_profile: "provider-secret-model",
        evidence_disclosure: "route-secret-disclosure",
        pedagogy: { phase: "phase-secret-code", move: "move-secret-code" },
      },
    } as unknown as ChatResponse;

    const { container } = render(
      <Sidebar
        snapshot={snapshot}
        ragEnabled
        ragUploadMode="upload"
        setRagUploadMode={vi.fn()}
        setRagEnabled={vi.fn()}
        chatSettings={CHAT_SETTINGS_DEFAULTS}
        setChatSettings={vi.fn()}
        ragSettings={RAG_SETTINGS_DEFAULTS}
        setRagSettings={vi.fn()}
        onSaveSettings={vi.fn()}
        isSavingSettings={false}
        onLoadRole={vi.fn()}
        roleDetail={null}
        keepCurrentRole={false}
        setKeepCurrentRole={vi.fn()}
        conversationInstruction=""
        setConversationInstruction={vi.fn()}
        onNewSession={vi.fn()}
        isSending={false}
        refresh={vi.fn()}
        onUploadClick={vi.fn()}
        uploadState=""
        lastChat={lastChat}
      />,
    );

    const html = container.innerHTML;
    expect(html).toContain("学习体验");
    expect(html).toContain("资料辅助");
    expect(html).toContain("外发数据与联网");
    expect(html).toContain("高级检索设置");
    expect(html).toContain("服务已连接");

    expect(html).not.toContain("添加到现有知识库");
    expect(html).not.toContain("重建整个知识库");
    expect(html).not.toContain("新建单人会话");
    expect(html).not.toContain("工作流");
    expect(html).not.toContain("受控工具");
    expect(html).not.toContain("学习记忆");
    expect(html).not.toContain("单人对话");

    expect(html).not.toContain("provider-secret-service");
    expect(html).not.toContain("secret-vector-provider");
    expect(html).not.toContain("session-secret-id");
    expect(html).not.toContain("route-secret-role");
    expect(html).not.toContain("route-secret-mode");
    expect(html).not.toContain("provider-secret-model");
    expect(html).not.toContain("route-secret-disclosure");
    expect(html).not.toContain("phase-secret-code");
    expect(html).not.toContain("move-secret-code");
  });
});
