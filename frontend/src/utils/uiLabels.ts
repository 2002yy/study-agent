/** Render-only labels. API values and external content stay unchanged. */
export function labelFor(labels: Record<string, string>, value: string | null | undefined, fallback: string): string {
  return value && Object.prototype.hasOwnProperty.call(labels, value) ? labels[value] : fallback;
}
const STATUS_LABELS: Record<string, string> = {
  ready: "可用", read: "已读取", success: "已读取", succeeded: "已读取",
  selected: "已采用", candidate: "候选来源", rejected: "已排除",
  found: "已找到", unavailable: "暂不可用", failed: "读取失败",
  error: "出现错误", empty: "未找到来源", partial: "部分通过",
  confirmed: "已确认", pass: "已通过", pending: "等待中",
  legacy_unknown: "旧版候选 · 验证状态未知",
  ok: "已读取", read_success: "已读取", read_usable: "已读取", completed: "已完成",
};
const REASON_LABELS: Record<string, string> = {
  official_source: "来自官方来源", official: "来自官方来源",
  relevant: "内容与问题相关", unrelated: "内容与问题不匹配",
  irrelevant: "内容与问题不匹配", selected_for_answer: "用于本次回答",
  read_backed: "正文已读取验证", body_unrelated: "正文与问题不匹配",
  duplicate: "重复来源", duplicate_url: "重复来源", timeout: "读取超时",
  read_failed: "来源读取失败", legacy_unknown: "验证状态未知",
};
export function uiStatusLabel(value: string | undefined): string {
  return labelFor(STATUS_LABELS, value, "其他状态");
}
export function uiReasonLabel(value: string | undefined): string {
  return labelFor(REASON_LABELS, value, "原因待确认");
}
export function researchStepLabel(value: string | null | undefined): string {
  const labels: Record<string, string> = {
    search: "搜索来源", read: "阅读来源", assess: "核对来源", synthesize: "整理证据",
  };
  return labelFor(labels, value, "其他步骤");
}
export function scoreLabel(value: string): string {
  const labels: Record<string, string> = {
    score: "相关度", relevance: "相关度",
    keyword: "关键词匹配", keyword_score: "关键词匹配",
    lexical: "关键词匹配", lexical_score: "关键词原始评分",
    lexical_rank: "关键词排序", lexical_normalized: "关键词归一化评分",
    lexical_rrf: "关键词融合贡献",
    semantic: "语义相关度", semantic_score: "语义相关度",
    vector: "语义相关度", vector_score: "语义原始评分",
    vector_rank: "语义排序", vector_rrf: "语义融合贡献",
    authority: "来源权威度", authority_score: "来源权威度",
    bm25: "关键词匹配", rerank: "综合排序评分", total: "综合评分",
    fusion: "融合方式", rrf_k: "融合平滑常数",
    combined_score: "融合后评分", backend_score: "增强语义评分",
  };
  return labelFor(labels, value, "其他评分");
}
export function humanizeUiError(error: unknown, message = "暂时无法连接学习服务，请稍后重试。"): string {
  // Keep technical details available to developers, out of ordinary UI text.
  console.error("学习助手开发者诊断", error);
  return message;
}
