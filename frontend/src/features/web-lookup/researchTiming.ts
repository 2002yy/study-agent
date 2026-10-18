/**
 * Browser-side latency marks for provisional replies.
 *
 * All marks come from one monotonic browser clock (`performance.now()`), so
 * user-visible latency is never computed by subtracting timestamps taken on
 * different machines. Server-side marks only explain where the time went.
 *
 * Visible marks are keyed by `reply_id + content_version + stage`: a receipt, a
 * task understanding (G1) and a sourced judgment (G2) are three different
 * things, and only the component that actually renders a reply reports one.
 * Every mark is first-wins, so a replayed event can never move an observation.
 *
 * Observations belong to one turn: a new send starts a new window, and an
 * answer-visible report is accepted only from that window's turn. Otherwise the
 * previous answer (still mounted, still reporting) would fill in this turn's
 * mark and make the G1/G2 lead look smaller than it was.
 *
 * The reported time is `rendered_after_frame`: the first frame after the content
 * was committed. It is a render observation, not proof that a reader's eyes
 * reached it in the scroll area.
 */
import type { ChatResearchReply, ChatResearchReplyStage } from "../../types";

export type ReplyTimingMark = {
  key: string;
  reply_id: string | null;
  steering_id: string;
  scope: "steering" | "research";
  submit_ms: number | null;
  receipt_ms: number | null;
  answer_ms: number | null;
};

export type ReplyVisibleMark = {
  /** `reply_id@content_version:stage` - one mark per rendered content state. */
  key: string;
  reply_id: string;
  content_version: number;
  stage: ChatResearchReplyStage;
  at: number;
};

export type ResearchTimingState = {
  marks: ReplyTimingMark[];
  visible: ReplyVisibleMark[];
  answer_done_ms: number | null;
  /** Reported by the component that renders the final answer, not by `done`. */
  answer_visible_ms: number | null;
  /** The turn this window observes; reports from any other turn are refused. */
  target_turn_id: string | null;
  /** What `answer_visible_ms` actually measures, stated instead of implied. */
  visibility_source: "rendered_after_frame";
};

export type TimingEvent =
  | { kind: "run_start"; at: number; turnId: string }
  | { kind: "submit"; at: number; steeringId: string }
  | { kind: "replies"; at: number; replies: ChatResearchReply[] }
  | { kind: "reply_visible"; at: number; reply: ChatResearchReply }
  | { kind: "answer_done"; at: number }
  | { kind: "answer_visible"; at: number; turnId?: string };

export function emptyTiming(): ResearchTimingState {
  return {
    marks: [],
    visible: [],
    answer_done_ms: null,
    answer_visible_ms: null,
    target_turn_id: null,
    visibility_source: "rendered_after_frame",
  };
}

/**
 * Whether an event belongs to the window this state observes.
 *
 * `target_turn_id === null` means no send has opened a window in this session
 * (for example a restored conversation), so events are not filtered and the
 * marks only describe what this session observed. Once a window is open, every
 * event must name that turn: a late SSE from another run must not add marks.
 */
function inWindow(
  state: ResearchTimingState,
  turnId: string | null | undefined,
): boolean {
  if (state.target_turn_id === null) return true;
  return turnId === state.target_turn_id;
}

export function visibleKey(reply: ChatResearchReply): string {
  return `${reply.reply_id}@${reply.content_version}:${reply.stage}`;
}

function markFor(marks: ReplyTimingMark[], steeringId: string): ReplyTimingMark {
  const known = marks.find(mark => mark.steering_id === steeringId);
  if (known) return known;
  const created: ReplyTimingMark = {
    key: `pending:${steeringId}`,
    reply_id: null,
    steering_id: steeringId,
    scope: "steering",
    submit_ms: null,
    receipt_ms: null,
    answer_ms: null,
  };
  marks.push(created);
  return created;
}

export function mergeTiming(
  state: ResearchTimingState,
  event: TimingEvent,
): ResearchTimingState {
  if (event.kind === "run_start") {
    // A new send opens a new observation window: nothing from the previous
    // answer may be carried into it.
    return { ...emptyTiming(), target_turn_id: event.turnId };
  }
  const marks = state.marks.map(mark => ({ ...mark }));
  const visible = state.visible.map(mark => ({ ...mark }));
  if (event.kind === "submit") {
    const mark = markFor(marks, event.steeringId);
    mark.submit_ms = mark.submit_ms ?? event.at;
    return { ...state, marks, visible };
  }
  if (event.kind === "answer_done") {
    for (const mark of marks) mark.answer_ms = mark.answer_ms ?? event.at;
    return { ...state, marks, visible, answer_done_ms: state.answer_done_ms ?? event.at };
  }
  if (event.kind === "answer_visible") {
    if (!inWindow(state, event.turnId)) {
      // A previous turn's answer is still mounted and still reporting.
      return { ...state, marks, visible };
    }
    return {
      ...state,
      marks,
      visible,
      answer_visible_ms: state.answer_visible_ms ?? event.at,
    };
  }
  if (event.kind === "reply_visible") {
    if (!inWindow(state, event.reply.turn_id)) {
      // A reply from another run can still be mounted after a new send.
      return { ...state, marks, visible };
    }
    const key = visibleKey(event.reply);
    if (!visible.some(mark => mark.key === key)) {
      visible.push({
        key,
        reply_id: event.reply.reply_id,
        content_version: event.reply.content_version,
        stage: event.reply.stage,
        at: event.at,
      });
    }
    return { ...state, marks, visible };
  }
  for (const reply of event.replies ?? []) {
    if (!inWindow(state, reply.turn_id)) continue;
    const mark = markFor(marks, reply.steering_id || reply.reply_id);
    mark.key = reply.reply_id;
    mark.reply_id = reply.reply_id;
    mark.scope = reply.scope;
    mark.receipt_ms = mark.receipt_ms ?? event.at;
  }
  return { ...state, marks, visible };
}

/** Earliest time a reply of this stage was actually rendered, if ever. */
export function visibleStageAt(
  state: ResearchTimingState,
  replyId: string,
  stage: ChatResearchReplyStage,
): number | null {
  const matches = state.visible
    .filter(mark => mark.reply_id === replyId && mark.stage === stage)
    .map(mark => mark.at);
  return matches.length ? Math.min(...matches) : null;
}

/** Earliest render of any provisional reply for this steering id, if ever. */
export function firstVisibleAt(
  state: ResearchTimingState,
  replyId: string,
): number | null {
  const matches = state.visible.filter(mark => mark.reply_id === replyId).map(mark => mark.at);
  return matches.length ? Math.min(...matches) : null;
}

function lead(answer: number | null, at: number | null): number | null {
  if (answer === null || at === null || at > answer) return null;
  return Math.round(answer - at);
}

/** How long before the answer the first visible reply appeared (null when late). */
export function leadBeforeAnswer(
  state: ResearchTimingState,
  replyId: string,
): number | null {
  return lead(state.answer_done_ms, firstVisibleAt(state, replyId));
}

/**
 * How long before the answer a real task understanding (G1) was visible.
 *
 * A sourced judgment is *not* a substitute: a run without G1 reports null here.
 */
export function analysisLeadBeforeAnswer(
  state: ResearchTimingState,
  replyId: string,
): number | null {
  return lead(state.answer_visible_ms, visibleStageAt(state, replyId, "analysis"));
}

/** How long before the answer a sourced judgment (G2) was visible. */
export function evidenceLeadBeforeAnswer(
  state: ResearchTimingState,
  replyId: string,
): number | null {
  return lead(state.answer_visible_ms, visibleStageAt(state, replyId, "evidence_update"));
}
