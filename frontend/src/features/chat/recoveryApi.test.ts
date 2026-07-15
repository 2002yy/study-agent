import { afterEach, describe, expect, it, vi } from "vitest";

import { abandonInterruptedTurn } from "./recoveryApi";

describe("recovery API", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("posts to the encoded interrupted-turn abandon endpoint", async () => {
    const fetchMock = vi.fn(
      async (_input: RequestInfo | URL, _init?: RequestInit) =>
        new Response(
          JSON.stringify({
            session_id: "chat / 1",
            turn_id: "turn / 1",
            status: "abandoned",
            changed: true,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        )
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await abandonInterruptedTurn("chat / 1", "turn / 1");

    const calls = fetchMock.mock.calls as Array<[
      RequestInfo | URL,
      RequestInit | undefined,
    ]>;
    expect(String(calls[0][0])).toBe(
      "/sessions/chat%20%2F%201/turns/turn%20%2F%201/abandon"
    );
    expect(calls[0][1]?.method).toBe("POST");
    expect(result.status).toBe("abandoned");
  });
});
