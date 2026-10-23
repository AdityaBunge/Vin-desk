import { AlertTriangle, CheckCircle2, Inbox, Info, Loader2, X, XCircle } from "lucide-react";
import {
  type ButtonHTMLAttributes,
  type ReactNode,
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { label as humanise } from "@/lib/format";
import { ApiError } from "@/services/api";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

// --- Buttons ---------------------------------------------------------------------------

type Variant = "primary" | "secondary" | "danger" | "ghost";
const VARIANTS: Record<Variant, string> = {
  primary: "bg-gradient-to-b from-brand-600 to-brand-800 text-white shadow-md shadow-brand-900/25 hover:from-brand-700 hover:to-brand-900 hover:shadow-lg hover:shadow-brand-900/30 disabled:from-brand-300 disabled:to-brand-300 disabled:shadow-none",
  secondary: "border border-slate-900/10 bg-white/75 text-slate-700 shadow-xs hover:border-slate-900/15 hover:bg-white hover:text-slate-900 disabled:bg-white/50 disabled:text-slate-400",
  danger: "bg-gradient-to-b from-red-500 to-red-700 text-white shadow-md shadow-red-900/20 hover:from-red-600 hover:to-red-800 disabled:from-red-300 disabled:to-red-300 disabled:shadow-none",
  ghost: "text-brand-700 hover:bg-brand-500/10 disabled:text-slate-400",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: "sm" | "md";
  loading?: boolean;
}
export function Button({ variant = "primary", size = "md", loading, className, children, disabled, ...rest }: ButtonProps) {
  return (
    <button
      type="button"
      {...rest}
      disabled={disabled || loading}
      className={cx(
        "inline-flex items-center justify-center gap-1.5 rounded-lg font-medium whitespace-nowrap transition-[background-color,border-color,color,box-shadow,transform] duration-150 select-none enabled:active:scale-[0.98] disabled:cursor-not-allowed",
        size === "sm" ? "h-8 rounded-lg px-2.5 text-xs" : "h-10 rounded-xl px-4 text-sm",
        VARIANTS[variant],
        className,
      )}
    >
      {loading && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
      {children}
    </button>
  );
}

// --- Layout primitives -----------------------------------------------------------------

export function Card({ title, actions, children, className }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cx("glass rounded-2xl", className)}>
      {(title || actions) && (
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-900/[0.06] px-4 py-3 sm:px-5">
          <h2 className="text-[15px] font-semibold tracking-tight text-slate-900">{title}</h2>
          <div className="flex flex-wrap items-center gap-2">{actions}</div>
        </header>
      )}
      <div className="p-4 sm:p-5">{children}</div>
    </section>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3 sm:mb-6">
      <div className="min-w-0">
        <h1 className="flex items-center gap-3 text-xl font-semibold tracking-tight text-slate-900 sm:text-2xl">
          <span aria-hidden className="h-6 w-1.5 shrink-0 rounded-full bg-gradient-to-b from-brand-400 to-brand-700" />{title}
        </h1>
        {subtitle && <p className="mt-1 pl-[1.125rem] text-sm text-slate-500">{subtitle}</p>}
      </div>
      <div className="no-print flex w-full flex-wrap items-center gap-2 sm:w-auto">{actions}</div>
    </div>
  );
}

export function Spinner({ label = "Loading..." }: { label?: string }) {
  return (
    <div role="status" className="flex items-center justify-center gap-2 p-10 text-sm text-slate-500">
      <Loader2 className="h-5 w-5 animate-spin text-brand-500" aria-hidden />
      {label}
    </div>
  );
}

export function EmptyState({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 px-4 py-10 text-center">
      <span className="mb-1 rounded-2xl bg-slate-500/[0.08] p-3"><Inbox className="h-6 w-6 text-slate-400" aria-hidden /></span>
      <p className="text-sm font-medium text-slate-700">{title}</p>
      {hint && <p className="max-w-md text-sm text-slate-500">{hint}</p>}
      {action}
    </div>
  );
}

export function errorText(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Something went wrong";
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex flex-col items-center gap-2 px-4 py-10 text-center">
      <span className="mb-1 rounded-2xl bg-red-500/10 p-3"><AlertTriangle className="h-6 w-6 text-red-500" aria-hidden /></span>
      <p className="text-sm font-medium text-slate-800">{errorText(error)}</p>
      {onRetry && (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

const ALERT_TONES = {
  info: { box: "border-brand-500/20 bg-brand-500/[0.07] text-brand-900", icon: Info, iconClass: "text-brand-500" },
  warn: { box: "border-amber-500/30 bg-amber-400/[0.12] text-amber-950", icon: AlertTriangle, iconClass: "text-amber-500" },
  error: { box: "border-red-500/25 bg-red-500/[0.08] text-red-900", icon: XCircle, iconClass: "text-red-500" },
  success: { box: "border-emerald-500/25 bg-emerald-500/[0.08] text-emerald-900", icon: CheckCircle2, iconClass: "text-emerald-500" },
};

export function Alert({ tone = "info", children }: { tone?: "info" | "warn" | "error" | "success"; children: ReactNode }) {
  const t = ALERT_TONES[tone];
  const Icon = t.icon;
  return (
    <div role={tone === "error" ? "alert" : "status"} className={cx("flex items-start gap-2.5 rounded-xl border px-3 py-2.5 text-sm backdrop-blur-sm", t.box)}>
      <Icon className={cx("mt-0.5 h-4 w-4 shrink-0", t.iconClass)} aria-hidden />
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}

// --- Status badge ----------------------------------------------------------------------

const GREEN = "bg-emerald-500/10 text-emerald-700 ring-emerald-600/20";
const AMBER = "bg-amber-400/15 text-amber-800 ring-amber-600/25";
const RED = "bg-red-500/10 text-red-700 ring-red-600/20";
const BLUE = "bg-brand-500/10 text-brand-700 ring-brand-600/20";
const GREY = "bg-slate-500/10 text-slate-600 ring-slate-500/20";
const PURPLE = "bg-violet-500/10 text-violet-700 ring-violet-600/20";
const STATUS_TONE: Record<string, string> = {
  RECEIVED: BLUE, AWAITING_ASSIGNMENT: AMBER, INSPECTION_IN_PROGRESS: BLUE, AWAITING_ESTIMATE_APPROVAL: AMBER,
  AWAITING_PARTS: AMBER, READY_FOR_SERVICE: BLUE, IN_SERVICE: BLUE, AWAITING_QUALITY_CHECK: PURPLE,
  AWAITING_MANAGER_REVIEW: PURPLE, READY_FOR_BILLING: PURPLE, READY_FOR_DELIVERY: GREEN, COMPLETED: GREEN,
  ON_HOLD: GREY, CANCELLED: GREY,
  PENDING: AMBER, APPROVED: GREEN, REJECTED: RED, SUPERSEDED: GREY, DRAFT: GREY, AWAITING_CUSTOMER_APPROVAL: AMBER,
  PARTIALLY_RESERVED: AMBER, RESERVED: BLUE, PARTIALLY_ISSUED: AMBER, ISSUED: GREEN, UNAVAILABLE: RED,
  PARTIALLY_FULFILLED: AMBER, FULFILLED: GREEN, PROPOSED: AMBER, AVAILABLE: GREEN,
  PENDING_APPROVAL: AMBER, PARTIALLY_RECEIVED: AMBER,
  FINALISED: GREEN, UNPAID: RED, PARTIALLY_PAID: AMBER, PAID: GREEN,
  QUEUED: BLUE, SENT: BLUE, DELIVERED: GREEN, FAILED: RED, RETRY_SCHEDULED: AMBER, SKIPPED: GREY,
  DELIVERY_STATUS_UNKNOWN: BLUE, SIMULATED: PURPLE,
  PASS: GREEN, FAIL: RED, LOW: GREY, NORMAL: GREY, HIGH: AMBER, URGENT: RED,
  ACCEPTED: GREEN, TEMPORARY_FAILURE: AMBER, PERMANENT_FAILURE: RED,
};
const STATUS_TEXT: Record<string, string> = {
  DELIVERY_STATUS_UNKNOWN: "Sent (delivery unconfirmed)",
  SIMULATED: "Simulated (not sent)",
  SENT: "Sent (awaiting receipt)",
};

export function StatusBadge({ status }: { status: string | null | undefined }) {
  if (!status) return null;
  return (
    <span className={cx("inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap ring-1 ring-inset", STATUS_TONE[status] ?? GREY)}>
      <span className="h-1.5 w-1.5 rounded-full bg-current opacity-70" aria-hidden />
      {STATUS_TEXT[status] ?? humanise(status)}
    </span>
  );
}

// --- Form fields -----------------------------------------------------------------------

export function Field({ label, error, hint, required, children, className }: {
  label: string; error?: string; hint?: string; required?: boolean; children: (id: string, describedBy?: string) => ReactNode; className?: string;
}) {
  const id = useId();
  const describedBy = error ? `${id}-err` : hint ? `${id}-hint` : undefined;
  return (
    <div className={className}>
      <label htmlFor={id} className="mb-1.5 block text-[13px] font-medium text-slate-700">
        {label}
        {required && <span className="text-red-600" aria-hidden> *</span>}
      </label>
      {children(id, describedBy)}
      {error ? (
        <p id={`${id}-err`} role="alert" className="mt-1 text-xs text-red-600">{error}</p>
      ) : hint ? (
        <p id={`${id}-hint`} className="mt-1 text-xs text-slate-500">{hint}</p>
      ) : null}
    </div>
  );
}

export function DescriptionList({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-3.5 sm:grid-cols-2">
      {items.map(([term, value]) => (
        <div key={term} className="flex min-w-0 flex-col gap-0.5">
          <dt className="text-xs text-slate-500">{term}</dt>
          <dd className="text-sm font-medium break-words whitespace-pre-wrap text-slate-900">{value || "-"}</dd>
        </div>
      ))}
    </dl>
  );
}

// --- Modal & confirmation --------------------------------------------------------------

/** Centred dialog on larger screens, bottom sheet on phones. */
export function Modal({ open, title, onClose, children, footer, wide }: {
  open: boolean; title: string; onClose: () => void; children: ReactNode; footer?: ReactNode; wide?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    ref.current?.focus();
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
    };
  }, [open, onClose]);
  if (!open) return null;
  // Portal to <body>: a frosted (backdrop-filter) ancestor would otherwise trap this fixed overlay inside it.
  return createPortal(
    <div className="no-print fixed inset-0 z-50 flex animate-fade-in items-end justify-center bg-slate-900/30 backdrop-blur-[3px] sm:items-center sm:p-4"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={ref} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby={titleId}
        className={cx("glass-strong flex max-h-[92dvh] w-full animate-sheet-in flex-col rounded-t-3xl outline-none sm:max-h-[88dvh] sm:animate-[pop_420ms_cubic-bezier(0.34,1.56,0.64,1)_both] sm:rounded-3xl", wide ? "sm:max-w-3xl" : "sm:max-w-lg")}>
        <div className="mx-auto mt-2 h-1 w-10 rounded-full bg-slate-900/15 sm:hidden" aria-hidden />
        <header className="flex items-center justify-between gap-3 px-5 pt-3 pb-3 sm:pt-4">
          <h2 id={titleId} className="text-base font-semibold tracking-tight text-slate-900">{title}</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded-lg p-1.5 text-slate-500 transition-colors hover:bg-slate-900/5 hover:text-slate-800">
            <X className="h-4 w-4" />
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 pb-5">{children}</div>
        {footer && (
          <footer className="flex flex-col-reverse gap-2 border-t border-slate-900/[0.06] px-5 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] sm:flex-row sm:flex-wrap sm:justify-end sm:pb-3 [&>*]:w-full sm:[&>*]:w-auto">
            {footer}
          </footer>
        )}
      </div>
    </div>,
    document.body,
  );
}

interface ConfirmOptions {
  title: string;
  message: ReactNode;
  confirmLabel?: string;
  danger?: boolean;
  /** Ask for a reason (required) and pass it to the resolver. */
  reason?: { label: string; minLength?: number };
}
type ConfirmResult = { ok: boolean; reason: string };
const ConfirmContext = createContext<(opts: ConfirmOptions) => Promise<ConfirmResult>>(async () => ({ ok: false, reason: "" }));
export const useConfirm = () => useContext(ConfirmContext);

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<(ConfirmOptions & { resolve: (r: ConfirmResult) => void }) | null>(null);
  const [reason, setReason] = useState("");
  const confirm = useCallback((opts: ConfirmOptions) => {
    setReason("");
    return new Promise<ConfirmResult>((resolve) => setState({ ...opts, resolve }));
  }, []);
  const close = (ok: boolean) => {
    state?.resolve({ ok, reason: reason.trim() });
    setState(null);
  };
  const reasonOk = !state?.reason || reason.trim().length >= (state.reason.minLength ?? 3);
  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      <Modal open={!!state} title={state?.title ?? ""} onClose={() => close(false)}
        footer={<>
          <Button variant="secondary" onClick={() => close(false)}>Cancel</Button>
          <Button variant={state?.danger ? "danger" : "primary"} disabled={!reasonOk} onClick={() => close(true)}>
            {state?.confirmLabel ?? "Confirm"}
          </Button>
        </>}>
        <div className="space-y-3 text-sm text-slate-700">
          <div>{state?.message}</div>
          {state?.reason && (
            <Field label={state.reason.label} required>
              {(id) => <textarea id={id} className="input" rows={3} value={reason} onChange={(e) => setReason(e.target.value)} />}
            </Field>
          )}
        </div>
      </Modal>
    </ConfirmContext.Provider>
  );
}

// --- Toasts ----------------------------------------------------------------------------

interface Toast { id: number; tone: "success" | "error"; text: string }
const ToastContext = createContext<{ success: (t: string) => void; error: (e: unknown) => void }>({ success: () => {}, error: () => {} });
export const useToast = () => useContext(ToastContext);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((tone: Toast["tone"], text: string) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t.slice(-3), { id, tone, text }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), tone === "error" ? 8000 : 4000);
  }, []);
  const value = useMemo(() => ({ success: (t: string) => push("success", t), error: (e: unknown) => push("error", errorText(e)) }), [push]);
  return (
    <ToastContext.Provider value={value}>
      {children}
      {/* Above the phone bottom navigation; bottom-right on desktop. */}
      <div className="no-print fixed inset-x-3 bottom-24 z-[60] flex flex-col items-center gap-2 sm:inset-x-auto sm:right-4 sm:items-end lg:bottom-4" aria-live="polite">
        {toasts.map((t) => {
          const Icon = t.tone === "error" ? XCircle : CheckCircle2;
          return (
            <div key={t.id} role={t.tone === "error" ? "alert" : "status"}
              className="glass-strong flex w-full max-w-sm animate-toast-in items-start gap-2.5 rounded-xl px-3.5 py-3 text-sm text-slate-800">
              <Icon className={cx("mt-0.5 h-4 w-4 shrink-0", t.tone === "error" ? "text-red-500" : "text-emerald-500")} aria-hidden />
              <span className="min-w-0 flex-1">{t.text}</span>
              <button type="button" aria-label="Dismiss" className="rounded p-0.5 text-slate-400 hover:text-slate-700" onClick={() => setToasts((x) => x.filter((y) => y.id !== t.id))}>
                <X className="h-4 w-4" />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

/** Segmented control; scrolls sideways on narrow screens. */
export function Tabs({ tabs, active, onChange }: { tabs: { key: string; label: string; badge?: number }[]; active: string; onChange: (key: string) => void }) {
  return (
    <div className="no-print mb-5 -mx-4 overflow-x-auto px-4 no-scrollbar sm:mx-0 sm:px-0">
      <div role="tablist" className="glass inline-flex min-w-max gap-1 rounded-xl p-1">
        {tabs.map((t) => (
          <button key={t.key} role="tab" type="button" aria-selected={active === t.key} onClick={() => onChange(t.key)}
            className={cx("flex items-center rounded-lg px-3.5 py-1.5 text-sm font-medium whitespace-nowrap transition-colors",
              active === t.key ? "bg-white text-slate-900 shadow-sm ring-1 ring-slate-900/5" : "text-slate-600 hover:bg-white/50 hover:text-slate-900")}>
            {t.label}
            {!!t.badge && <span className="ml-1.5 rounded-full bg-amber-400/20 px-1.5 text-xs text-amber-800">{t.badge}</span>}
          </button>
        ))}
      </div>
    </div>
  );
}
