import { useEffect, useRef, useState } from "react";
import "./panelResize.css";

type Panel = "sidebar" | "reading";
export const panelWidthKey = (panel: Panel) => `study-agent:panel-width:${panel}:v1`;

export function panelBounds(panel: Panel, available: number, hasDocument: boolean) {
  return panel === "sidebar"
    ? { min: 180, max: Math.max(180, Math.min(360, available - (hasDocument ? 736 : 400))) }
    : { min: Math.min(360, available / 2), max: Math.max(available / 2, available - 360) };
}
const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value));

function storedWidth(panel: Panel): number | null {
  try {
    const raw = localStorage.getItem(panelWidthKey(panel));
    if (raw === null) return null;
    const value = Number(raw);
    return Number.isFinite(value) && (panel === "sidebar" ? value >= 180 && value <= 360 : value > 0 && value < 1) ? value : null;
  } catch { return null; }
}

/** Display preference only: never writes session or settings APIs. */
export function PanelResizeHandle({ panel }: { panel: Panel }) {
  const handle = useRef<HTMLDivElement>(null);
  const controller = useRef<{ move: (width: number) => void; save: () => void; reset: () => void } | null>(null);
  const drag = useRef<{ pointer: number; x: number; width: number } | null>(null);
  const [size, setSize] = useState({ min: 0, max: 0, value: 0 });
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    const element = handle.current;
    const root = element?.closest<HTMLElement>(panel === "sidebar" ? ".app-shell" : ".reading-layout");
    const target = root?.querySelector<HTMLElement>(panel === "sidebar" ? ".session-sidebar" : ".document-reader");
    if (!element || !root || !target) return;
    const property = panel === "sidebar" ? "--sidebar-width" : "--resized-reader-width";
    let preference = storedWidth(panel);
    let current = target.getBoundingClientRect().width;
    let available = 0;
    let bounds = { min: 0, max: 0 };

    const sync = () => {
      if (!target.offsetWidth || innerWidth <= (panel === "sidebar" ? 1100 : 900)) return;
      const css = getComputedStyle(root);
      available = root.clientWidth - parseFloat(css.paddingLeft || "0") - parseFloat(css.paddingRight || "0") - 16;
      bounds = panelBounds(panel, available, Boolean(root.querySelector(".document-reader")));
      if (preference !== null) {
        current = clamp(panel === "sidebar" ? preference : available * preference, bounds.min, bounds.max);
        root.style.setProperty(property, `${current}px`);
        if (panel === "reading") root.dataset.readingResized = "true";
      } else {
        root.style.removeProperty(property);
        if (panel === "reading") delete root.dataset.readingResized;
      }
      const rect = target.getBoundingClientRect();
      current = rect.width;
      element.style.left = `${rect.right - root.getBoundingClientRect().left + 2}px`;
      setSize(previous => previous.min === bounds.min && previous.max === bounds.max && previous.value === current
        ? previous : { ...bounds, value: current });
    };
    controller.current = {
      move(width) {
        const value = clamp(width, bounds.min, bounds.max);
        preference = panel === "sidebar" ? value : value / available;
        sync();
      },
      save() {
        if (preference === null) return;
        try { localStorage.setItem(panelWidthKey(panel), String(preference)); } catch { /* Keep this view adjustable. */ }
      },
      reset() {
        preference = null;
        try { localStorage.removeItem(panelWidthKey(panel)); } catch { /* Device storage can be disabled. */ }
        sync();
      },
    };
    const onStorage = (event: StorageEvent) => {
      if (event.key === panelWidthKey(panel) || event.key === null) { preference = storedWidth(panel); sync(); }
    };
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(sync);
    observer?.observe(root);
    observer?.observe(target);
    window.addEventListener("resize", sync);
    window.addEventListener("storage", onStorage);
    sync();
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", sync);
      window.removeEventListener("storage", onStorage);
      root.style.removeProperty(property);
      if (panel === "reading") delete root.dataset.readingResized;
      controller.current = null;
    };
  }, [panel]);

  const finish = () => {
    if (!drag.current) return;
    drag.current = null;
    setDragging(false);
    controller.current?.save();
  };
  return <div ref={handle} className={`panel-resize-handle panel-resize-${panel}`}
    role="separator" aria-orientation="vertical" tabIndex={0}
    aria-label={panel === "sidebar" ? "调整左侧导航宽度" : "调整正文与对话宽度"}
    aria-valuemin={Math.round(size.min)} aria-valuemax={Math.round(size.max)} aria-valuenow={Math.round(size.value)}
    aria-valuetext={`${Math.round(size.value)} 像素，双击或回车恢复默认`}
    title="拖动调整宽度，双击恢复默认；方向键微调，回车恢复默认"
    data-dragging={dragging || undefined}
    onDoubleClick={() => controller.current?.reset()}
    onKeyDown={event => {
      const step = event.shiftKey ? 32 : 16;
      const value = event.key === "ArrowLeft" ? size.value - step : event.key === "ArrowRight" ? size.value + step
        : event.key === "Home" ? size.min : event.key === "End" ? size.max : null;
      if (event.key === "Enter") { event.preventDefault(); controller.current?.reset(); }
      if (value !== null) { event.preventDefault(); controller.current?.move(value); controller.current?.save(); }
    }}
    onPointerDown={event => {
      if (!event.isPrimary || event.button !== 0) return;
      event.preventDefault();
      event.currentTarget.focus();
      event.currentTarget.setPointerCapture(event.pointerId);
      drag.current = { pointer: event.pointerId, x: event.clientX, width: size.value };
      setDragging(true);
    }}
    onPointerMove={event => {
      if (drag.current?.pointer !== event.pointerId) return;
      event.preventDefault();
      controller.current?.move(drag.current.width + event.clientX - drag.current.x);
    }}
    onPointerUp={finish} onPointerCancel={finish} onLostPointerCapture={finish}
  />;
}
