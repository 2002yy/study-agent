import { act, create } from "react-test-renderer";
import { describe, expect, it, vi } from "vitest";

import { SlideOver } from "./SlideOver";

describe("SlideOver", () => {
  it("does not render when closed", () => {
    let renderer!: ReturnType<typeof create>;
    act(() => {
      renderer = create(
        <SlideOver open={false} title="会话历史" onClose={vi.fn()}>
          <p>内容</p>
        </SlideOver>
      );
    });

    expect(renderer.toJSON()).toBeNull();
    act(() => renderer.unmount());
  });

  it("exposes explicit close controls without relying on hover", () => {
    const onClose = vi.fn();
    let renderer!: ReturnType<typeof create>;
    act(() => {
      renderer = create(
        <SlideOver open title="会话历史" onClose={onClose}>
          <p>内容</p>
        </SlideOver>
      );
    });

    const dialog = renderer.root.findByProps({ role: "dialog" });
    expect(dialog.props["aria-label"]).toBe("会话历史");

    const closeButtons = renderer.root.findAllByProps({ "aria-label": "关闭会话历史" });
    expect(closeButtons).toHaveLength(2);

    act(() => closeButtons[1].props.onClick());
    expect(onClose).toHaveBeenCalledTimes(1);

    act(() => renderer.unmount());
  });
});
