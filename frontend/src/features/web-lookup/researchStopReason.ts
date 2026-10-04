export const KNOWN_RESEARCH_STOP_REASONS = [
  "evidence_gate_pass",
  "evidence_budget_exhausted",
  "evidence_gap_open",
  "evidence_saturated",
  "wave_limit_exhausted",
  "claim_planning_blocked_by_policy",
  "claim_plan_unavailable",
  "active_runtime_unavailable",
  "user_cancelled",
  "providers_failed",
  "providers_returned_no_results",
  "direct_results_found",
  "read_backed_tool_evidence_found",
  "search_candidates_only",
  "no_tool_calls",
  "insufficient_valid_sources",
  "sources_read",
  "sources_partially_read",
  "source_reading_failed",
  "chat_tool_loop_failed",
  "research_stage_failed",
  "legacy_run_interrupted",
] as const;

export type KnownResearchStopReason = (typeof KNOWN_RESEARCH_STOP_REASONS)[number];

export const RESEARCH_STOP_REASON_LABELS = {
  evidence_gate_pass: "证据校验已通过；本轮结论只使用通过校验的证据。",
  evidence_budget_exhausted: "研究预算已用尽；仍有关键证据缺口，结论保持为部分结果。",
  evidence_gap_open: "证据校验未通过；仍有关键证据缺口，结论保持为部分结果。",
  evidence_saturated: "当前可用来源已趋于饱和；仍有证据缺口，结论保持为部分结果。",
  wave_limit_exhausted: "已达到本轮研究轮次上限；仍有证据缺口，结论保持为部分结果。",
  claim_planning_blocked_by_policy: "外部数据策略未授权研究规划；本轮未继续调用外部模型。",
  claim_plan_unavailable: "研究规划暂时不可用；本轮未把未经校验的结果当成结论。",
  active_runtime_unavailable: "主动研究链不可用；未把未经校验的结果当成结论。",
  user_cancelled: "已停止本次研究；已保存可确认的进度。",
  providers_failed: "联网来源暂时不可用；本轮未获得可确认的搜索结果。",
  providers_returned_no_results: "联网来源未返回结果；这不代表目标不存在。",
  direct_results_found: "已找到可直接使用的联网结果。",
  read_backed_tool_evidence_found: "已找到经过读取确认的联网证据。",
  search_candidates_only: "已找到候选来源，但尚未完成读取确认。",
  no_tool_calls: "本轮没有发起联网工具调用；未获得联网证据。",
  insufficient_valid_sources: "可验证来源不足；本轮未形成足够可靠的研究结果。",
  sources_read: "已读取并确认本轮可用来源。",
  sources_partially_read: "部分来源已读取确认，仍有来源读取失败。",
  source_reading_failed: "候选来源读取失败；本轮未形成可确认的读取证据。",
  chat_tool_loop_failed: "联网研究工具链未完成；未把未经校验的结果当成结论。",
  research_stage_failed: "联网研究阶段未完成；可从已保存的进度重试。",
  legacy_run_interrupted: "旧版研究任务曾被中断；可重新发起或继续研究。",
} satisfies Record<KnownResearchStopReason, string>;

export function researchStopReasonDisplay(
  reason: string,
  fallback = "联网研究已结束。",
): string {
  if (!reason) return fallback;
  return RESEARCH_STOP_REASON_LABELS[reason as KnownResearchStopReason] ?? fallback;
}
