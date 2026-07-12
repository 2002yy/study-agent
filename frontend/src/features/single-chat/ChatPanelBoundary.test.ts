import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const source = readFileSync(
  fileURLToPath(new URL("./ChatPanel.tsx", import.meta.url)),
  "utf8"
);

describe("active ChatPanel interaction boundary", () => {
  it("supports IME-safe Enter send and Shift+Enter newline", () => {
    expect(source).toContain('event.key !== "Enter"');
    expect(source).toContain("event.shiftKey");
    expect(source).toContain("event.nativeEvent.isComposing");
    expect(source).toContain("event.currentTarget.form?.requestSubmit()");
    expect(source).toContain("onKeyDown={handleComposerKeyDown}");
  });

  it("copies only the assistant message body", () => {
    expect(source).toContain('aria-label="复制回答正文"');
    expect(source).toContain("navigator.clipboard.writeText(content)");
    expect(source).not.toContain("navigator.clipboard.writeText(label)");
  });

  it("derives closure actions from the persisted task contract", () => {
    expect(source).toContain("taskContractFromRoute(lastChat?.route)");
    expect(source).toContain("closureActionLabel(taskContract)");
    expect(source).toContain("{closureLabel ? (");
    expect(source).toContain("{closureLabel}");
  });
});
