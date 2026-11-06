import { describe, expect, it } from "vitest";
import { loadThreeSource } from "./threeSource";

describe("local Three source bundle", () => {
  it("returns cached inert browser source with a frozen host global, without executing it", async () => {
    const before = (globalThis as { THREE?: unknown }).THREE;
    const first = loadThreeSource();
    expect(loadThreeSource()).toBe(first);
    const source = await first;
    expect(source.length).toBeGreaterThan(300000);
    expect(source).toContain('"THREE"');
    expect(source).toContain("writable:!1");
    expect(source).not.toContain("require(");
    expect((globalThis as { THREE?: unknown }).THREE).toBe(before);
  });
});
