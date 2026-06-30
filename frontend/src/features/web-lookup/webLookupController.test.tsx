import React from "react";
import { act, create } from "react-test-renderer";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { operationRegistry } from "../../app/operationRegistry";
import { useWebLookupController } from "./webLookupController";

const apiMocks = vi.hoisted(() => ({
  lookupNews: vi.fn(),
}));

vi.mock("../../api", () => apiMocks);

describe("useWebLookupController", () => {
  beforeEach(() => {
    operationRegistry.cancelAll();
    vi.clearAllMocks();
  });

  it("owns lookup result, chat opt-in, and server run ID", async () => {
    apiMocks.lookupNews.mockResolvedValue({
      run_id: "web_lookup_1",
      query_text: "Python docs",
      news_items: [{ title: "Python" }],
      source_block: "source",
      warnings: [],
    });
    const errors: string[] = [];
    let controller: ReturnType<typeof useWebLookupController> | undefined;

    function Harness() {
      controller = useWebLookupController({
        query: "Python docs",
        setOperationError: (message) => errors.push(message),
      });
      return null;
    }

    await act(async () => {
      create(<Harness />);
    });
    await act(async () => {
      await controller?.lookup();
    });

    expect(controller?.result?.run_id).toBe("web_lookup_1");
    expect(controller?.useInChat).toBe(true);
    expect(controller?.isBusy).toBe(false);
    expect(errors[errors.length - 1]).toBe("");
  });
});
