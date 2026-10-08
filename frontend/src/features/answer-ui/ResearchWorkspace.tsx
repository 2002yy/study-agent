import { useEffect, useRef, useState } from "react";
import { mergeResearchPresentation, parseResearchPresentation, type ResearchPresentation } from "./researchPresentation";
import "./researchWorkspace.css";
import { researchStopReasonDisplay } from "../web-lookup/researchStopReason";

const tierNames = { lookup: "Lookup · 快速查找", standard: "Standard · 对照核验", deep: "Deep · 深入研究" };
const statuses: Record<string, string> = { pending: "待处理", running: "研究中", completed: "研究结束", partial: "部分完成", failed: "失败", cancelled: "已停止" };
const readNames: Record<string, string> = { unknown: "读取状态未提供", read: "正文已读取", structured: "结构化数据已读取", failed: "读取失败", skipped: "未读取" };
const supportNames: Record<string, string> = { NOT_EVALUATED: "尚未判断支持关系", SPAN_BOUND: "原文片段已定位", SUPPORT: "存在支持记录，未发布", CONFLICT: "来源存在冲突", INSUFFICIENT: "证据不足" };
const phaseNames: Record<string, string> = { planned: "规划", planning: "规划", searching: "搜索", assessing: "筛选来源", reading: "读取正文", gating: "证据核验", synthesizing: "整理证据", completed: "结束", standard_handoff: "对照研究", deep_handoff: "深入研究" };
const display = (names: Record<string, string>, value: string, fallback: string) =>
  Object.prototype.hasOwnProperty.call(names, value) ? names[value] : fallback;

export function ResearchWorkspace({ sessionId, turnId, initial }: { sessionId: string; turnId: string; initial?: ResearchPresentation }) {
  const [snapshot, setSnapshot] = useState<ResearchPresentation | null>(initial ?? null);
  const [unavailable, setUnavailable] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const current = useRef(snapshot);
  const resumePolling = useRef<(() => void) | null>(null);
  useEffect(() => {
    if (initial && initial.session_id === sessionId && initial.turn_id === turnId) {
      current.current = mergeResearchPresentation(current.current, initial);
      setSnapshot(current.current);
      if (current.current.watch) resumePolling.current?.();
    } else if (current.current?.session_id !== sessionId || current.current?.turn_id !== turnId) {
      current.current = null;
      setSnapshot(null);
    }
  }, [initial, sessionId, turnId]);
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController;
    let inFlight = false;
    const load = async () => {
      timer = undefined;
      if (document.visibilityState === "hidden") { timer = setTimeout(load, 5000); return; }
      inFlight = true;
      controller = new AbortController();
      const requestController = controller;
      const deadline = setTimeout(() => requestController.abort(), 8000);
      let watch = current.current?.session_id === sessionId && current.current?.turn_id === turnId
        ? current.current.watch : false;
      try {
        const token = import.meta.env.VITE_STUDY_AGENT_API_TOKEN ?? "";
        const response = await fetch(`${import.meta.env.VITE_API_BASE_URL ?? ""}/sessions/${encodeURIComponent(sessionId)}/turns/${encodeURIComponent(turnId)}/research-presentation`, {
          signal: controller.signal, headers: token ? { "X-Study-Agent-Token": token } : {},
        });
        if (!response.ok) { watch = watch && response.status >= 500; throw new Error("unavailable"); }
        const data = parseResearchPresentation(await response.json());
        if (!data || data.session_id !== sessionId || data.turn_id !== turnId) {
          watch = false; throw new Error("invalid snapshot");
        }
        if (active) {
          current.current = mergeResearchPresentation(current.current, data);
          setSnapshot(current.current); setUnavailable(false);
          watch = current.current.watch;
        }
      } catch { if (active) setUnavailable(true); }
      finally { clearTimeout(deadline); inFlight = false; }
      if (active && watch) timer = setTimeout(load, 5000);
    };
    resumePolling.current = () => { if (active && !inFlight && timer === undefined) void load(); };
    void load();
    return () => { active = false; resumePolling.current = null; clearTimeout(timer); controller?.abort(); };
  }, [sessionId, turnId, refresh]);
  if (!snapshot?.blocks.length || snapshot.session_id !== sessionId || snapshot.turn_id !== turnId) return null;
  return <section className="research-workspace" aria-label="研究工作区">
    <header><strong>研究工作区</strong><span>仅观察 · 不改变正式答案</span><button type="button" onClick={() => setRefresh(n => n + 1)} aria-label="刷新研究状态">刷新</button></header>
    {unavailable ? <p role="status">状态更新暂不可用，以下是最后一次成功读取的快照。</p> : null}
    <div className="research-tier-list">{snapshot.blocks.map(b => <details key={b.block_id} open={b.research_status === "running"}>
      <summary><strong>{tierNames[b.tier]}</strong><span>{display(statuses, b.research_status, "状态未识别")}</span></summary>
      <p>当前阶段：{display(phaseNames, b.research_phase ?? b.stage, "未提供阶段细节")}{b.tier === "deep" ? ` · 研究波次 ${b.wave ?? "—"}` : ""}</p>
      <p className="research-counts">候选 {b.candidate_count ?? "—"} · 读取成功 {b.read_count ?? "—"} · 关键缺口 {b.open_critical_gap_count ?? "—"}{b.read_attempt_count !== null ? ` · 读取尝试 ${b.read_attempt_count}` : ""}</p>
      <small>— 表示未提供数据。读取成功不等于支持结论。</small>
      {b.conflict_count !== null ? <p>尚未解决的证据冲突：{b.conflict_count}</p> : null}
      {b.sources.length ? <ul>{b.sources.map(s => <li key={s.block_id}><a href={s.url} target="_blank" rel="noreferrer noopener">{s.title}</a><span>{readNames[s.read_status]} · 来源版本 {s.source_truth_version}</span></li>)}</ul> : <p>当前快照尚无可展示的来源。</p>}
      {b.gaps.length ? <table><thead><tr><th>待研究字段</th><th>研究状态</th><th>支持关系</th></tr></thead><tbody>{b.gaps.map(g => <tr key={g.block_id}><td>{g.field}</td><td>{g.research_state === "SOURCE_ACQUIRED" ? "已取得来源" : "缺口未闭合"}</td><td>{supportNames[g.support_status]}</td></tr>)}</tbody></table> : null}
      {b.bindings.length ? <details><summary>查看证据关联记录（尚未发布）</summary><ul>{b.bindings.map(r => <li key={r.block_id}><span>证据 {r.evidence_id} → 问题 {r.claim_id} · {r.relation === "supports" ? "提取为支持" : "提取为反例"}</span><a href={r.source_url} target="_blank" rel="noreferrer noopener">查看来源{r.locator ? ` · ${r.locator}` : ""}</a></li>)}</ul></details> : null}
      {b.stop_reason ? <p>停止原因：{researchStopReasonDisplay(b.stop_reason, "原因未提供")}</p> : null}
      {b.sources_truncated ? <p>来源预览已截断。</p> : null}
      <small>研究版本 {b.revision} · 更新时间 {b.updated_at}</small>
    </details>)}</div>
    {snapshot.audit_status === "audited" ? <p>Deep 审计候选已就绪，尚未获准发布；正式答案保持原版本。</p> : null}
    {snapshot.audit_integrity === "invalid" ? <p>审计记录未通过完整性检查，未用于正式答案。</p> : null}
    {snapshot.truncated ? <p>研究记录预览已截断。</p> : null}
  </section>;
}
