import { X } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";

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
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (!open || typeof window === "undefined") return;

    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  useEffect(() => {
    if (!open || typeof document === "undefined") return;

    const previousOverflow = document.body.style.overflow;
    const previousFocus = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    document.body.style.overflow = "hidden";
    closeButtonRef.current?.focus();

    return () => {
      document.body.style.overflow = previousOverflow;
      previousFocus?.focus();
    };
  }, [open]);

  if (!open) return null;
  return (
    <div className="slide-over-root" role="dialog" aria-modal="true" aria-label={title}>
      <button className="slide-over-backdrop" onClick={onClose} aria-label={`关闭${title}`} type="button" />
      <aside className="slide-over">
        <header className="slide-over-header">
          <strong>{title}</strong>
          <button
            ref={closeButtonRef}
            aria-label={`关闭${title}`}
            className="icon-button"
            onClick={onClose}
            type="button"
            title={`关闭${title}`}
          >
            <X size={17} />
          </button>
        </header>
        <div className="slide-over-body">{children}</div>
      </aside>
    </div>
  );
}
