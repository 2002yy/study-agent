import type { ChatResponse, PedagogySummary, TurnEvidence, WebToolCall } from "../../types";

export type WebSearchSummary = {
  query: string;
  results: { title?: string; url?: string; snippet?: string }[];
};
export type WebReadSummary = { url: string; ok: boolean; preview: string; error?: string };
export type WebCallsSummary = { searches: WebSearchSummary[]; reads: WebReadSummary[] };

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

export function summarizeWebCalls(calls: WebToolCall[] | undefined): WebCallsSummary {
  const out: WebCallsSummary = { searches: [], reads: [] };
  for (const call of calls ?? []) {
    if (call.name === "web_search") {
      const rawResults = Array.isArray((call.result as { results?: unknown }).results)
        ? ((call.result as { results: unknown[] }).results ?? [])
        : [];
      const results = rawResults.flatMap((value) => {
        const result = asRecord(value);
        const title = String(result.title ?? "").trim();
        const url = String(result.url ?? "").trim();
        const snippet = String(result.snippet ?? "").trim();
        if (!title && !url) return [];
        return [{ title: title || undefined, url: url || undefined, snippet: snippet || undefined }];
      });
      const query = String(call.arguments.query ?? "").trim();
      if (query || results.length) out.searches.push({ query, results });
    } else if (call.name === "web_read") {
      const r = asRecord(call.result);
      const url = String(call.arguments.url ?? r.url ?? "").trim();
      const ok = r.ok === true || r.ok === "true";
      const preview = String(r.content ?? "").slice(0, 300);
      const error = String(r.error ?? "").trim() || undefined;
      if (url || preview || error) out.reads.push({ url, ok, preview, error });
    }
  }
  return out;
}

export type Citation = { title: string; source: string; score: number };

function basename(path: string): string {
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts[parts.length - 1] ?? path;
}

export function buildCitations(rag: ChatResponse["rag"]): Citation[] {
  const results = (rag.results ?? []) as Array<Record<string, unknown>>;
  const seen = new Set<string>();
  return results.flatMap((result) => {
    const chunk = asRecord(result.chunk);
    const source = String(
      chunk.source_path ?? result.source_path ?? result.source ?? ""
    ).trim();
    const rawTitle = String(chunk.title ?? result.title ?? "").trim();
    const score = Number(result.score ?? 0);
    if ((!rawTitle && !source) || !Number.isFinite(score) || score <= 0) return [];
    const title = rawTitle || basename(source);
    const key = `${source}\u0000${title}`;
    if (seen.has(key)) return [];
    seen.add(key);
    return [{ title, source, score }];
  });
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

type SessionTurn = {
  turn_id: string;
  pedagogy_snapshot?: Record<string, unknown>;
  route_snapshot?: Record<string, unknown>;
  rag_snapshot?: Record<string, unknown>;
};

export function evidenceFromSessionTurns(turns: SessionTurn[]): Map<string, TurnEvidence> {
  const map = new Map<string, TurnEvidence>();
  for (const turn of turns) {
    const pedagogy = pedagogySummaryFromSnapshot(turn.pedagogy_snapshot);
    const rag =
      turn.rag_snapshot && Object.keys(turn.rag_snapshot).length
        ? (turn.rag_snapshot as ChatResponse["rag"])
        : undefined;
    const route =
      turn.route_snapshot && Object.keys(turn.route_snapshot).length
        ? turn.route_snapshot
        : undefined;
    if (pedagogy || rag || route) {
      map.set(turn.turn_id, { pedagogy, rag, route });
    }
  }
  return map;
}
