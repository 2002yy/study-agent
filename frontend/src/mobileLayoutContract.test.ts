import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const practicalCss = readFileSync(
  new URL("./practical-experience.css", import.meta.url),
  "utf8"
);

function narrowScreenRules(): string {
  const start = practicalCss.indexOf("@media (max-width: 760px)");
  const end = practicalCss.indexOf("@media (max-width: 430px)", start);
  return practicalCss.slice(start, end);
}

describe("narrow-screen layout contract", () => {
  it("keeps the primary action and three mobile controls in one compact row", () => {
    const rules = narrowScreenRules();

    expect(rules).toContain("flex-wrap: nowrap");
    expect(rules).toContain(".topbar-actions .end-session-button");
    expect(rules).toContain("flex: 0 0 auto");
    expect(rules).not.toContain("grid-column: 1 / -1");
    expect(rules).not.toContain("repeat(6, 38px)");
  });

  it("keeps touch targets, the More popover, and drawers inside the viewport", () => {
    const rules = narrowScreenRules();

    expect(rules).toContain(".topbar-actions .icon-button");
    expect(rules).toContain("width: 44px");
    expect(rules).toContain("min-height: 44px");
    expect(rules).toContain(".workspace-menu");
    expect(rules).toContain("position: static");
    expect(rules).toContain("left: 0");
    expect(rules).toContain("width: min(300px, calc(100vw - 32px))");
    expect(rules).toContain("height: 100dvh");
  });
});
