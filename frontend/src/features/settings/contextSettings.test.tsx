// @vitest-environment jsdom
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { createWechatOpening, digestNewsRun, discussNewsRun, sendChat, sendWechatMessage } from "../../api";
import { CHAT_SETTINGS_DEFAULTS, RAG_SETTINGS_DEFAULTS } from "./SettingsPanel";
import { useSettingsController } from "./settingsController";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it.each(["", "none", "fast", "light", "deep"])("preserves context %s without sending a speed override on any transport", async contextMode => {
  const fetchMock = vi.fn(async () => new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } }));
  vi.stubGlobal("fetch", fetchMock);
  const chatSettings = { ...CHAT_SETTINGS_DEFAULTS, contextMode };
  const options = { chatSettings, ragSettings: RAG_SETTINGS_DEFAULTS, ragEnabled: false };
  await sendChat("question", [], options);
  await createWechatOpening(chatSettings);
  await sendWechatMessage("question", options);
  await digestNewsRun("run", chatSettings);
  await discussNewsRun("run", "group", chatSettings);
  expect(fetchMock).toHaveBeenCalledTimes(5);
  for (const [, init] of fetchMock.mock.calls as unknown as [string, RequestInit][]) {
    expect(JSON.parse(String(init.body)).performance_mode).toBeNull();
  }
  const single = JSON.parse(String((fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1].body));
  expect(single.context_mode).toBe(contextMode || null);
});

it.each(["", "none", "fast", "light", "deep"])("saves independent context %s and retains the server roundtrip", async contextMode => {
  const response = { settings: { context_mode: contextMode, performance_mode: "standard" }, options: {} };
  const fetchMock = vi.fn(async () => new Response(JSON.stringify(response), { status: 200, headers: { "Content-Type": "application/json" } }));
  vi.stubGlobal("fetch", fetchMock);
  const setRuntimeSettings = vi.fn();
  const refresh = vi.fn(async () => {});
  const { result } = renderHook(() => useSettingsController({
    chatSettings: { ...CHAT_SETTINGS_DEFAULTS, contextMode }, ragSettings: RAG_SETTINGS_DEFAULTS,
    ragEnabled: false, setRuntimeSettings, setOperationError: vi.fn(), refresh,
  }));
  await act(async () => result.current.save());
  const body = JSON.parse(String((fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1].body));
  expect(body.context_mode).toBe(contextMode);
  expect(body).not.toHaveProperty("performance_mode");
  expect(setRuntimeSettings).toHaveBeenCalledWith(response);
  expect(refresh).toHaveBeenCalledTimes(1);
});
