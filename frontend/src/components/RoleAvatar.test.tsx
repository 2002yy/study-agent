// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RoleAvatar } from "./RoleAvatar";

describe("RoleAvatar", () => {
  it("uses an empty image alt because the visible role label is rendered separately", () => {
    const { container } = render(<RoleAvatar fallback="assistant" roleId="keqing" />);
    expect(container.querySelector('[aria-hidden="true"]')).toBeTruthy();
    expect(container.querySelector("img")).toHaveAttribute("alt", "");
  });
});
