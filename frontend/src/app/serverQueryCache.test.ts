import { describe, expect, it, vi } from "vitest";

import { ServerQueryCache } from "./serverQueryCache";

describe("ServerQueryCache", () => {
  it("deduplicates concurrent requests and reuses a fresh value", async () => {
    const cache = new ServerQueryCache();
    const loader = vi.fn().mockResolvedValue({ version: 1 });
    const [first, second] = await Promise.all([
      cache.query("snapshot", loader),
      cache.query("snapshot", loader),
    ]);
    const third = await cache.query("snapshot", loader);

    expect(second).toBe(first);
    expect(third).toBe(first);
    expect(loader).toHaveBeenCalledTimes(1);
  });

  it("invalidates only keys under the requested prefix", async () => {
    const cache = new ServerQueryCache();
    const snapshotLoader = vi.fn().mockResolvedValue("snapshot");
    const roleLoader = vi.fn().mockResolvedValue("role");
    await cache.query("snapshot:runtime", snapshotLoader);
    await cache.query("role:nahida", roleLoader);
    cache.invalidate("snapshot");
    await cache.query("snapshot:runtime", snapshotLoader);
    await cache.query("role:nahida", roleLoader);

    expect(snapshotLoader).toHaveBeenCalledTimes(2);
    expect(roleLoader).toHaveBeenCalledTimes(1);
  });
});
