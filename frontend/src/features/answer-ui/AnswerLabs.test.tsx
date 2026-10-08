// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { MarkdownMessage } from "../../components/MarkdownMessage";
import { parseAnswerCard } from "./answerUiProtocol";

afterEach(cleanup);
const block = (c: unknown) => "```study-ui\n" + JSON.stringify(c) + "\n```";
export const memoryCard = { type: "memory_lab", title: "Java内存实验室", initialName: "甲", updatedName: "乙" };
export const performanceCard = { type: "performance_lab", title: "研究性能实验台", pages: 8, concurrency: 3, readSeconds: 4, summarySeconds: 6 };
export const evidenceCard = { type: "evidence_lab", title: "证据审查实验", mode: "simulation", sources: [{ label: "编码任务", kind: "measurement", aSeconds: 1.4, bSeconds: 2 }, { label: "检索任务", kind: "measurement", aSeconds: 2.6, bSeconds: 2.1 }, { label: "评论", kind: "opinion", text: "感觉A更快" }] };
describe("state-driven answer applications", () => {
  it("keeps references, objects and explanation synchronized through a sequence of operations", () => {
    render(<MarkdownMessage content={block(memoryCard)} interactive />);
    fireEvent.click(screen.getByRole("button", { name: "修改属性" }));
    expect(screen.getByRole("region", { name: "堆上的对象" })).toHaveTextContent('name = "乙"');
    expect(screen.getByRole("status")).toHaveTextContent("a.name 也会读到新值");
    fireEvent.click(screen.getByRole("button", { name: "重新赋值" }));
    expect(screen.getByRole("region", { name: "局部变量与引用" })).toHaveTextContent("b→ #2");
    fireEvent.click(screen.getByRole("button", { name: "置空 b" }));
    fireEvent.click(screen.getByRole("button", { name: "修改属性" }));
    expect(screen.getByRole("status")).toHaveTextContent("NullPointerException");
    fireEvent.click(screen.getByRole("button", { name: "全部置空" }));
    expect(screen.getAllByText("不可达 · 可被回收")).toHaveLength(2);
    expect(screen.getByRole("status")).toHaveTextContent("不意味着 GC 已实际发生");
    fireEvent.click(screen.getByRole("button", { name: "重置实验" }));
    expect(screen.getByRole("region", { name: "堆上的对象" })).toHaveTextContent('name = "甲"');
    expect(screen.queryByText("对象 #2")).not.toBeInTheDocument();
  });
  it("calculates non-divisible batches, caps useful concurrency and restores parameters", () => {
    render(<MarkdownMessage content={block(performanceCard)} interactive />);
    expect(screen.getByLabelText("串行读取总耗时")).toHaveTextContent("38s");
    expect(screen.getByLabelText("并发读取总耗时")).toHaveTextContent("18s");
    expect(screen.getByRole("status", { name: "性能预测结论" })).toHaveTextContent("节省 20 秒 · 耗时降低 53%");
    fireEvent.change(screen.getByRole("slider", { name: "允许同时读取的网页数" }), { target: { value: 12 } });
    expect(screen.getByLabelText("并发读取总耗时")).toHaveTextContent("10s");
    fireEvent.change(screen.getByRole("slider", { name: "需要读取的网页数" }), { target: { value: 1 } });
    expect(screen.getByRole("status", { name: "性能预测结论" })).toHaveTextContent("节省 0 秒");
    fireEvent.click(screen.getByRole("button", { name: "恢复默认参数" }));
    expect(screen.getByLabelText("并发读取总耗时")).toHaveTextContent("18s");
  });
  it("distinguishes finite support, opinions, no evidence, and a counterexample", () => {
    render(<MarkdownMessage content={block(evidenceCard)} interactive />);
    expect(screen.getByRole("status")).toHaveTextContent("不能证明所有任务");
    fireEvent.click(screen.getByRole("checkbox", { name: /编码任务/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /评论/ }));
    expect(screen.getByRole("status")).toHaveTextContent("证据不足");
    fireEvent.click(screen.getByRole("checkbox", { name: /检索任务/ }));
    expect(screen.getByRole("status")).toHaveTextContent("发现反例");
    fireEvent.click(screen.getByRole("button", { name: "重置选择" }));
    expect(screen.getByRole("status")).toHaveTextContent("已纳入 1/3");
  });
  it("rejects model-claimed real evidence, invalid resource counts and non-finite timings", () => {
    expect(parseAnswerCard(JSON.stringify({ ...evidenceCard, mode: "verified" }))).toBeNull();
    expect(parseAnswerCard(JSON.stringify({ ...performanceCard, concurrency: 0 }))).toBeNull();
    expect(parseAnswerCard(JSON.stringify({ ...performanceCard, pages: 1.5 }))).toBeNull();
    expect(parseAnswerCard(JSON.stringify({ ...performanceCard, readSeconds: null }))).toBeNull();
  });
});
