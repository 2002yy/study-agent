// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { GlobalNotices } from "./GlobalNotices";

afterEach(() => cleanup());

const actions = () => ({
  onRetryApi: vi.fn(),
  onOpenSettings: vi.fn(),
  onDismissOperationError: vi.fn(),
});

describe("GlobalNotices", () => {
  it("announces API failure and exposes retry, settings, and details", () => {
    const callbacks = actions();
    render(
      <GlobalNotices
        apiError="503 provider down"
        operationError=""
        partialErrors={[]}
        {...callbacks}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("无法连接学习服务");
    expect(screen.getByText("503 provider down")).not.toBeVisible();
    fireEvent.click(screen.getByText("开发者诊断"));
    expect(screen.getByText("503 provider down")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    fireEvent.click(screen.getByRole("button", { name: "设置" }));
    expect(callbacks.onRetryApi).toHaveBeenCalledOnce();
    expect(callbacks.onOpenSettings).toHaveBeenCalledOnce();
  });

  it("announces operation failure and can be dismissed", () => {
    const callbacks = actions();
    render(
      <GlobalNotices
        apiError=""
        operationError="上传失败"
        partialErrors={[]}
        {...callbacks}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("操作没有完成");
    expect(screen.getByRole("alert")).toHaveTextContent("上传失败");
    fireEvent.click(screen.getByRole("button", { name: "关闭错误提示" }));
    expect(callbacks.onDismissOperationError).toHaveBeenCalledOnce();
  });

  it("uses polite status semantics for partial feature failures", () => {
    render(
      <GlobalNotices
        apiError=""
        operationError=""
        partialErrors={[["sessions", "timeout"]]}
        {...actions()}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("部分功能暂不可用");
  });
});
