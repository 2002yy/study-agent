// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ApiSnapshot, SearchProviderHealthResponse } from "../../types";
import { CHAT_SETTINGS_DEFAULTS, RAG_SETTINGS_DEFAULTS, SettingsPanel } from "./SettingsPanel";

const apiMocks = vi.hoisted(() => ({
  checkSearchProviderHealth: vi.fn(),
}));

vi.mock("../../api", () => ({
  saveRuntimeSettings: vi.fn().mockResolvedValue({}),
  checkSearchProviderHealth: apiMocks.checkSearchProviderHealth,
}));

const snapshot = {
  health: { status: "ok" },
  error: "",
  runtimeSettings: { settings: { web_policy: "ask", cloud_context_policy: "question_only" } },
} as unknown as ApiSnapshot;

function renderPanel(isSending = false) {
  return render(
    <SettingsPanel
      snapshot={snapshot}
      ragEnabled
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
      isSending={isSending}
      refresh={vi.fn()}
      lastChat={null}
    />,
  );
}

function health(overrides: Partial<SearchProviderHealthResponse> = {}): SearchProviderHealthResponse {
  return {
    status: "ready",
    preferred_provider: "searxng",
    probed: true,
    checked_at: "2026-08-13T00:00:00Z",
    providers: [
      { name: "searxng", role: "preferred", enabled: true, configured: true, reachable: true, search_capable: true, status: "ready", detail: "valid_results_returned", endpoint: "http://127.0.0.1:8080" },
      { name: "bing_rss", role: "fallback", enabled: true, configured: true, reachable: null, search_capable: null, status: "enabled", detail: "not_probed", endpoint: "" },
      { name: "duckduckgo_html", role: "last_fallback", enabled: true, configured: true, reachable: null, search_capable: null, status: "enabled", detail: "not_probed_challenge_prone", endpoint: "" },
    ],
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
  apiMocks.checkSearchProviderHealth.mockReset();
});

describe("SettingsPanel provider health", () => {
  it("does not probe on render and reports a healthy preferred source after a click", async () => {
    apiMocks.checkSearchProviderHealth.mockResolvedValue(health());
    renderPanel();

    expect(apiMocks.checkSearchProviderHealth).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "检测联网搜索" }));

    expect(await screen.findByText("首选搜索源可用，可以正常联网检索。")).toBeVisible();
    expect(screen.getByText("SearXNG").parentElement).toHaveTextContent("可用");
  });

  it("distinguishes an online service with unhealthy engines from a full outage", async () => {
    apiMocks.checkSearchProviderHealth
      .mockResolvedValueOnce(health({
        status: "degraded",
        providers: health().providers.map((provider) => provider.name === "searxng"
          ? { ...provider, search_capable: false, status: "degraded", detail: "no_valid_results" }
          : provider),
      }))
      .mockResolvedValueOnce(health({
        status: "unavailable",
        providers: health().providers.map((provider) => ({ ...provider, enabled: false, configured: false, reachable: provider.name === "searxng" ? false : null, search_capable: provider.name === "searxng" ? false : null, status: "disabled" })),
      }));
    renderPanel();

    fireEvent.click(screen.getByRole("button", { name: "检测联网搜索" }));
    expect(await screen.findByText(/SearXNG 服务在线，但搜索引擎没有返回有效结果/)).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "检测联网搜索" }));
    expect(await screen.findByText("联网搜索不可用，提问时会明确返回未使用联网来源。")).toBeVisible();
  });

  it("keeps the provider check independent from the chat sending lock and renders request failure", async () => {
    apiMocks.checkSearchProviderHealth.mockRejectedValue(new Error("503 provider probe unavailable"));
    renderPanel(true);

    const button = screen.getByRole("button", { name: "检测联网搜索" });
    expect(button).toBeEnabled();
    fireEvent.click(button);

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("联网搜索检测失败，请稍后重试。"));
    expect(screen.getByText("检测失败，联网搜索当前不可确认。")).toBeVisible();
  });
});
