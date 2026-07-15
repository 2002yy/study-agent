import { act, create } from "react-test-renderer";
import { describe, expect, it, vi } from "vitest";

import type { ApiSnapshot, ChatResponse } from "../types";
import {
  CHAT_SETTINGS_DEFAULTS,
  RAG_SETTINGS_DEFAULTS,
  Sidebar,
} from "./Sidebar";

describe("Sidebar user-facing settings", () => {
  it("does not expose provider, route, or session identifiers in ordinary settings", () => {
    const snapshot = {
      health: {
        status: "ok",
        service: "provider-secret-service",
      },
      error: null,
      ragStatus: {
        documents: 3,
        chunks: 12,
        vector_backend: {
          name: "secret-vector-provider",
          available: true,
        },
      },
      runtimeSettings: {
        settings: {},
      },
    } as ApiSnapshot;
    const lastChat = {
      session_id: "session-secret-id",
      route: {
        role: "route-secret-role",
        mode: "route-secret-mode",
        model_profile: "provider-secret-model",
        evidence_disclosure: "route-secret-disclosure",
        pedagogy: {
          phase: "phase-secret-code",
          move: "move-secret-code",
        },
      },
    } as ChatResponse;

    let renderer!: ReturnType<typeof create>;
    act(() => {
      renderer = create(
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
        />
      );
    });

    const serialized = JSON.stringify(renderer.toJSON());
    expect(serialized).toContain("语义检索");
    expect(serialized).toContain("可用");
    expect(serialized).toContain("服务已连接");
    expect(serialized).not.toContain("provider-secret-service");
    expect(serialized).not.toContain("secret-vector-provider");
    expect(serialized).not.toContain("session-secret-id");
    expect(serialized).not.toContain("route-secret-role");
    expect(serialized).not.toContain("route-secret-mode");
    expect(serialized).not.toContain("provider-secret-model");
    expect(serialized).not.toContain("route-secret-disclosure");
    expect(serialized).not.toContain("phase-secret-code");
    expect(serialized).not.toContain("move-secret-code");

    act(() => renderer.unmount());
  });
});
