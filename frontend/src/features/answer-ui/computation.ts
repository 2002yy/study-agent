/**
 * Authoritative computation result — view types and a client-side mirror of the
 * server validation.
 *
 * The frontend only renders a table that the server already validated and bound
 * (``run_id`` / ``tool_run_id`` / ``input_revision`` / ``source_refs``).  No
 * model-provided HTML, JavaScript or callbacks are ever executed here.
 */

import type { ComputationPayload, ComputationStatus, ComputationTable } from "../../types";

export type { ComputationPayload, ComputationStatus, ComputationTable };

const MAX_COLUMNS = 12;
const MAX_ROWS = 500;

/**
 * Return the renderable table, or ``null`` when the payload must not render.
 *
 * A ``superseded`` result still renders its frozen table (badged stale); only
 * non-computed statuses are refused.
 */
export function renderableTable(payload: ComputationPayload | null | undefined): ComputationTable | null {
  if (!payload || (payload.status !== "succeeded" && payload.status !== "superseded")) return null;
  const result = payload.result as ComputationTable;
  if (!result || !Array.isArray(result.columns) || !Array.isArray(result.rows)) return null;
  if (!result.columns.length || result.columns.length > MAX_COLUMNS || result.rows.length > MAX_ROWS) return null;
  const columns = result.columns;
  if (new Set(columns).size !== columns.length || columns.some(name => typeof name !== "string" || !name.trim())) return null;
  for (const row of result.rows) {
    if (!Array.isArray(row) || row.length !== columns.length) return null;
    for (const cell of row) if (typeof cell === "number" && !Number.isFinite(cell)) return null;
  }
  return { columns, rows: result.rows, unit: result.unit };
}

/** The label/value split a bar or line view needs; both come from server data. */
export function chartSeries(table: ComputationTable): { label: string; value: number }[] {
  if (table.columns.length < 2) return [];
  return table.rows
    .map(row => ({ label: String(row[0]), value: row[1] }))
    .filter((point): point is { label: string; value: number } => typeof point.value === "number");
}

export function isStale(payload: ComputationPayload | null | undefined): boolean {
  return payload?.status === "superseded";
}

export function provenanceCopy(payload: ComputationPayload): string {
  const engine = payload.engine === "isolated_python" ? "隔离 Python" : "确定性计算";
  const sources = payload.source_refs.length ? ` · 来源 ${payload.source_refs.join("、")}` : " · 无绑定来源";
  return `${engine} · 版本 v${payload.input_revision} · 执行 ${payload.tool_run_id}${sources}`;
}
