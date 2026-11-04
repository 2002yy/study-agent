// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, fireEvent } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { MarkdownMessage } from "./MarkdownMessage";

afterEach(cleanup);

describe("MarkdownMessage", () => {
  it.each([["M01", "output_limit"], ["P01", "completed"]])("offers a draft for the real %s source-only answer without executing it", (task, status) => {
    const content = readFileSync(resolve(`e2e/fixtures/m4c3-first/${task}.txt`), "utf-8");
    const draft = vi.fn();
    const view = render(<MarkdownMessage content={content} interactive generation={{ status }} onDraft={draft} />);
    expect(view.container.querySelector("iframe, script")).toBeNull();
    expect(screen.getByText("这段内容是网页源码，尚未作为交互界面运行。")).toBeVisible();
    expect(draft).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "继续未完成的说明" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "生成可运行界面" }));
    expect(draft).toHaveBeenCalledTimes(1);
    expect(draft).toHaveBeenCalledWith(expect.stringContaining("study-ui"));
    if (status === "output_limit") expect(screen.getByRole("status")).toHaveTextContent("输出长度上限");
  });

  it("lets the user draft a continuation after a text output limit", () => {
    const draft = vi.fn();
    render(<MarkdownMessage content="已经收到的说明" interactive generation={{ status: "output_limit" }} onDraft={draft} />);
    expect(draft).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "继续未完成的说明" }));
    expect(draft).toHaveBeenCalledWith(expect.stringContaining("只用文字继续"));
  });
  it.each([
    ["output_limit", "本次回答达到输出长度上限"],
    ["completed", "模型已结束回答，但交互格式不完整"],
    ["timeout", "生成请求超时"],
    ["cancelled", "已停止生成"],
  ])("distinguishes %s without submitting an automatic repair", (status, text) => {
    const draft = vi.fn();
    render(<MarkdownMessage content={'```study-ui\n{"type":"interactive","html":"'} interactive generation={{ status }} onDraft={draft} />);
    expect(screen.getByText(new RegExp(text))).toBeInTheDocument();
    expect(draft).not.toHaveBeenCalled();
    expect(document.querySelector("iframe")).toBeNull();
  });
  it("renders markdown headings, emphasis and lists", () => {
    render(<MarkdownMessage content={"# 标题\n\n- 第一项\n- **第二项**"} />);

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("标题");
    expect(screen.getByText("第一项")).toBeInTheDocument();
    expect(screen.getByText("第二项")).toHaveTextContent("第二项");
  });

  it("renders GitHub-flavored markdown tables", () => {
    render(
      <MarkdownMessage
        content={"| A | B |\n|---|---|\n| 1 | 2 |"}
      />,
    );

    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
  });

  it("opens links in a new tab with noopener", () => {
    render(<MarkdownMessage content={"[链接](https://example.com)"} />);

    const link = screen.getByRole("link", { name: "链接" });
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noreferrer noopener");
  });

  it("renders fenced code blocks", () => {
    render(<MarkdownMessage content={"```ts\nconst x = 1;\n```"} />);

    expect(screen.getByText("const x = 1;")).toBeInTheDocument();
  });

  it("renders empty content safely", () => {
    const { container } = render(<MarkdownMessage content="" />);

    expect(container.firstChild).not.toBeNull();
    expect(container.textContent?.trim()).toBe("");
  });
});
