type CacheEntry<T> = {
  value?: T;
  promise?: Promise<T>;
  expiresAt: number;
};

export class ServerQueryCache {
  private entries = new Map<string, CacheEntry<unknown>>();

  async query<T>(
    key: string,
    loader: () => Promise<T>,
    ttlMs = 15_000
  ): Promise<T> {
    const now = Date.now();
    const current = this.entries.get(key) as CacheEntry<T> | undefined;
    if (current?.value !== undefined && current.expiresAt > now) {
      return current.value;
    }
    if (current?.promise) return current.promise;
    const promise = loader()
      .then((value) => {
        this.entries.set(key, { value, expiresAt: Date.now() + ttlMs });
        return value;
      })
      .catch((error) => {
        this.entries.delete(key);
        throw error;
      });
    this.entries.set(key, { promise, expiresAt: now + ttlMs });
    return promise;
  }

  invalidate(prefix?: string) {
    if (!prefix) {
      this.entries.clear();
      return;
    }
    for (const key of this.entries.keys()) {
      if (key.startsWith(prefix)) this.entries.delete(key);
    }
  }
}

export const serverQueryCache = new ServerQueryCache();
