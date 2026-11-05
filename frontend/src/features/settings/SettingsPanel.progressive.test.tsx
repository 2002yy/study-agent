// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ApiSnapshot, ChatSettings, RagSettings } from "../../types";
import { SettingsPanel } from "./SettingsPanel";

vi.mock("../../api", () => ({
  saveRuntimeSettings: vi.fn().mockResolvedValue({}),
  checkSearchProviderHealth: vi.fn(),
}));

const snapshot = {
  health: { status: "ok" },
  error: "",
  runtimeSettings: {
    settings: {
      web_policy: "ask",
      cloud_context_policy: "question_only",
    },
  },
} as unknown as ApiSnapshot;

const chatSettings: ChatSettings = {
  selectedRole: "auto",
  selectedMode: "auto",
  selectedModel: "auto",
  relationshipMode: "standard",
  contextMode: "",
};

const ragSettings: RagSettings = {
  retrievalMode: "hybrid",
  topK: 5,
  chatTopK: 3,
  minScore: 0.01,
};

function renderPanel() {
  return render(
    <SettingsPanel
      snapshot={snapshot}
      ragEnabled
      setRagEnabled={vi.fn()}
      chatSettings={chatSettings}
      setChatSettings={vi.fn()}
      ragSettings={ragSettings}
      setRagSettings={vi.fn()}
      onSaveSettings={vi.fn()}
      isSavingSettings={false}
      onLoadRole={vi.fn()}
      roleDetail={null}
      keepCurrentRole={false}
      setKeepCurrentRole={vi.fn()}
      conversationInstruction=""
      setConversationInstruction={vi.fn()}
      isSending={false}
      refresh={vi.fn()}
      lastChat={null}
    />,
  );
}

afterEach(() => cleanup());

describe("SettingsPanel progressive disclosure", () => {
  it("keeps ordinary settings focused on learning, material, privacy and tone", () => {
    renderPanel();

    expect(screen.getByRole("combobox", { name: "学习方式" })).toBeVisible();
    expect(screen.getByRole("combobox", { name: "互动氛围" })).toBeVisible();
    expect(screen.getByRole("checkbox", { name: "回答时使用我的资料" })).toBeVisible();
    expect(screen.getByRole("combobox", { name: "联网策略" })).toBeVisible();
    expect(screen.getByRole("combobox", { name: "模型上下文" })).toBeVisible();
    expect(screen.getByRole("button", { name: "设为全局默认" })).toBeVisible();

    expect(screen.getByRole("combobox", { name: "角色", hidden: true })).not.toBeVisible();
    expect(screen.getByRole("combobox", { name: "模型档位", hidden: true })).not.toBeVisible();
    expect(screen.getByRole("combobox", { name: "个人记忆读取范围", hidden: true })).not.toBeVisible();
    expect(screen.getByRole("combobox", { name: "检索方式", hidden: true })).not.toBeVisible();
    expect(screen.getByRole("textbox", { name: "本会话微调", hidden: true })).not.toBeVisible();
  });

  it("keeps all existing engineering controls reachable after opening advanced settings", () => {
    renderPanel();
    fireEvent.click(screen.getByText("高级设置", { exact: true }));

    expect(screen.getByRole("combobox", { name: "角色" })).toBeVisible();
    expect(screen.getByRole("button", { name: "强制保持当前角色" })).toBeVisible();
    expect(screen.getByRole("textbox", { name: "本会话微调" })).toBeVisible();
    expect(screen.getByRole("combobox", { name: "模型档位" })).toBeVisible();
    expect(screen.getByRole("combobox", { name: "个人记忆读取范围" })).toBeVisible();
    expect(screen.getByRole("option", { name: "不读个人记忆" })).toHaveValue("none");
    expect(screen.getByRole("option", { name: "当前学习要点" })).toHaveValue("fast");
    expect(screen.getByRole("option", { name: "学习摘要" })).toHaveValue("light");
    expect(screen.getByRole("option", { name: "完整记忆范围" })).toHaveValue("deep");
    expect(screen.getByRole("combobox", { name: "检索方式" })).toBeVisible();
    expect(screen.getByRole("spinbutton", { name: "候选来源" })).toBeVisible();
    expect(screen.getByRole("spinbutton", { name: "回答引用" })).toBeVisible();
    expect(screen.getByRole("spinbutton", { name: "最低相关度" })).toBeVisible();
  });
});
