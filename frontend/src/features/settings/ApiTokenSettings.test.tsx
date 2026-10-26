// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { apiToken, setApiToken } from "../../apiToken";
import { ApiTokenSettings } from "./ApiTokenSettings";

beforeEach(() => setApiToken(""));
afterEach(() => {
  cleanup();
  setApiToken("");
});

describe("ApiTokenSettings", () => {
  it("explains the locked state when no token is stored", () => {
    render(<ApiTokenSettings />);

    expect(screen.getByLabelText("API 令牌")).toHaveValue("");
    expect(screen.getByText(/所有私有接口返回 401/)).toBeTruthy();
  });

  it("stores the pasted token in this browser only", () => {
    render(<ApiTokenSettings />);

    fireEvent.change(screen.getByLabelText("API 令牌"), {
      target: { value: "  local-secret  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存令牌" }));

    expect(apiToken()).toBe("local-secret");
    expect(screen.getByText(/令牌已保存在本机浏览器/)).toBeTruthy();
  });

  it("clears a stored token", () => {
    setApiToken("local-secret");
    render(<ApiTokenSettings />);

    fireEvent.click(screen.getByRole("button", { name: "清除令牌" }));

    expect(apiToken()).toBe("");
    expect(screen.getByText(/所有私有接口返回 401/)).toBeTruthy();
  });

  it("trims the value and keeps the field in sync with what was stored", () => {
    render(<ApiTokenSettings />);

    fireEvent.change(screen.getByLabelText("API 令牌"), {
      target: { value: "  spaced  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存令牌" }));

    expect(screen.getByLabelText("API 令牌")).toHaveValue("spaced");
  });
});
