"use client";

import clsx from "clsx";
import { ArrowDownAZ, ArrowUpAZ, Filter, Search } from "lucide-react";
import { useEffect, useRef, useState } from "react";

type Opt = { value: string; label: string };

/** Excel-style column header: label + funnel that opens sort and filter options. */
export function ColumnFilter({
  label, sortKey, sort, onSort, text, onText, options, selected, onSelect, presence, onPresence, presenceLabels, className,
}: {
  label: string;
  sortKey?: string;
  sort?: string;
  onSort?: (s: string) => void;
  text?: string;
  onText?: (v: string) => void;
  options?: Opt[];
  selected?: string[];
  onSelect?: (v: string[]) => void;
  presence?: boolean | null;
  onPresence?: (v: boolean | null) => void;
  presenceLabels?: [string, string];
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(text || "");
  const [find, setFind] = useState("");
  const ref = useRef<HTMLTableCellElement>(null);
  useEffect(() => setDraft(text || ""), [text]);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [open]);

  const active = !!text || (selected && selected.length > 0) || (presence !== undefined && presence !== null);
  const sorted = sortKey && sort ? (sort === sortKey ? "asc" : sort === `-${sortKey}` ? "desc" : null) : null;
  const shown = (options || []).filter((o) => o.label.toLowerCase().includes(find.toLowerCase()));
  const apply = () => { onText?.(draft.trim()); setOpen(false); };
  const clear = () => { onText?.(""); onSelect?.([]); onPresence?.(null); setDraft(""); setOpen(false); };

  return (
    <th ref={ref} className={clsx("th relative", className)}>
      <div className="flex items-center gap-1">
        <button type="button" className="hover:text-slate-900" onClick={() => sortKey && onSort?.(sorted === "asc" ? `-${sortKey}` : sortKey)}>
          {label}{sorted === "asc" ? " ↑" : sorted === "desc" ? " ↓" : ""}
        </button>
        <button type="button" aria-label={`Filter ${label}`} onClick={() => setOpen(!open)}
          className={clsx("rounded p-0.5 hover:bg-slate-200", active ? "bg-brand-100 text-brand-700" : "text-slate-400")}>
          <Filter className="h-3.5 w-3.5" fill={active ? "currentColor" : "none"} />
        </button>
      </div>
      {open && (
        <div className="absolute start-0 top-full z-30 mt-1 w-64 rounded-lg border border-slate-200 bg-white p-3 text-start text-sm font-normal normal-case tracking-normal text-slate-700 shadow-lg">
          {sortKey && onSort && (
            <div className="mb-2 space-y-0.5 border-b border-slate-100 pb-2">
              <button type="button" className={clsx("flex w-full items-center gap-2 rounded px-2 py-1 hover:bg-slate-50", sorted === "asc" && "font-medium text-brand-700")} onClick={() => { onSort(sortKey); setOpen(false); }}><ArrowDownAZ className="h-4 w-4" />Sort A → Z</button>
              <button type="button" className={clsx("flex w-full items-center gap-2 rounded px-2 py-1 hover:bg-slate-50", sorted === "desc" && "font-medium text-brand-700")} onClick={() => { onSort(`-${sortKey}`); setOpen(false); }}><ArrowUpAZ className="h-4 w-4" />Sort Z → A</button>
            </div>
          )}
          {onPresence && (
            <div className="mb-2 space-y-1 border-b border-slate-100 pb-2">
              {([[null, "All"], [true, presenceLabels?.[0] ?? "Has a value"], [false, presenceLabels?.[1] ?? "Empty"]] as const).map(([v, l]) => (
                <label key={String(v)} className="flex cursor-pointer items-center gap-2 px-2"><input type="radio" checked={presence === v || (v === null && presence == null)} onChange={() => { onPresence(v); setOpen(false); }} />{l}</label>
              ))}
            </div>
          )}
          {onText && (
            <form onSubmit={(e) => { e.preventDefault(); apply(); }} className="space-y-2">
              <div className="text-xs font-medium text-slate-500">Contains</div>
              <input autoFocus className="input py-1.5" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder={`Filter ${label.toLowerCase()}…`} />
            </form>
          )}
          {options && onSelect && (
            <div className="space-y-2">
              {options.length > 8 && (
                <div className="relative"><Search className="pointer-events-none absolute start-2 top-2 h-3.5 w-3.5 text-slate-400" /><input className="input py-1.5 ps-7" value={find} onChange={(e) => setFind(e.target.value)} placeholder="Search…" /></div>
              )}
              <label className="flex cursor-pointer items-center gap-2 px-1 font-medium"><input type="checkbox" checked={(selected || []).length === 0} onChange={() => onSelect([])} />(Select all)</label>
              <div className="max-h-56 space-y-1 overflow-y-auto px-1">
                {shown.map((o) => (
                  <label key={o.value} className="flex cursor-pointer items-center gap-2">
                    <input type="checkbox" checked={(selected || []).includes(o.value)}
                      onChange={(e) => onSelect(e.target.checked ? [...(selected || []), o.value] : (selected || []).filter((x) => x !== o.value))} />
                    <span className="truncate">{o.label}</span>
                  </label>
                ))}
                {shown.length === 0 && <div className="text-xs text-slate-400">No values</div>}
              </div>
            </div>
          )}
          <div className="mt-3 flex justify-between gap-2">
            <button type="button" className="text-xs text-slate-500 hover:underline" onClick={clear}>Clear filter</button>
            {onText ? <button type="button" className="rounded bg-brand-700 px-3 py-1 text-xs font-medium text-white hover:bg-brand-800" onClick={apply}>Apply</button>
              : <button type="button" className="rounded border border-slate-200 px-3 py-1 text-xs hover:bg-slate-50" onClick={() => setOpen(false)}>Done</button>}
          </div>
        </div>
      )}
    </th>
  );
}
