import { describe, expect, it } from "vitest";

import { translateStatus } from "./format";

describe("translateStatus", () => {
  it("keeps evidence sufficiency enums out of learner-facing UI", () => {
    expect(translateStatus("uncertain")).toBe("证据待确认");
    expect(translateStatus("insufficient")).toBe("证据不足");
  });
});
