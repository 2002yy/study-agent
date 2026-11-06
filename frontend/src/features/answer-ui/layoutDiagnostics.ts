/** Host-injected DOM measurements. They describe layout, not task correctness. */
import type { RepairIssue } from "./repairFeedback";

export function parseLayoutDiagnostics(value: unknown): RepairIssue[] | null {
  if (!Array.isArray(value) || value.length > 20) return null;
  return value.every(item => item && typeof item === "object"
    && typeof item.checkId === "string" && item.checkId.length <= 128
    && typeof item.elementId === "string" && item.elementId.length <= 128
    && typeof item.unit === "string" && item.unit.length <= 24
    && typeof item.measured === "number" && Number.isFinite(item.measured)
    && typeof item.threshold === "number" && Number.isFinite(item.threshold)) ? value : null;
}

export const LAYOUT_DIAGNOSTICS = `() => {
  const issues = [];
  const identify = el => {
    if (el.id) return '#' + el.id.slice(0, 120);
    const path = [];
    for (let node = el; node && node !== document.body && path.length < 5; node = node.parentElement) {
      const siblings = Array.from(node.parentElement.children).filter(other => other.tagName === node.tagName);
      path.unshift(node.tagName.toLowerCase() + ':nth-of-type(' + (siblings.indexOf(node) + 1) + ')');
    }
    return path.join(' > ').slice(-128);
  };
  const add = (checkId, elementId, measured, threshold, unit) => {
    if (issues.length < 20 && Number.isFinite(measured)) issues.push({checkId,elementId,measured,threshold,unit});
  };
  Array.from(document.body.querySelectorAll('*')).slice(0, 1000).forEach((el, index) => {
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    if (!rect.width || !rect.height || style.visibility === 'hidden' || style.display === 'none') return;
    const id = identify(el, index);
    if (Array.from(el.childNodes).some(node => node.nodeType === 3 && node.textContent.trim())) {
      let size = parseFloat(style.fontSize);
      if (el instanceof SVGTextElement) { const m = el.getScreenCTM(); if (m) size *= Math.hypot(m.c, m.d); }
      if (size < 14) add('usability-font', id, size, 14, 'px');
    }
    if (el.matches('button,input:not([type=hidden]),select,textarea')) {
      if (rect.width < 40) add('control-width', id, rect.width, 40, 'px');
      if (rect.height < 40) add('control-height', id, rect.height, 40, 'px');
    }
  });
  const overflow = Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) - innerWidth;
  if (overflow > 1) add('horizontal-overflow', 'document', overflow, 0, 'px');
  return issues;
}`;
