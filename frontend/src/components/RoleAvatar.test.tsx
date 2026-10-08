// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RoleAvatar } from "./RoleAvatar";

describe("RoleAvatar", () => {
  it("uses an empty image alt because the visible role label is rendered separately", () => {
    const { container } = render(<RoleAvatar fallback="assistant" roleId="keqing" />);
    expect(container.querySelector('[aria-hidden="true"]')).toBeTruthy();
    expect(container.querySelector("img")).toHaveAttribute("alt", "");
  });
  it("falls back on a failed image and loads a newly selected role", () => {
    const view=render(<RoleAvatar fallback="assistant" roleId="nahida"/>);
    fireEvent.error(view.container.querySelector("img")!);
    expect(view.container.querySelector("img")).toBeNull();
    expect(view.container.querySelector("svg")).toBeTruthy();
    view.rerender(<RoleAvatar fallback="assistant" roleId="march7"/>);
    expect(view.container.querySelector("img")).toHaveAttribute("src","/assets/avatars/march7.png");
  });
});
