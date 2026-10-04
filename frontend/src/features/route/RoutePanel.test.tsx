// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { ChatResponse } from "../../types";
import { RoutePanel } from "./RoutePanel";

afterEach(cleanup);

const baseChat: ChatResponse = {
  reply: "回答",
  session_id: "s1",
  route: {
    role: "teacher",
    mode: "socratic",
    model_profile: "qwen",
    manual_override: false,
    confidence: 0.9,
    matched_keywords: ["恢复"],
    llm_router_used: true,
    reason: "用户处于恢复语义",
  },
  rag: {
    status: "success",
    query: "q",
    retrieval_mode: "hybrid",
    reason: "",
    context: "",
    sources: "",
    result_count: 3,
    results: [],
    debug: {},
    attempts: [],
    rewritten_query: "",
  },
};

describe("RoutePanel", () => {
  it("shows an empty state before the first answer", () => {
    render(<RoutePanel lastChat={null} />);

    expect(screen.getByText("等待第一轮回答")).toBeInTheDocument();
    expect(screen.getByText(/这里会展示后端返回的角色/)).toBeInTheDocument();
  });

  it("shows the session id once a chat exists", () => {
    render(<RoutePanel lastChat={baseChat} />);

    expect(screen.getByText("记录 ID s1")).toBeInTheDocument();
  });

  it("renders every route metric with its value", () => {
    render(<RoutePanel lastChat={baseChat} />);

    expect(screen.getByText("实际角色").nextElementSibling).toHaveTextContent("teacher");
    expect(screen.getByText("实际模式").nextElementSibling).toHaveTextContent("socratic");
    expect(screen.getByText("实际模型").nextElementSibling).toHaveTextContent("qwen");
    expect(screen.getByText("命中关键词").nextElementSibling).toHaveTextContent("恢复");
    expect(screen.getByText("LLM 路由").nextElementSibling).toHaveTextContent("true");
    expect(screen.getByText("路由原因").nextElementSibling).toHaveTextContent("用户处于恢复语义");
  });

  it("renders RAG status, result count and web tool usage", () => {
    render(<RoutePanel lastChat={baseChat} />);

    expect(screen.getByText("RAG 状态").nextElementSibling).toHaveTextContent("成功");
    expect(screen.getByText("引用数量").nextElementSibling).toHaveTextContent("3");
    expect(screen.getByText("模型联网工具").nextElementSibling).toHaveTextContent("本轮未调用");
  });

  it("reports called web tools with call count", () => {
    render(
      <RoutePanel
        lastChat={{
          ...baseChat,
          rag: {
            ...baseChat.rag,
            web_tools: { enabled: true, used: true, calls: [{ name: "search" }, { name: "fetch" }] },
          },
        }}
      />,
    );

    expect(screen.getByText("模型联网工具").nextElementSibling).toHaveTextContent("已调用 2 次");
  });

  it("reports disabled web tools", () => {
    render(
      <RoutePanel
        lastChat={{
          ...baseChat,
          rag: {
            ...baseChat.rag,
            web_tools: { enabled: false, used: false, calls: [] },
          },
        }}
      />,
    );

    expect(screen.getByText("模型联网工具").nextElementSibling).toHaveTextContent("已关闭");
  });
});
