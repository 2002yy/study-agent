/**
 * Provisional assistant replies ("阶段性回复").
 *
 * They are display-only: a turn's answer is still exactly one message, and these
 * never enter the persisted chat history. The merge rule is that a reply's
 * content version must strictly increase; a terminal reply is frozen against
 * late or duplicated events.
 */
import type { ChatResearchReply } from "../../types";

export function mergeResearchReplies(
  previous: ChatResearchReply[],
  incoming: ChatResearchReply[] | undefined,
): ChatResearchReply[] {
  if (!incoming?.length) return previous;
  const byId = new Map(previous.map(reply => [reply.reply_id, reply]));
  const unprovenClose = (reply: ChatResearchReply) =>
    reply.lifecycle === "closed" && reply.lifecycle_closed_by !== "run_terminal";
  for (const raw of incoming) {
    if (!raw?.reply_id || !raw.text) continue;
    const known = byId.get(raw.reply_id);
    if (!known) {
      // First restore: an unproven close is not a frozen state, but the reply
      // itself is real, so it is shown as live rather than dropped or mislabelled.
      byId.set(raw.reply_id, unprovenClose(raw) ? { ...raw, lifecycle: "open" } : raw);
      continue;
    }
    // A reply we already trust is never overwritten by a bare close claim.
    const reply = raw;
    // A frozen reply is never reopened.
    if (known.lifecycle !== "open") continue;
    // Only the research run's terminal state may freeze a reply: a writer that
    // merely claims "closed" is ignored, exactly as the server does.
    if (reply.lifecycle === "closed") {
      // An authoritative freeze is a state, not a content update: it is accepted
      // even at the same content version. An unproven claim is ignored.
      if (reply.lifecycle_closed_by === "run_terminal") byId.set(reply.reply_id, reply);
      continue;
    }
    // An invalidation the server decided (superseded or retracted) must reach the
    // reader even though it is not a "newer content" in the usual sense.
    if (
      (reply.lifecycle === "superseded" || reply.lifecycle === "retracted") &&
      reply.content_version >= known.content_version
    ) {
      byId.set(reply.reply_id, reply);
      continue;
    }
    if (reply.content_version <= known.content_version) continue;
    byId.set(reply.reply_id, reply);
  }
  return Array.from(byId.values()).sort((left, right) => left.reply_id.localeCompare(right.reply_id));
}

/** A reply that only acknowledges the supplement must not read as analysis. */
export function replyHeading(reply: ChatResearchReply): string {
  if (reply.stage === "acknowledgement") return "已收到补充";
  if (reply.stage === "knowledge") return "初步说明";
  if (reply.scope === "research") return "阶段性判断";
  return "初步分析";
}

export function replyIsProvisional(reply: ChatResearchReply): boolean {
  return reply.stage === "evidence_update";
}

export function replyStatusNote(reply: ChatResearchReply): string | null {
  if (reply.lifecycle === "retracted") return "已撤回，不再作为当前结论";
  if (reply.lifecycle === "superseded") return "已被后续纠正取代";
  // A general opening is useful, never authority: say so where it is read.
  if (reply.stage === "knowledge") return "已有知识；未经本次检索核实";
  if (reply.stale) return "尚未覆盖后续新增的条件";
  // The run accepted this requirement but the answer does not cover it. This is
  // the stronger, more honest statement, and it names the next step.
  if (reply.result_state === "not_included") {
    return "本轮研究结果未包含此要求（已接受，未执行）；可排队下一轮继续";
  }
  // A missing task understanding is *state*: it is reported here so it never has
  // to replace a sourced judgment that already exists.
  if (reply.analysis_state === "not_generated") return "本轮未生成模型分析";
  if (reply.lifecycle === "closed") return "研究已结束";
  return null;
}
