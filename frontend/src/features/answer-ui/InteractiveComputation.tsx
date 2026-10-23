import { useState } from "react";

import {
  chartSeries,
  isStale,
  provenanceCopy,
  renderableTable,
  type ComputationPayload,
} from "./computation";

export type ComputationParameter = { name: string; value: number };

const VIEWS = [
  ["bar", "柱状图"],
  ["line", "折线图"],
  ["table", "数据表"],
] as const;

type View = (typeof VIEWS)[number][0];

/**
 * Interactive view over a server-validated computation result.
 *
 * The component only rearranges bound numbers: it never runs model-provided
 * HTML/JS, and a parameter change triggers a fresh *server* computation rather
 * than an ad-hoc local recalculation.  A superseded result is shown as stale
 * and never overwrites the original execution record.
 */
export function InteractiveComputation({
  payload,
  parameters = [],
  onRecompute,
  isRecomputing = false,
}: {
  payload: ComputationPayload;
  parameters?: ComputationParameter[];
  onRecompute?: (values: Record<string, number>) => void | Promise<void>;
  isRecomputing?: boolean;
}) {
  const [view, setView] = useState<View>("bar");
  const [values, setValues] = useState<Record<string, number>>(
    () => Object.fromEntries(parameters.map(parameter => [parameter.name, parameter.value])),
  );
  const table = renderableTable(payload);

  if (payload.status === "blocked" || payload.status === "failed" || payload.status === "cancelled") {
    return <div className="computation-note" role="status">计算未完成：{payload.reason || payload.status}</div>;
  }
  if (!table) {
    return <div className="computation-note computation-invalid" role="status">计算结果未通过校验，已拒绝展示。</div>;
  }
  const series = chartSeries(table);
  const maxValue = Math.max(...series.map(point => point.value), 0) || 1;

  return (
    <figure className="computation-card" aria-label="计算结果">
      <header className="computation-head">
        <div className="computation-view-toggle" role="group" aria-label="图表类型">
          {VIEWS.map(([id, label]) => (
            <button key={id} type="button" aria-pressed={view === id} onClick={() => setView(id)}>{label}</button>
          ))}
        </div>
        {isStale(payload) ? (
          <span className="computation-stale" role="status">
            已过期：输入已更新至 v{payload.superseded_by_revision}，旧结果保留不回写
          </span>
        ) : null}
      </header>

      {view === "table" ? (
        <table className="computation-table">
          <thead><tr>{table.columns.map(column => <th key={column} scope="col">{column}</th>)}</tr></thead>
          <tbody>
            {table.rows.map((row, index) => (
              <tr key={index}>{row.map((cell, cellIndex) => <td key={cellIndex}>{String(cell)}</td>)}</tr>
            ))}
          </tbody>
        </table>
      ) : series.length ? (
        view === "bar" ? (
          <ul className="computation-bars">
            {series.map(point => (
              <li key={point.label}>
                <span className="computation-bar-label">{point.label}</span>
                <span className="computation-bar" style={{ width: `${Math.round((point.value / maxValue) * 100)}%` }} aria-hidden />
                <span className="computation-bar-value">{point.value}{table.unit ? ` ${table.unit}` : ""}</span>
              </li>
            ))}
          </ul>
        ) : (
          <svg className="computation-line" role="img" viewBox={`0 0 ${Math.max(series.length - 1, 1) * 100} 100`} preserveAspectRatio="none" aria-label="折线图">
            <polyline
              fill="none"
              points={series.map((point, index) => `${index * 100},${100 - Math.round((point.value / maxValue) * 90)}`).join(" ")}
            />
          </svg>
        )
      ) : (
        <p className="computation-note">这份结果没有可绘制的数值列，请查看数据表。</p>
      )}

      {parameters.length && onRecompute ? (
        <div className="computation-parameters">
          {parameters.map(parameter => (
            <label key={parameter.name}>
              <span>{parameter.name}</span>
              <input
                type="number"
                step="any"
                value={values[parameter.name] ?? 0}
                onChange={event => setValues(current => ({ ...current, [parameter.name]: Number(event.target.value) }))}
              />
            </label>
          ))}
          <button type="button" disabled={isRecomputing} onClick={() => void onRecompute(values)}>
            {isRecomputing ? "重新计算中…" : "按新参数重新计算"}
          </button>
        </div>
      ) : null}

      <figcaption className="computation-provenance">{provenanceCopy(payload)}</figcaption>
    </figure>
  );
}
