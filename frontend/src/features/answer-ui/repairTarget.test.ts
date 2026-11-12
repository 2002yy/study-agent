import { afterEach, describe, expect, it } from "vitest";
import { clearRepairTarget, consumePendingRepairTarget, setPendingRepairTarget } from "./repairTarget";

const target = { id: "scene", revision: 1 };
afterEach(clearRepairTarget);

describe("repair retry identity lifecycle", () => {
  it("retains identity for a same-session transport retry after clearing the composer chip", () => {
    setPendingRepairTarget(target, "a");
    expect(consumePendingRepairTarget("repair", "a")).toEqual(target);
    setPendingRepairTarget(null);
    expect(consumePendingRepairTarget("repair", "a")).toEqual(target);
  });

  it("cancellation clears both an unsent draft and a consumed retry identity", () => {
    setPendingRepairTarget(target, "a");
    clearRepairTarget();
    expect(consumePendingRepairTarget("repair", "a")).toBeNull();
    setPendingRepairTarget(target, "a");
    consumePendingRepairTarget("repair", "a");
    clearRepairTarget();
    expect(consumePendingRepairTarget("repair", "a")).toBeNull();
  });

  it("a request in another session invalidates the previous retry even when returning", () => {
    setPendingRepairTarget(target, "a");
    consumePendingRepairTarget("repair", "a");
    expect(consumePendingRepairTarget("repair", "b")).toBeNull();
    expect(consumePendingRepairTarget("repair", "a")).toBeNull();
  });

  it("ordinary input invalidates the previous repair retry", () => {
    setPendingRepairTarget(target, "a");
    consumePendingRepairTarget("repair", "a");
    expect(consumePendingRepairTarget("ordinary", "a")).toBeNull();
    expect(consumePendingRepairTarget("repair", "a")).toBeNull();
  });

  it("a newly selected version replaces the prior retry identity", () => {
    setPendingRepairTarget(target, "a");
    consumePendingRepairTarget("repair", "a");
    const next = { id: "other", revision: 2 };
    setPendingRepairTarget(next, "a");
    expect(consumePendingRepairTarget("repair", "a")).toEqual(next);
    expect(consumePendingRepairTarget("repair", "a")).toEqual(next);
  });
});
