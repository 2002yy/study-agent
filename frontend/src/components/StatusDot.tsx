export function StatusDot({ tone = "neutral" }: { tone?: "good" | "warn" | "neutral" | "bad" }) {
  return <span className={`status-dot ${tone}`} />;
}
