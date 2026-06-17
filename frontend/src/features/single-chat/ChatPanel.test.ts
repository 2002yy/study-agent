import { describe, expect, it } from "vitest";
import { latestMemorySection } from "./ChatPanel";
import type { MemoryStatusResponse } from "../../types";

function memoryStatus(preview: string): MemoryStatusResponse {
  return {
    context_mode: "light",
    memory_mode: "preview",
    reason: "test",
    writable: false,
    safe_mode: false,
    groups: {},
    files: [
      {
        name: "progress.md",
        exists: true,
        path: "progress.md",
        size_bytes: preview.length,
        mtime_ns: 1,
        preview
      }
    ]
  };
}

describe("latestMemorySection", () => {
  it("uses the latest markdown section when memory preview contains headings", () => {
    const result = latestMemorySection(
      memoryStatus("# Progress\n\nold\n\n## Latest\n\ncontinue here"),
      "progress.md",
      "fallback"
    );

    expect(result).toBe("## Latest\n\ncontinue here");
  });

  it("falls back when the memory file is absent", () => {
    expect(latestMemorySection(memoryStatus(""), "missing.md", "fallback")).toBe("fallback");
  });
});
