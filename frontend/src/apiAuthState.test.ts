// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  clearAuthRequired,
  isAuthRequired,
  noteAuthRequired,
  subscribeAuthRequired,
} from "./apiAuthState";

afterEach(() => clearAuthRequired());

describe("apiAuthState", () => {
  it("only 401 marks the deployment as locked", () => {
    noteAuthRequired(500);
    noteAuthRequired(404);
    expect(isAuthRequired()).toBe(false);

    noteAuthRequired(401);
    expect(isAuthRequired()).toBe(true);
  });

  it("notifies subscribers once per transition", () => {
    const listener = vi.fn();
    const unsubscribe = subscribeAuthRequired(listener);

    noteAuthRequired(401);
    noteAuthRequired(401);
    clearAuthRequired();
    clearAuthRequired();

    expect(listener).toHaveBeenCalledTimes(2);
    unsubscribe();
  });

  it("stops notifying after unsubscribe", () => {
    const listener = vi.fn();
    subscribeAuthRequired(listener)();

    noteAuthRequired(401);

    expect(listener).not.toHaveBeenCalled();
  });
});
