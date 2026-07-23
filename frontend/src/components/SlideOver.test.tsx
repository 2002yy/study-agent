// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SlideOver } from "./SlideOver";

describe("SlideOver", () => {
  it("does not render when closed", () => {
    const { container } = render(
      <SlideOver open={false} title="会话历史" onClose={vi.fn()}>
        <p>内容</p>
      </SlideOver>
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("exposes explicit close controls without relying on hover", () => {
    const onClose = vi.fn();
    render(
      <SlideOver open title="会话历史" onClose={onClose}>
        <p>内容</p>
      </SlideOver>
    );

    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-label", "会话历史");

    const closeButtons = screen.getAllByRole("button", { name: "关闭会话历史" });
    expect(closeButtons).toHaveLength(2);

    fireEvent.click(closeButtons[1]);
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
