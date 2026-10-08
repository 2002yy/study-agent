// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EXTERNAL_DATA_NOTICE_KEY, ExternalDataFirstUseNotice } from "./ExternalDataFirstUseNotice";

beforeEach(() => window.localStorage.clear());
afterEach(() => cleanup());

describe("ExternalDataFirstUseNotice", () => {
  it("explains current defaults once and can open privacy settings", () => {
    const onOpenSettings = vi.fn();
    render(
      <ExternalDataFirstUseNotice
        webPolicy="auto"
        cloudContextPolicy="allow_local_evidence"
        onOpenSettings={onOpenSettings}
      />,
    );
    expect(screen.getByRole("complementary", { name: "联网与模型上下文说明" })).toBeVisible();
    const disclosure = screen.getByLabelText("联网与模型上下文说明", { selector: "summary" });
    expect(disclosure.closest("details")).not.toHaveAttribute("open");
    fireEvent.click(disclosure);
    expect(screen.getByText(/任务需要时自动联网/)).toBeVisible();
    expect(screen.getByText(/相关本地资料片段/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "查看隐私设置" }));
    expect(onOpenSettings).toHaveBeenCalledOnce();
    expect(window.localStorage.getItem(EXTERNAL_DATA_NOTICE_KEY)).toBe("acknowledged");
  });

  it("stays dismissed after acknowledgement", () => {
    window.localStorage.setItem(EXTERNAL_DATA_NOTICE_KEY, "acknowledged");
    render(
      <ExternalDataFirstUseNotice
        webPolicy="ask"
        cloudContextPolicy="question_only"
        onOpenSettings={vi.fn()}
      />,
    );
    expect(screen.queryByRole("complementary")).toBeNull();
  });
});
