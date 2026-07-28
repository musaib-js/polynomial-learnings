import {
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { IconCopy, IconCheck, IconRefresh, IconX } from "./icons";
import { shortId } from "../lib/format";
import { useApp, type Toast } from "../context/AppContext";

export function Spinner({ size = 16 }: { size?: number }) {
  return (
    <span
      className="spin"
      style={{
        width: size,
        height: size,
        display: "inline-block",
        border: "2px solid var(--border-strong)",
        borderTopColor: "var(--accent)",
        borderRadius: "999px",
      }}
    />
  );
}

export function SectionTitle({
  eyebrow,
  title,
  right,
}: {
  eyebrow?: string;
  title: string;
  right?: ReactNode;
}) {
  return (
    <div className="flex items-end justify-between gap-4 mb-3">
      <div>
        {eyebrow && <div className="eyebrow mb-1">{eyebrow}</div>}
        <h2
          className="text-[15px] font-semibold"
          style={{ color: "var(--text-strong)" }}
        >
          {title}
        </h2>
      </div>
      {right}
    </div>
  );
}

export function Stat({
  label,
  value,
  sub,
  icon,
  muted = false,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  icon?: ReactNode;
  muted?: boolean;
}) {
  return (
    <div className="panel px-4 py-3.5" style={muted ? { opacity: 0.7 } : undefined}>
      <div className="flex items-center justify-between">
        <div className="eyebrow">{label}</div>
        {icon && <span style={{ color: "var(--faint)" }}>{icon}</span>}
      </div>
      <div
        className="mt-2 text-[26px] leading-none font-semibold tabular-nums"
        style={{ color: "var(--text-strong)" }}
      >
        {value}
      </div>
      {sub !== undefined && (
        <div className="mt-1.5 text-[12px]" style={{ color: "var(--muted)" }}>
          {sub}
        </div>
      )}
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  hint,
  action,
}: {
  icon?: ReactNode;
  title: string;
  hint?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center text-center px-6 py-14">
      {icon && (
        <div
          className="mb-3 grid place-items-center rounded-full"
          style={{
            width: 44,
            height: 44,
            background: "var(--panel-2)",
            border: "1px solid var(--border)",
            color: "var(--faint)",
          }}
        >
          {icon}
        </div>
      )}
      <div
        className="text-[14px] font-medium"
        style={{ color: "var(--text-strong)" }}
      >
        {title}
      </div>
      {hint && (
        <div
          className="mt-1.5 text-[13px] max-w-md"
          style={{ color: "var(--muted)" }}
        >
          {hint}
        </div>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function CopyId({
  id,
  label = "id",
  head = 8,
}: {
  id: string;
  label?: string;
  head?: number;
}) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      className="btn-ghost inline-flex items-center gap-1.5 rounded-md px-1.5 py-0.5 mono"
      style={{ color: "var(--faint)", cursor: "pointer", fontSize: 11.5 }}
      title={`Copy ${label}: ${id}`}
      onClick={(e) => {
        e.stopPropagation();
        navigator.clipboard?.writeText(id);
        setCopied(true);
        setTimeout(() => setCopied(false), 1200);
      }}
    >
      {copied ? <IconCheck size={12} /> : <IconCopy size={12} />}
      <span>{shortId(id, head)}</span>
    </button>
  );
}

export function RefreshButton({
  onClick,
  loading,
  label = "Refresh",
}: {
  onClick: () => void;
  loading?: boolean;
  label?: string;
}) {
  return (
    <button className="btn btn-sm" onClick={onClick} disabled={loading}>
      {loading ? <Spinner size={13} /> : <IconRefresh size={13} />}
      {label}
    </button>
  );
}

export function Modal({
  title,
  subtitle,
  onClose,
  children,
  footer,
  wide = false,
}: {
  title: string;
  subtitle?: ReactNode;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [onClose]);

  // Portaled straight to <body>: any ancestor with a CSS transform/filter
  // animation (e.g. this app's own `.animate-in`, used on nearly every
  // screen's root div) creates a new containing block for `position: fixed`
  // descendants — even after the animation finishes, since `animation-fill-
  // mode: both` keeps it "attached". Left in place, that silently shrinks
  // this overlay down to that ancestor's content box instead of the
  // viewport (it was observed tracking a table's height). Rendering into
  // `document.body` sidesteps the issue entirely, regardless of where the
  // modal is invoked from.
  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-start justify-center p-4 sm:p-8 overflow-y-auto"
      style={{ background: "rgba(0,0,0,0.55)", backdropFilter: "blur(2px)" }}
      onClick={onClose}
    >
      <div
        className="panel w-full animate-in my-auto"
        style={{
          maxWidth: wide ? 760 : 560,
          background: "var(--bg-elevated)",
          boxShadow: "0 24px 60px rgba(0,0,0,0.5)",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4 px-5 pt-4 pb-3 border-b">
          <div>
            <h3
              className="text-[15px] font-semibold"
              style={{ color: "var(--text-strong)" }}
            >
              {title}
            </h3>
            {subtitle && (
              <div className="text-[12.5px] mt-0.5" style={{ color: "var(--muted)" }}>
                {subtitle}
              </div>
            )}
          </div>
          <button className="btn-ghost rounded-md p-1.5" onClick={onClose} aria-label="Close">
            <IconX size={16} />
          </button>
        </div>
        <div className="px-5 py-4">{children}</div>
        {footer && (
          <div className="flex items-center justify-end gap-2 px-5 py-3.5 border-t">
            {footer}
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}

export function Tag({ children }: { children: ReactNode }) {
  return (
    <span
      className="inline-flex items-center rounded-md px-1.5 h-[19px] text-[11px] font-medium"
      style={{
        background: "var(--panel-2)",
        border: "1px solid var(--border)",
        color: "var(--muted)",
      }}
    >
      {children}
    </span>
  );
}

const TOAST_HUE: Record<Toast["kind"], string> = {
  success: "var(--ok)",
  error: "var(--danger)",
  info: "var(--info)",
};

export function Toaster() {
  const { toasts, dismissToast } = useApp();
  return (
    <div className="fixed bottom-4 right-4 z-[60] flex flex-col gap-2 w-[340px] max-w-[calc(100vw-2rem)]">
      {toasts.map((t) => (
        <div
          key={t.id}
          className="panel animate-in px-3.5 py-3 flex items-start gap-3"
          style={{ background: "var(--bg-elevated)", boxShadow: "0 10px 30px rgba(0,0,0,0.4)" }}
        >
          <span
            className="mt-1.5 shrink-0 rounded-full"
            style={{ width: 7, height: 7, background: TOAST_HUE[t.kind] }}
          />
          <div className="min-w-0 flex-1">
            <div className="text-[13px] font-medium" style={{ color: "var(--text-strong)" }}>
              {t.title}
            </div>
            {t.detail && (
              <div className="text-[12px] mt-0.5 break-words" style={{ color: "var(--muted)" }}>
                {t.detail}
              </div>
            )}
          </div>
          <button
            className="btn-ghost rounded p-1 shrink-0"
            style={{ color: "var(--faint)" }}
            onClick={() => dismissToast(t.id)}
            aria-label="Dismiss"
          >
            <IconX size={13} />
          </button>
        </div>
      ))}
    </div>
  );
}
