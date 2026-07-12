import { create } from "react-test-renderer";
import { describe, expect, it } from "vitest";
import { RoleAvatar } from "./RoleAvatar";

describe("RoleAvatar", () => {
  it("uses an empty image alt because the visible role label is rendered separately", () => {
    const root = create(<RoleAvatar fallback="assistant" roleId="keqing" />).root;
    expect(root.findByProps({ "aria-hidden": "true" })).toBeTruthy();
    expect(root.findByType("img").props.alt).toBe("");
  });
});
