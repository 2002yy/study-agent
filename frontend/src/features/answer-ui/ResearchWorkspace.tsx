import { useEffect, useId, useRef, useState, type RefObject } from "react";
import { mergeResearchPresentation, parseResearchPresentation, type ResearchPresentation } from "./researchPresentation";
import "./researchWorkspace.css";
import { BookOpen, Check, ChevronRight, Loader2, X } from "lucide-react";
import { SlideOver } from "../../components/SlideOver";
import { researchStopReasonDisplay } from "../web-lookup/researchStopReason";

const tierNames = { lookup: "Lookup · 快速查找", standard: "Standard · 对照核验", deep: "Deep · 深入研究" };
const statuses: Record<string, string> = { pending: "待处理", running: "研究中", completed: "研究结束", partial: "部分完成", failed: "失败", cancelled: "已停止" };
const readNames: Record<string, string> = { unknown: "读取状态未提供", read: "正文已读取", structured: "结构化数据已读取", failed: "读取失败", skipped: "未读取" };
const supportNames: Record<string, string> = { NOT_EVALUATED: "尚未判断支持关系", SPAN_BOUND: "原文片段已定位", SUPPORT: "存在支持记录，未发布", CONFLICT: "来源存在冲突", INSUFFICIENT: "证据不足" };
const phaseNames: Record<string, string> = { planned: "规划", planning: "规划", searching: "搜索", assessing: "筛选来源", reading: "读取正文", gating: "证据核验", synthesizing: "整理证据", completed: "结束", standard_handoff: "对照研究", deep_handoff: "深入研究" };
const display = (names: Record<string, string>, value: string, fallback: string) =>
  Object.prototype.hasOwnProperty.call(names, value) ? names[value] : fallback;

/** Shared research presentation state for one bound assistant turn. */
export type ResearchControl = {
  snapshot: ResearchPresentation | null;
  unavailable: boolean;
  refresh: () => void;
};

export function useResearchPresentation({ sessionId, turnId, initial }: {
  sessionId: string; turnId: string; initial?: ResearchPresentation;
}): ResearchControl {
  const initialMatches = Boolean(initial && initial.session_id === sessionId && initial.turn_id === turnId);
  const [snapshot, setSnapshot] = useState<ResearchPresentation | null>(initialMatches ? initial! : null);
  const [unavailable, setUnavailable] = useState(false);
  const [refreshTick, setRefreshTick] = useState(0);
  const current = useRef<ResearchPresentation | null>(initialMatches ? initial! : null);
  const resumePolling = useRef<(() => void) | null>(null);
  useEffect(() => {
    if (!sessionId || !turnId) {
      current.current = null;
      setSnapshot(null);
      return;
    }
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
    if (!sessionId || !turnId) return;
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
  }, [sessionId, turnId, refreshTick]);
  return { snapshot, unavailable, refresh: () => setRefreshTick((n) => n + 1) };
}

export function useResearchMobile(maxWidth = 1100) {
  const [mobile, setMobile] = useState(() => typeof window !== "undefined"
    && typeof window.matchMedia === "function" && window.matchMedia(`(max-width: ${maxWidth}px)`).matches);
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia(`(max-width: ${maxWidth}px)`);
    const change = () => setMobile(media.matches);
    media.addEventListener("change", change);
    return () => media.removeEventListener("change", change);
  }, [maxWidth]);
  return mobile;
}

/** The narrative research status line. Rendered inside the bound assistant message. */
export function ResearchStatusRow({ snapshot, unavailable, hasAnswer, open, onToggle, openerRef, panelId, mobile }: {
  snapshot: ResearchPresentation; unavailable: boolean; hasAnswer: boolean;
  open: boolean; onToggle: () => void; openerRef?: RefObject<HTMLButtonElement | null>;
  panelId: string; mobile: boolean;
}) {
  const active = [...snapshot.blocks].reverse().find(b => ["running", "pending"].includes(b.research_status));
  const latest = active ?? snapshot.blocks[snapshot.blocks.length - 1];
  const waiting = snapshot.watch || Boolean(active);
  const title = !Object.prototype.hasOwnProperty.call(statuses, latest.research_status) ? "研究状态待确认" : waiting ? "研究进行中" : latest.research_status === "failed" ? "研究暂未完成"
    : latest.research_status === "cancelled" ? "研究已停止" : latest.research_status === "partial" ? "研究已结束，仍有待确认问题" : "研究已结束";
  const narrative = waiting ? `${display(phaseNames, latest.research_phase ?? latest.stage, "核对资料")}，${hasAnswer ? "已有回答可继续阅读" : "核验后展示可用结果"}。`
    : snapshot.audit_status === "audited" ? "深入研究记录已审计，候选内容尚未获准发布。"
    : "回答与研究资料可继续查看；来源记录不等于结论已核实。";
  return <div className="research-status-row">
    <span className="research-status-icon" aria-hidden="true">{waiting ? <Loader2 size={16} className="spin"/> : <BookOpen size={16}/>}</span>
    <div role="status"><strong>{title}</strong><span>{unavailable ? "连接暂不可用，保留上次研究记录。" : narrative}</span></div>
    <button ref={openerRef} type="button" aria-expanded={open} aria-controls={panelId} aria-haspopup={mobile ? "dialog" : undefined} onClick={onToggle}>研究资料<ChevronRight size={14}/></button>
  </div>;
}

/** Panel-level research dossier: desktop sidebar or mobile slide-over. */
export function ResearchPanel({ control, sourceRequest, open, onClose, panelId, mobile, contentRef }: {
  control: ResearchControl; sourceRequest?: { url: string; key: number } | null;
  open: boolean; onClose: () => void; panelId: string; mobile: boolean;
  contentRef?: RefObject<HTMLDivElement | null>;
}) {
  const localContent = useRef<HTMLDivElement>(null);
  const content = contentRef ?? localContent;
  const { snapshot, refresh } = control;
  useEffect(() => {
    if (!open || !sourceRequest) return;
    const frame = requestAnimationFrame(() => {
      const target = Array.from(content.current?.querySelectorAll<HTMLElement>("[data-source-url]") ?? [])
        .find(element => element.dataset.sourceUrl === sourceRequest.url);
      target?.scrollIntoView?.({ block: "nearest" }); target?.focus();
    });
    return () => cancelAnimationFrame(frame);
  }, [sourceRequest, open, mobile, content]);
  if (!snapshot?.blocks.length) return null;
  const sources = snapshot.blocks.flatMap(b => b.sources).filter((s, i, all) => all.findIndex(other => other.url === s.url) === i);
  const gaps = snapshot.blocks.flatMap(b => b.gaps).filter(g => g.research_state === "OPEN" || g.support_status !== "SUPPORT");
  const details = <div className="research-dossier" ref={content}>
    <p className="research-authority-note">资料用于追溯查证过程。是否可用于回答，由原有证据与发布规则决定。</p>
    <ol className="research-journey" aria-label="研究进展">
      {snapshot.blocks.map(b => <li key={b.block_id}>
        {["pending", "running"].includes(b.research_status) ? <Loader2 size={14} className="spin"/> : b.research_status === "completed" ? <Check size={14}/> : <span className="research-step-dot"/>}
        <span>{({ lookup: "快速查证", standard: "对照核验", deep: "深入研究" })[b.tier]}</span>
        <small>{display(statuses, b.research_status, "状态未识别")}</small>
      </li>)}
    </ol>
    {snapshot.audit_status === "audited" ? <p className="research-audit-note">Deep 审计候选已就绪，尚未获准发布；不会追加为正式回答。</p> : null}
    {snapshot.audit_integrity === "invalid" ? <p className="research-audit-note">审计记录未通过完整性检查，未用于正式答案。</p> : null}
    {gaps.length ? <section aria-label="仍待确认"><h3>仍待确认</h3><ul className="research-open-questions">{gaps.map(g => <li key={g.block_id}>{g.field}<small>{display(supportNames, g.support_status, "支持关系未提供")}</small></li>)}</ul></section> : null}
    <section aria-label="本次研究来源"><h3>研究资料</h3>
      {sources.length ? <ol className="research-readable-sources">{sources.map((s, i) => <li key={s.url} data-source-url={s.url} tabIndex={-1} className={sourceRequest?.url === s.url ? "is-selected" : ""}>
        <span className="research-source-number">{i + 1}</span><div><a href={s.url} target="_blank" rel="noreferrer noopener">{s.title === s.url ? new URL(s.url).hostname : s.title}</a>
        <small>{new URL(s.url).hostname} · {readNames[s.read_status]}</small></div>
      </li>)}</ol> : <p>尚未取得可展示的来源。</p>}
    </section>
    <details className="research-diagnostics"><summary>技术详情与证据关联</summary>
    <div className="research-tier-list">{snapshot.blocks.map(b => <details key={b.block_id}>
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
      {snapshot.truncated ? <p>研究记录预览已截断。</p> : null}
    </details>
    <button className="research-refresh" type="button" onClick={refresh} aria-label="刷新研究状态">刷新研究状态</button>
  </div>;
  return mobile ? <SlideOver open={open} title="研究资料" onClose={onClose}><div id={panelId}>{details}</div></SlideOver>
    : open ? <aside id={panelId} className="research-sidebar" aria-label="研究资料" onKeyDown={event => { if (event.key === "Escape") { event.stopPropagation(); onClose(); } }}>
      <header><h2>研究资料</h2><button type="button" aria-label="关闭研究资料" onClick={onClose}><X size={18}/></button></header>{details}
    </aside> : null;
}

/**
 * Self-contained workspace: owns the fetch and renders status row + dossier in one region.
 * Kept for direct/legacy usage; the conversation panel uses {@link useResearchPresentation}
 * so the status row can live inside the bound assistant message.
 */
export function ResearchWorkspace({ sessionId, turnId, initial, hasAnswer = false, onOpenChange, onSnapshot, sourceRequest }: {
  sessionId: string; turnId: string; initial?: ResearchPresentation; hasAnswer?: boolean;
  onOpenChange?: (open: boolean) => void;
  onSnapshot?: (snapshot: ResearchPresentation | null) => void;
  sourceRequest?: { url: string; key: number } | null;
}) {
  const [open, setOpen] = useState(false);
  const mobile = useResearchMobile();
  const panelId = useId();
  const opener = useRef<HTMLButtonElement>(null);
  const control = useResearchPresentation({ sessionId, turnId, initial });
  useEffect(() => { onOpenChange?.(open && !mobile); return () => onOpenChange?.(false); }, [open, mobile, onOpenChange]);
  useEffect(() => { if (sourceRequest) setOpen(true); }, [sourceRequest]);
  useEffect(() => { onSnapshot?.(control.snapshot); }, [control.snapshot, onSnapshot]);
  const close = () => { setOpen(false); opener.current?.focus(); };
  if (!control.snapshot?.blocks.length || control.snapshot.session_id !== sessionId || control.snapshot.turn_id !== turnId) return null;
  return <section className="research-workspace" aria-label="研究工作区">
    <ResearchStatusRow snapshot={control.snapshot} unavailable={control.unavailable} hasAnswer={hasAnswer}
      open={open} onToggle={() => setOpen(value => !value)} openerRef={opener} panelId={panelId} mobile={mobile} />
    <ResearchPanel control={control} sourceRequest={sourceRequest} open={open} onClose={close} panelId={panelId} mobile={mobile} />
  </section>;
}
