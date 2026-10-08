// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MarkdownMessage } from "../../components/MarkdownMessage";
import { AnswerProgress } from "./AnswerProgress";

afterEach(cleanup);
const block = (card: unknown) => "```study-ui\n" + JSON.stringify(card) + "\n```";
describe("inline learning interactions", () => {
  it("changes the curve and its numeric samples, resets it, and keeps controls across streamed text", () => {
    const content = block({ type: "plot", title: "二次函数", fn: "quadratic", a: 1, b: 0 });
    const view = render(<MarkdownMessage content={content} interactive streaming />);
    const slider = screen.getByRole("slider", { name: "二次函数 系数 a" });
    const initial = view.container.querySelector("polyline")!.getAttribute("points");
    fireEvent.change(slider, { target: { value: "2" } });
    expect(view.container.querySelector("polyline")!.getAttribute("points")).not.toBe(initial);
    view.rerender(<MarkdownMessage content={content + "\n\n补充解释"} interactive streaming />);
    expect(screen.getByRole("slider", { name: "二次函数 系数 a" })).toHaveValue("2");
    fireEvent.click(screen.getByRole("button", { name: "恢复初始" }));
    expect(screen.getByRole("slider", { name: "二次函数 系数 a" })).toHaveValue("1");
  });
  it("switches chart presentation without changing source data, including negative and zero values", () => {
    render(<MarkdownMessage interactive content={block({ type: "chart", title: "样例", points: [{ label: "甲", value: -3 }, { label: "乙", value: 0 }] })} />);
    fireEvent.click(screen.getByRole("button", { name: "折线图" }));
    expect(screen.getByRole("img")).toHaveAccessibleName(/折线图/);
    expect(screen.getByRole("table")).toHaveTextContent("-3");
  });
  it("offers explicit draft actions only for assistant-rendered components", () => {
    const onDraft = vi.fn();
    const content = block({ type: "actions", title: "继续探索", items: [{ label: "练习", prompt: "请给一道练习题" }] });
    const view = render(<MarkdownMessage content={content} onDraft={onDraft} />);
    expect(screen.queryByRole("button", { name: "练习" })).not.toBeInTheDocument();
    view.rerender(<MarkdownMessage content={content} interactive onDraft={onDraft} />);
    fireEvent.click(screen.getByRole("button", { name: "练习" }));
    expect(onDraft).toHaveBeenCalledWith("请给一道练习题");
  });
  it("does not execute HTML and keeps malformed components readable", () => {
    const { container } = render(<MarkdownMessage interactive content={'<script>window.bad=true</script>\n\n```study-ui\n{"type":"html"}\n```'} />);
    expect(container.querySelector("script")).toBeNull();
    expect(screen.getByText('{"type":"html"}')).toBeVisible();
  });
  it("handles unavailable images and opens a map only after an explicit click", () => {
    const view = render(<MarkdownMessage interactive content={block({ type: "image", title: "图", src: "/assets/avatars/nahida.png", alt: "学习头像" })} />);
    fireEvent.error(screen.getByRole("img"));
    expect(screen.getByText(/图片暂时无法显示/)).toBeInTheDocument();
    view.rerender(<MarkdownMessage interactive content={block({ type: "map", title: "地点", points: [{ label: "甲", lat: 30, lon: 120 }, { label: "乙", lat: 40, lon: 116 }] })} />);
    expect(view.container.querySelector("iframe")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "乙" }));
    fireEvent.click(screen.getByRole("button", { name: "显示地图" }));
    expect(screen.getByTitle("乙 地图")).toHaveAttribute("src", expect.stringContaining("marker=40%2C116"));
  });
  it("labels useful partial text separately from a pre-answer wait", () => {
    const view = render(<AnswerProgress hasContent={false} />);
    expect(screen.getByRole("status")).toHaveTextContent("正在组织回答");
    view.rerender(<AnswerProgress hasContent />);
    expect(screen.getByRole("status")).toHaveTextContent("回答正在补充，可以先阅读");
  });
});
