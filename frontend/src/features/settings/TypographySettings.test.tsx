// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import AppShell from "../../AppShell";
import { TypographySettings } from "./TypographySettings";
import { TYPOGRAPHY_KEY, setTypographyPreference, useTypographyPreference } from "./typographyPreference";

function Harness() {
  const typography = useTypographyPreference();
  return <AppShell typography={typography}><TypographySettings/></AppShell>;
}
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  setTypographyPreference("balanced");
  window.localStorage.clear();
});

describe("device typography preferences", () => {
  it("updates the workspace immediately and restores the saved choice after remount", () => {
    const view = render(<Harness/>);
    fireEvent.click(screen.getByRole("radio", { name: /宋体阅读/ }));
    expect(view.container.querySelector(".app-shell")).toHaveAttribute("data-typography", "serif");
    expect(window.localStorage.getItem(TYPOGRAPHY_KEY)).toBe("serif");
    view.unmount();
    render(<Harness/>);
    expect(screen.getByRole("radio", { name: /宋体阅读/ })).toBeChecked();
  });
  it("falls back to the balanced preset for unknown stored values", () => {
    window.localStorage.setItem(TYPOGRAPHY_KEY, "unknown-font");
    render(<Harness/>);
    expect(screen.getByRole("radio", { name: /黑体正文 · 宋体标题/ })).toBeChecked();
  });
  it("still switches fonts when device storage is unavailable", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("storage blocked"); });
    render(<Harness/>);
    fireEvent.click(screen.getByRole("radio", { name: /统一黑体/ }));
    expect(screen.getByRole("radio", { name: /统一黑体/ })).toBeChecked();
  });
  it("shares a changed preference with another open view", () => {
    const view = render(<Harness/>);
    window.localStorage.setItem(TYPOGRAPHY_KEY, "sans");
    act(() => window.dispatchEvent(new StorageEvent("storage", { key: TYPOGRAPHY_KEY })));
    expect(view.container.querySelector(".app-shell")).toHaveAttribute("data-typography", "sans");
  });
});
