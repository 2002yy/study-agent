export function formatScore(value: number | undefined): string {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "-";
  }
  return value.toFixed(3);
}

export function translateStatus(value: string | undefined): string {
  const labels: Record<string, string> = {
    waiting: "等待中",
    skipped: "已跳过",
    found: "已找到",
    not_found: "未找到",
    index_missing: "索引缺失",
    error: "错误",
    preview: "预览",
    succeeded: "成功",
    failed: "失败",
    blocked: "已阻止",
    started: "已开始",
    running: "运行中"
  };
  return labels[value ?? ""] ?? (value || "-");
}

export function basename(path: string): string {
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts.length ? parts[parts.length - 1] : path;
}

export function displayValue(value: unknown): string {
  if (value === null || typeof value === "undefined" || value === "") {
    return "-";
  }
  if (Array.isArray(value)) {
    return value.length ? value.join(", ") : "-";
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}
