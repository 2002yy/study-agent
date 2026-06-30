import { useState } from "react";

import { lookupNews } from "../../api";
import { operationRegistry } from "../../app/operationRegistry";
import type { NewsLookupResponse } from "../../types";

type WebLookupControllerOptions = {
  query: string;
  setOperationError: (message: string) => void;
};

export function useWebLookupController(options: WebLookupControllerOptions) {
  const [result, setResult] = useState<NewsLookupResponse | null>(null);
  const [useInChat, setUseInChat] = useState(true);
  const [isBusy, setIsBusy] = useState(false);

  const lookup = async () => {
    const query = options.query.trim();
    if (!query || isBusy) return;
    const operation = operationRegistry.start("web_lookup");
    setIsBusy(true);
    options.setOperationError("");
    try {
      const response = await lookupNews(query, 8, {
        signal: operation.controller.signal,
      });
      if (!operationRegistry.isCurrent(operation.operationId, operation.generationId)) return;
      setResult(response);
      setUseInChat(true);
    } catch (error) {
      if (
        !operationRegistry.isCurrent(operation.operationId, operation.generationId) ||
        (error instanceof DOMException && error.name === "AbortError")
      ) return;
      options.setOperationError(
        `联网搜索失败：${error instanceof Error ? error.message : "联网搜索失败"}`
      );
    } finally {
      if (operationRegistry.isCurrent(operation.operationId, operation.generationId)) {
        setIsBusy(false);
      }
      operationRegistry.complete(operation.operationId);
    }
  };

  const cancel = () => {
    operationRegistry.invalidate("web_lookup");
    setIsBusy(false);
  };

  return {
    result,
    useInChat,
    setUseInChat,
    isBusy,
    lookup,
    cancel,
  };
}
