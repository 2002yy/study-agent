import { X } from "lucide-react";
import { useEffect, type ReactNode } from "react";

export function SlideOver({
  open,
  title,
  onClose,
  children,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="slide-over-root" role="dialog" aria-modal="true" aria-label={title}>
      <button className="slide-over-backdrop" onClick={onClose} aria-label="关闭" type="button" />
      <aside className="slide-over">
        <header className="slide-over-header">
          <strong>{title}</strong>
          <button className="icon-button" onClick={onClose} type="button" title="关闭">
            <X size={17} />
          </button>
        </header>
        <div className="slide-over-body">{children}</div>
      </aside>
    </div>
  );
}
