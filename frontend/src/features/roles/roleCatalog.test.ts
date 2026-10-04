import { describe, expect, it } from "vitest";

import {
  roleAvatarUrl,
  roleLabel,
  roleOptions,
  speakerToRole,
} from "./roleCatalog";

describe("roleCatalog", () => {
  it("exposes auto plus the four named roles in order", () => {
    expect(roleOptions.map(([value]) => value)).toEqual([
      "auto",
      "march7",
      "keqing",
      "nahida",
      "firefly",
    ]);
    expect(roleOptions[1][1]).toBe("三月七");
  });

  it("resolves avatar urls for known roles only", () => {
    expect(roleAvatarUrl("march7")).toBe("/assets/avatars/march7.png");
    expect(roleAvatarUrl("keqing")).toBe("/assets/avatars/keqing.png");
    expect(roleAvatarUrl("unknown")).toBe("");
    expect(roleAvatarUrl(undefined)).toBe("");
  });

  it("labels auto and missing roles as Study Agent", () => {
    expect(roleLabel("auto")).toBe("学习助手");
    expect(roleLabel(undefined)).toBe("学习助手");
  });

  it("labels known roles with Chinese names and falls back to the id", () => {
    expect(roleLabel("firefly")).toBe("流萤");
    expect(roleLabel("nahida")).toBe("纳西妲");
    expect(roleLabel("weird")).toBe("学习助手");
  });

  it("maps Chinese speaker names to role ids", () => {
    expect(speakerToRole["用户"]).toBe("user");
    expect(speakerToRole["刻晴"]).toBe("keqing");
  });
});
