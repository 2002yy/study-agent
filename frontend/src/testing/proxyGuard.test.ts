import { describe, expect, it } from "vitest";

import {
  PROXY_BLOCKED_MESSAGE,
  assertLocalProxyIsBypassed,
  assessProxyEnvironment,
  hasActiveProxy,
  localTestTargets,
} from "./proxyGuard";

const DEV_SERVER = "http://127.0.0.1:5173";

describe("localTestTargets", () => {
  it("keeps loopback targets and drops everything else", () => {
    expect(
      localTestTargets([
        DEV_SERVER,
        "http://localhost:5173",
        "http://127.0.0.1:8000/health",
        "https://example.com/",
        "",
        null,
        undefined,
      ]),
    ).toEqual(["127.0.0.1:5173", "localhost:5173", "127.0.0.1:8000"]);
  });

  it("deduplicates the same host and port", () => {
    expect(localTestTargets([DEV_SERVER, DEV_SERVER, "http://127.0.0.1:5173/"])).toEqual([
      "127.0.0.1:5173",
    ]);
  });

  it("ignores values that are not absolute URLs", () => {
    expect(localTestTargets(["/relative", "not a url"])).toEqual([]);
  });
});

describe("assessProxyEnvironment", () => {
  it("passes when no proxy is set at all", () => {
    expect(assessProxyEnvironment({}, [DEV_SERVER]).verdict).toBe("ok");
  });

  it("passes when the only proxy variables are empty", () => {
    expect(
      assessProxyEnvironment({ HTTP_PROXY: "", http_proxy: "   " }, [DEV_SERVER]).verdict,
    ).toBe("ok");
  });

  it("passes when there is no local target to protect", () => {
    expect(
      assessProxyEnvironment({ HTTP_PROXY: "http://proxy.invalid:3128" }, [
        "https://example.com",
      ]).verdict,
    ).toBe("ok");
  });

  it("blocks when a proxy is set and nothing excludes loopback", () => {
    const assessment = assessProxyEnvironment(
      { HTTP_PROXY: "http://127.0.0.1:50565" },
      [DEV_SERVER],
    );
    expect(assessment.verdict).toBe("blocked");
    expect(assessment.detail.join("\n")).toContain("HTTP_PROXY");
    expect(assessment.detail.join("\n")).toContain("127.0.0.1:5173");
  });

  it("blocks even when HTTPS_PROXY alone is set", () => {
    expect(
      assessProxyEnvironment({ HTTPS_PROXY: "http://127.0.0.1:50565" }, [DEV_SERVER]).verdict,
    ).toBe("blocked");
  });

  it("honours lowercase proxy variables", () => {
    expect(
      assessProxyEnvironment({ http_proxy: "http://127.0.0.1:50565" }, [DEV_SERVER]).verdict,
    ).toBe("blocked");
  });

  it("passes when NO_PROXY covers the target host", () => {
    expect(
      assessProxyEnvironment(
        { HTTP_PROXY: "http://127.0.0.1:50565", NO_PROXY: "127.0.0.1" },
        [DEV_SERVER],
      ).verdict,
    ).toBe("ok");
  });

  it("passes when NO_PROXY is a wildcard", () => {
    expect(
      assessProxyEnvironment(
        { HTTP_PROXY: "http://127.0.0.1:50565", NO_PROXY: "*" },
        [DEV_SERVER],
      ).verdict,
    ).toBe("ok");
  });

  it("honours lowercase no_proxy", () => {
    expect(
      assessProxyEnvironment(
        { http_proxy: "http://127.0.0.1:50565", no_proxy: "localhost,127.0.0.1" },
        [DEV_SERVER],
      ).verdict,
    ).toBe("ok");
  });

  it("blocks when NO_PROXY names only localhost but the suite talks to 127.0.0.1", () => {
    const assessment = assessProxyEnvironment(
      { HTTP_PROXY: "http://127.0.0.1:50565", NO_PROXY: "localhost" },
      [DEV_SERVER],
    );
    expect(assessment.verdict).toBe("blocked");
  });

  it("requires the exclusion to match the port when one is given", () => {
    expect(
      assessProxyEnvironment(
        { HTTP_PROXY: "http://127.0.0.1:50565", NO_PROXY: "127.0.0.1:5173" },
        [DEV_SERVER],
      ).verdict,
    ).toBe("ok");
    expect(
      assessProxyEnvironment(
        { HTTP_PROXY: "http://127.0.0.1:50565", NO_PROXY: "127.0.0.1:9999" },
        [DEV_SERVER],
      ).verdict,
    ).toBe("blocked");
  });

  it("accepts a list of exclusions in either separator", () => {
    expect(
      assessProxyEnvironment(
        { HTTP_PROXY: "http://127.0.0.1:50565", NO_PROXY: "example.com, 127.0.0.1 localhost" },
        [DEV_SERVER, "http://localhost:5173"],
      ).verdict,
    ).toBe("ok");
  });

  it("reports unknown rather than healthy when an exclusion cannot be interpreted", () => {
    const assessment = assessProxyEnvironment(
      { HTTP_PROXY: "http://127.0.0.1:50565", NO_PROXY: "10.0.0.0/8" },
      [DEV_SERVER],
    );
    expect(assessment.verdict).toBe("unknown");
    expect(assessment.detail.join("\n")).toContain("无法可靠判断");
  });

  it("reports unknown for a bare IPv6 exclusion", () => {
    expect(
      assessProxyEnvironment(
        { HTTP_PROXY: "http://127.0.0.1:50565", NO_PROXY: "::1" },
        [DEV_SERVER],
      ).verdict,
    ).toBe("unknown");
  });

  it("never reports healthy when any exclusion rule is uninterpretable", () => {
    // A CIDR entry cannot be evaluated for a specific target, so even a list that also covers
    // one target exactly must not be read as "the environment is fine".
    const assessment = assessProxyEnvironment(
      { HTTP_PROXY: "http://127.0.0.1:50565", NO_PROXY: "localhost,10.0.0.0/8" },
      [DEV_SERVER, "http://localhost:5173"],
    );
    expect(assessment.verdict).toBe("unknown");
    expect(assessment.detail.join("\n")).toContain("127.0.0.1:5173");
  });
});

describe("hasActiveProxy", () => {
  it("is false for an empty or blank environment", () => {
    expect(hasActiveProxy({})).toBe(false);
    expect(hasActiveProxy({ HTTP_PROXY: "", https_proxy: "  " })).toBe(false);
  });

  it("sees any casing or protocol family", () => {
    expect(hasActiveProxy({ http_proxy: "http://127.0.0.1:50565" })).toBe(true);
    expect(hasActiveProxy({ ALL_PROXY: "socks5://127.0.0.1:1080" })).toBe(true);
  });
});

describe("assertLocalProxyIsBypassed", () => {
  it("stays silent when the environment is clean", () => {
    expect(() => assertLocalProxyIsBypassed({}, [DEV_SERVER])).not.toThrow();
  });

  it("raises the documented sentence when loopback would go through the proxy", () => {
    let message = "";
    try {
      assertLocalProxyIsBypassed({ HTTP_PROXY: "http://user:secret@127.0.0.1:50565" }, [
        DEV_SERVER,
      ]);
    } catch (error) {
      message = error instanceof Error ? error.message : String(error);
    }
    expect(message).toContain(PROXY_BLOCKED_MESSAGE);
    expect(message).toContain("127.0.0.1:5173");
  });

  it("never echoes proxy credentials", () => {
    let message = "";
    try {
      assertLocalProxyIsBypassed({ HTTP_PROXY: "http://user:secret@127.0.0.1:50565" }, [
        DEV_SERVER,
      ]);
    } catch (error) {
      message = error instanceof Error ? error.message : String(error);
    }
    expect(message).not.toContain("secret");
    expect(message).not.toContain("user:");
  });

  it("also refuses to claim health when the exclusion rules are undecidable", () => {
    expect(() =>
      assertLocalProxyIsBypassed(
        { HTTP_PROXY: "http://127.0.0.1:50565", NO_PROXY: "10.0.0.0/8" },
        [DEV_SERVER],
      ),
    ).toThrow();
  });
});
