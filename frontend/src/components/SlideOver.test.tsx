// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SlideOver } from "./SlideOver";

beforeEach(() => {
  vi.spyOn(HTMLElement.prototype, "getClientRects").mockReturnValue({
    0: {} as DOMRect,
    length: 1,
    item: () => null,
    [Symbol.iterator]: function* iterator() {
      yield {} as DOMRect;
    },
  } as DOMRectList);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  document.body.style.overflow = "";
});

describe("SlideOver keyboard ownership", () => {
  it("returns to navigation when switching drawers removes the original tool", () => {
    const navigation = document.createElement("button");
    navigation.className = "session-dock-button";
    const opener = document.createElement("button");
    document.body.append(navigation, opener);
    opener.focus();
    const { unmount } = render(<SlideOver open title="设置" onClose={vi.fn()}><p>设置内容</p></SlideOver>);
    opener.remove();
    unmount();
    expect(navigation).toHaveFocus();
    navigation.remove();
  });
  it("does not render when closed", () => {
    const { container } = render(
      <SlideOver open={false} title="会话历史" onClose={vi.fn()}>
        <p>内容</p>
      </SlideOver>,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("focuses close, loops Tab and Shift+Tab, closes with Escape, and restores the opener", () => {
    const onClose = vi.fn();
    const opener = document.createElement("button");
    opener.textContent = "打开";
    document.body.append(opener);
    opener.focus();

    const { unmount } = render(
      <SlideOver open title="设置" onClose={onClose}>
        <button type="button">第一个操作</button>
        <input aria-label="设置输入" />
        <button type="button">最后一个操作</button>
      </SlideOver>,
    );

    const dialog = screen.getByRole("dialog", { name: "设置" });
    const close = screen.getByRole("button", { name: "关闭设置" });
    const last = screen.getByRole("button", { name: "最后一个操作" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(close).toHaveFocus();
    expect(document.body.style.overflow).toBe("hidden");

    last.focus();
    fireEvent.keyDown(window, { key: "Tab" });
    expect(close).toHaveFocus();

    fireEvent.keyDown(window, { key: "Tab", shiftKey: true });
    expect(last).toHaveFocus();

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);

    unmount();
    expect(opener).toHaveFocus();
    expect(document.body.style.overflow).toBe("");
    opener.remove();
  });

  it("keeps focus on the panel when it contains no interactive children", () => {
    render(
      <SlideOver open title="空面板" onClose={vi.fn()}>
        <p>没有操作</p>
      </SlideOver>,
    );
    const panel = document.querySelector("aside.slide-over") as HTMLElement;
    panel.focus();
    fireEvent.keyDown(window, { key: "Tab" });
    expect(panel).toHaveFocus();
  });
});
