import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

/**
 * The composer is a grid. Its rows are load-bearing: the role panel is a chooser
 * for the *next* message, so it has to open above the input, and the toolbar and
 * send controls have to stay below it. A reorder that puts the panel underneath
 * the input is a regression the browser test catches only after a full page load,
 * so the ordering is pinned here as well.
 */
const workspacePolish = readFileSync(
  new URL("./features/reading/workspacePolish.css", import.meta.url),
  "utf8",
);

function rule(selector: string): string {
  const start = workspacePolish.indexOf(`${selector} {`);
  expect(start, `missing rule for ${selector}`).toBeGreaterThanOrEqual(0);
  const end = workspacePolish.indexOf("}", start);
  return workspacePolish.slice(start, end);
}

function gridRow(selector: string): number {
  const match = /grid-row:\s*(\d+)/.exec(rule(selector));
  expect(match, `missing grid-row for ${selector}`).not.toBeNull();
  return Number(match![1]);
}

describe("composer grid contract", () => {
  it("opens the role panel above the input", () => {
    const panel = gridRow(".reading-layout .composer-main > .chat-role-settings");
    const input = gridRow(".reading-layout .composer-main > textarea");

    expect(panel).toBeLessThan(input);
  });

  it("keeps the toolbar and send controls below the input", () => {
    const input = gridRow(".reading-layout .composer-main > textarea");

    expect(gridRow(".reading-layout .composer-toolbar")).toBeGreaterThan(input);
    expect(gridRow(".reading-layout .composer-footer")).toBeGreaterThan(input);
  });
});
