// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { ChatResponse } from "../../types";
import { ExternalDataDisclosure, summarizeExternalData } from "./ExternalDataDisclosure";

afterEach(() => cleanup());

const rag = {
  status: "found",
  query: "q",
  retrieval_mode: "hybrid",
  reason: "",
  context: "",
  sources: "",
  result_count: 0,
  results: [],
  debug: {},
  attempts: [],
  rewritten_query: "",
  external_data_policy: {
    web_policy: "auto",
    cloud_context_policy: "allow_local_evidence",
    task_source_policy: "local_and_web",
    web_allowed: true,
    local_retrieval_allowed: true,
    history_allowed: true,
    memory_allowed: true,
    local_evidence_to_model_allowed: true,
    reason: "allowed",
    external_data_audit_version: 2,
    external_calls: [
      {
        call_id: "answer_generation:1",
        purpose: "answer_generation",
        provider: "openai",
        data_categories: ["current_question", "recent_chat", "learning_state"],
        data_counts: { current_question: 1, recent_chat: 2, learning_state: 1 },
        status: "completed",
        result: "completed",
      },
      {
        call_id: "query_embedding:1",
        purpose: "query_embedding",
        provider: "openai:text-embedding-3-small",
        data_categories: ["retrieval_query"],
        data_counts: { retrieval_query: 1 },
        status: "blocked_by_policy",
        result: "blocked_by_policy",
      },
    ],
    web_search_performed: true,
    history_sent_to_model: true,
    history_message_count: 2,
    learning_state_sent_to_model: true,
    memory_context_sent_to_model: true,
    local_evidence_sent_to_model: true,
    local_evidence_chunk_count: 1,
  },
  web_tools: {
    enabled: true,
    used: true,
    calls: [
      {
        name: "web_search",
        arguments: { query: "Python 3.12 docs" },
        result: { providers_attempted: ["searxng"], results: [] },
      },
    ],
  },
} as ChatResponse["rag"];

describe("ExternalDataDisclosure", () => {
  it("summarizes policy, query, and provider without exposing local content", () => {
    const evidence = { rag };
    expect(summarizeExternalData(evidence)).toMatchObject({
      queries: ["Python 3.12 docs"],
      providers: ["SearXNG"],
    });
    render(<ExternalDataDisclosure evidence={evidence} />);
    expect(screen.getByLabelText("本轮外发数据说明")).toHaveTextContent(
      "搜索词：Python 3.12 docs",
    );
    expect(screen.getAllByText(/最近对话/)[0]).toHaveTextContent("已向模型发送 2 条消息");
    expect(screen.getByText(/本地资料/)).toHaveTextContent("已向模型发送 1 个相关片段");
    expect(screen.getByText(/搜索源/)).toHaveTextContent("SearXNG");
    expect(screen.getByText(/逐调用记录/)).toHaveTextContent(
      "回答生成 → OpenAI → 已完成",
    );
    expect(screen.getByText(/逐调用记录/)).toHaveTextContent(
      "检索词向量化 → OpenAI → 已被策略阻止，未外发",
    );
  });

  it("marks legacy policy booleans as unknown instead of claiming no transmission", () => {
    const legacy = {
      ...rag,
      external_data_policy: {
        ...rag.external_data_policy,
        external_data_audit_version: undefined,
        external_calls: undefined,
        learning_state_sent_to_model: false,
        memory_context_sent_to_model: false,
      },
    } as ChatResponse["rag"];

    render(<ExternalDataDisclosure evidence={{ rag: legacy }} />);

    expect(screen.getByText(/本地资料/)).toHaveTextContent(
      "学习状态：历史记录粒度不足，实际发送状态未知",
    );
    expect(screen.getByText(/本地资料/)).toHaveTextContent(
      "长期记忆上下文：历史记录粒度不足，实际发送状态未知",
    );
    expect(screen.getByText(/联网搜索/)).toHaveTextContent(
      "历史记录粒度不足，实际调用状态未知",
    );
    expect(screen.getByText(/最近对话/)).toHaveTextContent(
      "历史记录粒度不足，实际发送状态未知",
    );
    expect(screen.getByText(/本地资料/)).toHaveTextContent(
      "本地资料：历史记录粒度不足，实际发送状态未知",
    );
  });

  it("renders nothing for legacy turns without a policy snapshot", () => {
    const { container } = render(
      <ExternalDataDisclosure evidence={{ rag: { ...rag, external_data_policy: undefined } }} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
