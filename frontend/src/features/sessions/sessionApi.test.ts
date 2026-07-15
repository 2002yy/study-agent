import { afterEach, describe, expect, it, vi } from "vitest";

import { updateSessionTitle } from "./sessionApi";

const session = {
  session_id: "chat / 1",
  kind: "current",
  name: "chat-1.md",
  path: "",
  size_bytes: 0,
  mtime_ns: 0,
  title: "手动标题",
  title_source: "manual",
};

describe("session title API", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("patches the encoded session title endpoint", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ session }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await updateSessionTitle("chat / 1", "手动标题");

    expect(result.title).toBe("手动标题");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/sessions/chat%20%2F%201/title");
    expect(options.method).toBe("PATCH");
    expect(JSON.parse(String(options.body))).toEqual({ title: "手动标题" });
  });
});
