import { useSyncExternalStore } from "react";

export const TYPOGRAPHY_KEY = "study-agent:typography:v1";
const CHANGE_EVENT = "study-agent:typography-change";
export const TYPOGRAPHY_OPTIONS = [
  { value: "balanced", label: "黑体正文 · 宋体标题", description: "正文清晰，标题保留书页感" },
  { value: "sans", label: "统一黑体", description: "界面、标题和正文都使用黑体" },
  { value: "serif", label: "宋体阅读", description: "资料正文使用宋体，操作界面保持黑体" },
] as const;
export type TypographyPreset = typeof TYPOGRAPHY_OPTIONS[number]["value"];
let volatilePreference: TypographyPreset | null = null;

function validPreset(value: unknown): value is TypographyPreset {
  return TYPOGRAPHY_OPTIONS.some(option => option.value === value);
}

function snapshot(): TypographyPreset {
  if (volatilePreference) return volatilePreference;
  try {
    const value = window.localStorage.getItem(TYPOGRAPHY_KEY);
    return validPreset(value) ? value : "balanced";
  } catch { return "balanced"; }
}

function subscribe(notify: () => void) {
  const storageChanged = (event: StorageEvent) => {
    if (event.key !== TYPOGRAPHY_KEY && event.key !== null) return;
    volatilePreference = null;
    notify();
  };
  window.addEventListener(CHANGE_EVENT, notify);
  window.addEventListener("storage", storageChanged);
  return () => {
    window.removeEventListener(CHANGE_EVENT, notify);
    window.removeEventListener("storage", storageChanged);
  };
}

export function setTypographyPreference(value: TypographyPreset) {
  if (!validPreset(value)) return;
  try {
    window.localStorage.setItem(TYPOGRAPHY_KEY, value);
    volatilePreference = null;
  } catch { volatilePreference = value; }
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

export function useTypographyPreference() {
  return useSyncExternalStore(subscribe, snapshot, () => "balanced" as const);
}
