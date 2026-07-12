import type { ChatResponse, PedagogySummary, TurnEvidence, WebToolCall } from "../../types";

export type WebSearchSummary = {
  query: string;
  results: { title?: string; url?: string; snippet?: string }[];
};
export type WebReadSummary = { url: string; ok: boolean; preview: string; error?: string };
export type WebCallsSummary = { searches: WebSearchSummary[]; reads: WebReadSummary[] };

export function summarizeWebCalls(calls: WebToolCall[] | undefined): WebCallsSummary {
  const out: WebCallsSummary = { searches: [], reads: [] };
  for (const call of calls ?? []) {
    if (call.name === "web_search") {
      const results = Array.isArray((call.result as { results?: unknown }).results)
        ? (call.result as { results: { title?: string; url?: string; snippet?: string }[] }).results
        : [];
      out.searches.push({ query: String(call.arguments.query ?? ""), results });
    } else if (call.name === "web_read") {
      const r = call.result as { ok?: string; content?: string; url?: string; error?: string };
      out.reads.push({
        url: String(call.arguments.url ?? r.url ?? ""),
        ok: r.ok === "true",
        preview: (r.content ?? "").slice(0, 300),
        error: r.error,
      });
    }
  }
  return out;
}

export type Citation = { title: string; source: string; score: number };

export function buildCitations(rag: ChatResponse["rag"]): Citation[] {
  const results = (rag.results ?? []) as Array<Record<string, unknown>>;
  return results.map((r) => ({
    title: String(r.title ?? r.source_path ?? "未命名"),
    source: String(r.source_path ?? r.source ?? ""),
    score: Number(r.score ?? 0),
  }));
}

export function evidenceFromResponse(resp: ChatResponse): TurnEvidence {
  return { pedagogy: resp.pedagogy, rag: resp.rag, route: resp.route };
}

export function pedagogySummaryFromSnapshot(snap: unknown): PedagogySummary | undefined {
  if (!snap || typeof snap !== "object") return undefined;
  const o = snap as Record<string, unknown>;
  if (typeof o.mode !== "string" && typeof o.move !== "string") return undefined;
  return {
    mode: String(o.mode ?? ""),
    phase: String(o.phase ?? ""),
    move: String(o.move ?? ""),
    disclosure_level: Number(o.disclosure_level ?? 0),
  };
}

type SessionTurn = { turn_id: string; pedagogy_snapshot?: Record<string, unknown> };

export function evidenceFromSessionTurns(turns: SessionTurn[]): Map<string, TurnEvidence> {
  const map = new Map<string, TurnEvidence>();
  for (const turn of turns) {
    const pedagogy = pedagogySummaryFromSnapshot(turn.pedagogy_snapshot);
    if (pedagogy) map.set(turn.turn_id, { pedagogy });
  }
  return map;
}
