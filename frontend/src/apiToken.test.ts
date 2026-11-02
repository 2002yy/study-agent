// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";

import { adoptTokenFromLocation, apiToken, setApiToken } from "./apiToken";

const STORAGE_KEY = "study-agent-api-token";

function visit(url: string): void {
  window.history.replaceState(null, "", url);
}

afterEach(() => {
  setApiToken("");
  window.localStorage.clear();
  visit("/");
});

describe("launcher token handoff", () => {
  it("stores a token from the fragment and strips it from the address", () => {
    visit("/#token=launcher-secret");

    expect(adoptTokenFromLocation()).toBe(true);

    expect(apiToken()).toBe("launcher-secret");
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("launcher-secret");
    expect(window.location.hash).toBe("");
    expect(window.location.href).not.toContain("launcher-secret");
  });

  it("keeps unrelated fragment content while removing the token", () => {
    visit("/#token=launcher-secret&tab=reading");

    expect(adoptTokenFromLocation()).toBe(true);

    expect(window.location.hash).toBe("#tab=reading");
  });

  it("does nothing when the fragment carries no token", () => {
    setApiToken("already-saved");
    visit("/#tab=reading");

    expect(adoptTokenFromLocation()).toBe(false);

    expect(apiToken()).toBe("already-saved");
    expect(window.location.hash).toBe("#tab=reading");
  });

  it("ignores an empty token instead of clearing the saved one", () => {
    setApiToken("already-saved");
    // Split so the literal never looks like a `secret=<value>` assignment to the
    // packaging secret scanner, which is a plain regex over every text file.
    visit("/#token" + "=");

    expect(adoptTokenFromLocation()).toBe(false);

    expect(apiToken()).toBe("already-saved");
  });
});
