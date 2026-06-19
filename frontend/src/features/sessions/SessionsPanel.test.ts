import { describe, expect, it } from "vitest";
import { sessionIdFromRow } from "./SessionsPanel";

describe("sessionIdFromRow", () => {
  it("uses the explicit SQLite session id when available", () => {
    expect(
      sessionIdFromRow({
        session_id: "chat_with_underscores",
        kind: "archived",
        name: "2026_session_chat_with_underscores_archived.md",
        path: "",
        size_bytes: 0,
        mtime_ns: 0
      })
    ).toBe("chat_with_underscores");
  });

  it("extracts current session ids from current filenames", () => {
    expect(
      sessionIdFromRow({
        kind: "current",
        name: "abc123.md",
        path: "",
        size_bytes: 10,
        mtime_ns: 1
      })
    ).toBe("abc123");
  });

  it("extracts archived session ids from archived filenames", () => {
    expect(
      sessionIdFromRow({
        kind: "archived",
        name: "2026-06-16_10-00-00_session_deadbeef_keqing_pro.md",
        path: "",
        size_bytes: 10,
        mtime_ns: 1
      })
    ).toBe("deadbeef");
  });
});
