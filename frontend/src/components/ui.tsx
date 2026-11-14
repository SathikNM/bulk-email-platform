"use client";

import clsx from "clsx";
import { AlertTriangle, ChevronDown, ChevronLeft, ChevronRight, Inbox, Loader2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { titleCase } from "@/lib/format";

// ---------- Button ----------
type BtnProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger" | "accent";
  size?: "sm" | "md";
  loading?: boolean;
  icon?: React.ReactNode;
};
export function Button({ variant = "secondary", size = "md", loading, icon, className, children, disabled, ...p }: BtnProps) {
  return (
    <button
      {...p}
      disabled={disabled || loading}
      className={clsx(
        "inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" ? "px-2.5 py-1.5 text-xs" : "px-3.5 py-2 text-sm",
        {
          primary: "bg-brand-700 text-white shadow-xs hover:bg-brand-800",
          accent: "bg-accent-600 text-white shadow-xs hover:bg-accent-500",
          secondary: "border border-slate-300 bg-white text-slate-700 shadow-xs hover:bg-slate-50",
          ghost: "text-slate-600 hover:bg-slate-100",
          danger: "bg-red-600 text-white shadow-xs hover:bg-red-700",
        }[variant],
        className,
      )}
    >
      {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : icon}
      {children}
    </button>
  );
}

// ---------- Badges ----------
const TONES: Record<string, string> = {
  green: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  blue: "bg-sky-50 text-sky-700 ring-sky-600/20",
  amber: "bg-amber-50 text-amber-800 ring-amber-600/20",
  red: "bg-red-50 text-red-700 ring-red-600/20",
  gray: "bg-slate-100 text-slate-600 ring-slate-500/20",
  violet: "bg-violet-50 text-violet-700 ring-violet-600/20",
  brand: "bg-brand-50 text-brand-700 ring-brand-600/20",
};
export function Badge({ tone = "gray", children, className }: { tone?: keyof typeof TONES | string; children: React.ReactNode; className?: string }) {
  return (
    <span className={clsx("inline-flex items-center gap-1 whitespace-nowrap rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset", TONES[tone] || TONES.gray, className)}>
      {children}
    </span>
  );
}

const STATUS_TONE: Record<string, string> = {
  // campaign
  draft: "gray", scheduled: "blue", processing: "violet", sending: "violet", completed: "green", paused: "amber", failed: "red", cancelled: "gray",
  // subscription / verification
  subscribed: "green", pending: "amber", unsubscribed: "gray", bounced: "red", complained: "red",
  valid: "green", risky: "amber", invalid: "red", unverified: "gray", verified: "green",
  // recipients
  queued: "blue", sent: "brand", delivered: "green", skipped_suppressed: "gray",
  // company
  active: "green", prospect: "blue", customer: "violet", inactive: "gray",
  running: "violet",
};
export function StatusBadge({ status }: { status: string | null | undefined }) {
  if (!status) return <span className="text-slate-400">—</span>;
  const live = status === "sending" || status === "processing" || status === "running";
  return (
    <Badge tone={STATUS_TONE[status] || "gray"}>
      {live && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" />}
      {titleCase(status === "skipped_suppressed" ? "skipped" : status)}
    </Badge>
  );
}

// ---------- Layout bits ----------
export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-slate-900">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-slate-500">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Card({ title, actions, children, className, bodyClass }: { title?: React.ReactNode; actions?: React.ReactNode; children: React.ReactNode; className?: string; bodyClass?: string }) {
  return (
    <section className={clsx("card", className)}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-2 border-b border-slate-100 px-4 py-3">
          <h2 className="text-sm font-semibold text-slate-800">{title}</h2>
          {actions}
        </header>
      )}
      <div className={clsx("p-4", bodyClass)}>{children}</div>
    </section>
  );
}

export function Stat({ label, value, hint, icon, tone = "brand" }: { label: string; value: React.ReactNode; hint?: React.ReactNode; icon?: React.ReactNode; tone?: "brand" | "green" | "amber" | "red" | "violet" }) {
  const toneCls = { brand: "bg-brand-50 text-brand-700", green: "bg-emerald-50 text-emerald-700", amber: "bg-amber-50 text-amber-700", red: "bg-red-50 text-red-700", violet: "bg-violet-50 text-violet-700" }[tone];
  return (
    <div className="card flex items-start gap-3 p-4">
      {icon && <div className={clsx("rounded-lg p-2", toneCls)}>{icon}</div>}
      <div className="min-w-0">
        <div className="text-xs font-medium text-slate-500">{label}</div>
        <div className="mt-1 text-2xl font-semibold tabular-nums text-slate-900">{value}</div>
        {hint && <div className="mt-0.5 text-xs text-slate-500">{hint}</div>}
      </div>
    </div>
  );
}

// ---------- States ----------
export function Loading({ label = "Loading…", className }: { label?: string; className?: string }) {
  return (
    <div className={clsx("flex items-center justify-center gap-2 py-12 text-sm text-slate-500", className)}>
      <Loader2 className="h-4 w-4 animate-spin" /> {label}
    </div>
  );
}
export function Empty({ title, hint, action, icon }: { title: string; hint?: string; action?: React.ReactNode; icon?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      <div className="mb-3 rounded-full bg-slate-100 p-3 text-slate-400">{icon || <Inbox className="h-6 w-6" />}</div>
      <div className="text-sm font-semibold text-slate-800">{title}</div>
      {hint && <p className="mt-1 max-w-sm text-sm text-slate-500">{hint}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-12 text-center">
      <AlertTriangle className="h-6 w-6 text-red-500" />
      <div className="text-sm font-semibold text-slate-800">Something went wrong</div>
      <p className="max-w-md whitespace-pre-line text-sm text-slate-500">{error instanceof Error ? error.message : String(error)}</p>
      {retry && <Button size="sm" onClick={retry}>Try again</Button>}
    </div>
  );
}
export function Alert({ tone = "amber", title, children }: { tone?: "amber" | "red" | "blue" | "green"; title?: string; children?: React.ReactNode }) {
  const cls = { amber: "border-amber-200 bg-amber-50 text-amber-900", red: "border-red-200 bg-red-50 text-red-900", blue: "border-sky-200 bg-sky-50 text-sky-900", green: "border-emerald-200 bg-emerald-50 text-emerald-900" }[tone];
  return (
    <div className={clsx("rounded-lg border px-3 py-2.5 text-sm", cls)}>
      {title && <div className="font-semibold">{title}</div>}
      {children && <div className={clsx(title && "mt-0.5", "whitespace-pre-line")}>{children}</div>}
    </div>
  );
}

// ---------- Overlays ----------
function useEsc(open: boolean, onClose: () => void) {
  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open, onClose]);
}

export function Modal({ open, onClose, title, children, footer, wide }: { open: boolean; onClose: () => void; title: string; children: React.ReactNode; footer?: React.ReactNode; wide?: boolean }) {
  useEsc(open, onClose);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-900/40 p-4 pt-[8vh]" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div role="dialog" aria-modal className={clsx("w-full rounded-xl bg-white shadow-xl", wide ? "max-w-4xl" : "max-w-lg")}>
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-3.5">
          <h3 className="text-base font-semibold">{title}</h3>
          <button onClick={onClose} className="rounded p-1 text-slate-400 hover:bg-slate-100" aria-label="Close"><X className="h-4 w-4" /></button>
        </div>
        <div className="max-h-[70vh] overflow-y-auto px-5 py-4">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-slate-100 px-5 py-3">{footer}</div>}
      </div>
    </div>
  );
}

export function Drawer({ open, onClose, title, children, footer }: { open: boolean; onClose: () => void; title: string; children: React.ReactNode; footer?: React.ReactNode }) {
  useEsc(open, onClose);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-slate-900/30" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div role="dialog" aria-modal className="flex h-full w-full max-w-xl flex-col bg-white shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <h3 className="text-base font-semibold">{title}</h3>
          <button onClick={onClose} className="rounded p-1 text-slate-400 hover:bg-slate-100" aria-label="Close"><X className="h-4 w-4" /></button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-slate-100 px-5 py-3">{footer}</div>}
      </div>
    </div>
  );
}

export function Confirm({ open, onClose, onConfirm, title, message, confirmLabel = "Confirm", danger, loading }: { open: boolean; onClose: () => void; onConfirm: () => void; title: string; message: React.ReactNode; confirmLabel?: string; danger?: boolean; loading?: boolean }) {
  return (
    <Modal open={open} onClose={onClose} title={title} footer={<><Button onClick={onClose}>Cancel</Button><Button variant={danger ? "danger" : "primary"} onClick={onConfirm} loading={loading}>{confirmLabel}</Button></>}>
      <div className="text-sm text-slate-600">{message}</div>
    </Modal>
  );
}

// ---------- Form fields ----------
export function Field({ label, error, hint, children, className }: { label?: string; error?: string; hint?: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={className}>
      {label && <label className="label">{label}</label>}
      {children}
      {error ? <p className="mt-1 text-xs text-red-600">{error}</p> : hint ? <p className="mt-1 text-xs text-slate-500">{hint}</p> : null}
    </div>
  );
}

export function Select({ value, onChange, options, placeholder, className, disabled }: { value: string | null | undefined; onChange: (v: string) => void; options: { value: string; label: string }[]; placeholder?: string; className?: string; disabled?: boolean }) {
  return (
    <select className={clsx("input pe-8", className)} value={value ?? ""} onChange={(e) => onChange(e.target.value)} disabled={disabled}>
      {placeholder !== undefined && <option value="">{placeholder}</option>}
      {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  );
}

export function MultiSelect({ label, options, value, onChange, className }: { label: string; options: { value: string; label: string }[]; value: string[]; onChange: (v: string[]) => void; className?: string }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const h = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);
  const shown = options.filter((o) => o.label.toLowerCase().includes(q.toLowerCase()));
  return (
    <div className={clsx("relative", className)} ref={ref}>
      <button type="button" onClick={() => setOpen(!open)} className={clsx("inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-sm shadow-xs", value.length ? "border-brand-300 bg-brand-50 text-brand-800" : "border-slate-300 bg-white text-slate-700 hover:bg-slate-50")}>
        {label}{value.length > 0 && <span className="rounded bg-brand-700 px-1.5 text-xs text-white">{value.length}</span>}
        <ChevronDown className="h-3.5 w-3.5 opacity-60" />
      </button>
      {open && (
        <div className="absolute z-30 mt-1 w-64 rounded-lg border border-slate-200 bg-white p-2 shadow-lg">
          {options.length > 8 && <input className="input mb-2 py-1.5" placeholder="Search…" value={q} onChange={(e) => setQ(e.target.value)} autoFocus />}
          <div className="max-h-60 overflow-y-auto">
            {shown.length === 0 && <div className="px-2 py-3 text-center text-xs text-slate-500">No options</div>}
            {shown.map((o) => (
              <label key={o.value} className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-slate-50">
                <input type="checkbox" className="rounded border-slate-300" checked={value.includes(o.value)} onChange={(e) => onChange(e.target.checked ? [...value, o.value] : value.filter((v) => v !== o.value))} />
                <span className="truncate">{o.label}</span>
              </label>
            ))}
          </div>
          {value.length > 0 && <button className="mt-1 w-full rounded px-2 py-1 text-start text-xs text-slate-500 hover:bg-slate-50" onClick={() => onChange([])}>Clear selection</button>}
        </div>
      )}
    </div>
  );
}

export function Tabs({ tabs, value, onChange }: { tabs: { value: string; label: React.ReactNode }[]; value: string; onChange: (v: string) => void }) {
  return (
    <div className="mb-4 flex gap-1 border-b border-slate-200">
      {tabs.map((t) => (
        <button key={t.value} onClick={() => onChange(t.value)} className={clsx("-mb-px border-b-2 px-3 py-2 text-sm font-medium transition-colors", value === t.value ? "border-brand-700 text-brand-800" : "border-transparent text-slate-500 hover:text-slate-800")}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function Pagination({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  return (
    <div className="flex items-center justify-between px-3 py-2.5 text-sm text-slate-500">
      <span>{from.toLocaleString()}–{Math.min(page * pageSize, total).toLocaleString()} of {total.toLocaleString()}</span>
      <div className="flex items-center gap-1">
        <Button size="sm" variant="ghost" disabled={page <= 1} onClick={() => onPage(page - 1)} aria-label="Previous"><ChevronLeft className="h-4 w-4" /></Button>
        <span className="px-2 tabular-nums">{page} / {pages}</span>
        <Button size="sm" variant="ghost" disabled={page >= pages} onClick={() => onPage(page + 1)} aria-label="Next"><ChevronRight className="h-4 w-4" /></Button>
      </div>
    </div>
  );
}

export function SearchInput({ value, onChange, placeholder = "Search…", className }: { value: string; onChange: (v: string) => void; placeholder?: string; className?: string }) {
  const [v, setV] = useState(value);
  useEffect(() => setV(value), [value]);
  useEffect(() => {
    const t = setTimeout(() => v !== value && onChange(v), 300);
    return () => clearTimeout(t);
  }, [v]);
  return <input className={clsx("input w-64", className)} placeholder={placeholder} value={v} onChange={(e) => setV(e.target.value)} type="search" />;
}

export function Progress({ value, tone = "brand" }: { value: number; tone?: "brand" | "green" }) {
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100">
      <div className={clsx("h-full rounded-full transition-all", tone === "green" ? "bg-emerald-500" : "bg-brand-600")} style={{ width: `${Math.min(100, Math.max(0, value))}%` }} />
    </div>
  );
}

export function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label?: string }) {
  return (
    <label className="inline-flex cursor-pointer items-center gap-2 text-sm text-slate-700">
      <span className={clsx("relative h-5 w-9 rounded-full transition-colors", checked ? "bg-brand-700" : "bg-slate-300")} onClick={() => onChange(!checked)}>
        <span className={clsx("absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all", checked ? "start-[18px]" : "start-0.5")} />
      </span>
      {label}
    </label>
  );
}
