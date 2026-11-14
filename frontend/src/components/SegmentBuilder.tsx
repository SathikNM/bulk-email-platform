"use client";

import clsx from "clsx";
import { Plus, Trash2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fmtNum } from "@/lib/format";
import { useWsQuery } from "@/lib/hooks";
import type { Company, FieldDef, Page, Rule, RuleGroup, SegmentCounts } from "@/lib/types";
import { Button } from "./ui";

const OP_LABEL: Record<string, string> = {
  eq: "is", neq: "is not", in: "is any of", not_in: "is none of", contains: "contains", not_contains: "does not contain",
  starts_with: "starts with", is_empty: "is empty", is_not_empty: "is not empty", before: "is before", after: "is on/after",
};
const NO_VALUE = new Set(["is_empty", "is_not_empty"]);
const MULTI = new Set(["in", "not_in"]);
const isGroup = (r: Rule | RuleGroup): r is RuleGroup => "rules" in r;

export function useFields() {
  return useWsQuery(["segment-fields"], () => api.get<FieldDef[]>("/segments/fields"));
}

export function SegmentBuilder({ value, onChange }: { value: RuleGroup; onChange: (g: RuleGroup) => void }) {
  const fields = useFields();
  if (!fields.data) return <div className="py-6 text-sm text-slate-500">Loading fields…</div>;
  return <GroupEditor group={value} onChange={onChange} fields={fields.data} depth={0} />;
}

function GroupEditor({ group, onChange, onRemove, fields, depth }: { group: RuleGroup; onChange: (g: RuleGroup) => void; onRemove?: () => void; fields: FieldDef[]; depth: number }) {
  const update = (i: number, r: Rule | RuleGroup) => onChange({ ...group, rules: group.rules.map((x, j) => (j === i ? r : x)) });
  const remove = (i: number) => onChange({ ...group, rules: group.rules.filter((_, j) => j !== i) });
  return (
    <div className={clsx("rounded-xl border p-3", depth === 0 ? "border-slate-200 bg-white" : "border-dashed border-brand-200 bg-brand-50/40")}>
      <div className="mb-2 flex items-center gap-2">
        <span className="text-xs font-medium text-slate-500">Match</span>
        <div className="inline-flex overflow-hidden rounded-lg border border-slate-300 text-xs font-semibold">
          {(["and", "or"] as const).map((op) => <button key={op} type="button" onClick={() => onChange({ ...group, op })} className={clsx("px-3 py-1", group.op === op ? "bg-brand-700 text-white" : "bg-white text-slate-600 hover:bg-slate-50")}>{op === "and" ? "ALL" : "ANY"}</button>)}
        </div>
        <span className="text-xs text-slate-500">of these conditions</span>
        {onRemove && <button type="button" onClick={onRemove} className="ms-auto rounded p-1 text-slate-400 hover:bg-white hover:text-red-600" aria-label="Remove group"><X className="h-4 w-4" /></button>}
      </div>
      <div className="space-y-2">
        {group.rules.length === 0 && <div className="rounded-lg border border-dashed border-slate-300 px-3 py-4 text-center text-xs text-slate-500">No conditions: everyone in the workspace matches.</div>}
        {group.rules.map((r, i) => (
          <div key={i}>
            {i > 0 && <div className="my-1 ps-3 text-[11px] font-bold uppercase tracking-wider text-brand-600">{group.op === "and" ? "and" : "or"}</div>}
            {isGroup(r) ? <GroupEditor group={r} onChange={(g) => update(i, g)} onRemove={() => remove(i)} fields={fields} depth={depth + 1} />
              : <RuleRow rule={r} onChange={(x) => update(i, x)} onRemove={() => remove(i)} fields={fields} />}
          </div>
        ))}
      </div>
      <div className="mt-3 flex gap-2">
        <Button size="sm" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => onChange({ ...group, rules: [...group.rules, { field: "job_title", operator: "contains", value: "" }] })}>Condition</Button>
        {depth < 3 && <Button size="sm" variant="ghost" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => onChange({ ...group, rules: [...group.rules, { op: group.op === "and" ? "or" : "and", rules: [{ field: "job_title", operator: "contains", value: "" }] }] })}>Group</Button>}
      </div>
    </div>
  );
}

function RuleRow({ rule, onChange, onRemove, fields }: { rule: Rule; onChange: (r: Rule) => void; onRemove: () => void; fields: FieldDef[] }) {
  const def = fields.find((f) => f.field === rule.field) || fields[0];
  const setField = (field: string) => {
    const d = fields.find((f) => f.field === field)!;
    const op = d.operators.includes("in") ? "in" : d.operators.includes("eq") ? "eq" : d.operators[0];
    onChange({ field, operator: op, value: MULTI.has(op) ? [] : "" });
  };
  const setOp = (operator: string) => {
    let value = rule.value;
    if (MULTI.has(operator) && !Array.isArray(value)) value = value ? [value] : [];
    if (!MULTI.has(operator) && Array.isArray(value)) value = value[0] ?? "";
    onChange({ ...rule, operator, value: NO_VALUE.has(operator) ? undefined : value });
  };
  return (
    <div className="flex flex-wrap items-start gap-2 rounded-lg bg-slate-50 p-2">
      <select className="input w-48 py-1.5" value={rule.field} onChange={(e) => setField(e.target.value)} aria-label="Field">
        {fields.map((f) => <option key={f.field} value={f.field}>{f.label}</option>)}
      </select>
      <select className="input w-40 py-1.5" value={rule.operator} onChange={(e) => setOp(e.target.value)} aria-label="Operator">
        {def.operators.sort((a, b) => Object.keys(OP_LABEL).indexOf(a) - Object.keys(OP_LABEL).indexOf(b)).map((o) => <option key={o} value={o}>{OP_LABEL[o] || o}</option>)}
      </select>
      {!NO_VALUE.has(rule.operator) && <div className="min-w-[220px] flex-1"><ValueInput def={def} rule={rule} onChange={(value) => onChange({ ...rule, value })} /></div>}
      <button type="button" onClick={onRemove} className="rounded p-1.5 text-slate-400 hover:bg-white hover:text-red-600" aria-label="Remove condition"><Trash2 className="h-4 w-4" /></button>
    </div>
  );
}

function ValueInput({ def, rule, onChange }: { def: FieldDef; rule: Rule; onChange: (v: unknown) => void }) {
  const multi = MULTI.has(rule.operator);
  if (def.kind === "date") return <input type="date" className="input py-1.5" value={String(rule.value || "")} onChange={(e) => onChange(e.target.value)} />;
  if (def.async_options) return <CompanyValues value={(Array.isArray(rule.value) ? rule.value : rule.value ? [rule.value] : []) as string[]} onChange={(v) => onChange(multi ? v : v[0] || "")} />;
  const opts = def.options;
  if (opts && (def.kind !== "text" || multi)) {
    if (multi || def.kind === "ref_m2m") {
      const vals = (Array.isArray(rule.value) ? rule.value : rule.value ? [rule.value] : []) as string[];
      return <ChipSelect options={opts} value={vals} onChange={onChange} allowFree={def.kind === "text"} />;
    }
    return (
      <select className="input py-1.5" value={String(rule.value || "")} onChange={(e) => onChange(e.target.value)}>
        <option value="">Select…</option>
        {opts.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    );
  }
  if (multi) return <ChipSelect options={opts || []} value={(rule.value as string[]) || []} onChange={onChange} allowFree />;
  return (
    <>
      <input className="input py-1.5" list={`dl-${def.field}`} value={String(rule.value ?? "")} onChange={(e) => onChange(e.target.value)} placeholder="Value" />
      {opts && <datalist id={`dl-${def.field}`}>{opts.map((o) => <option key={o.value} value={o.value} />)}</datalist>}
    </>
  );
}

function ChipSelect({ options, value, onChange, allowFree }: { options: { value: string; label: string }[]; value: string[]; onChange: (v: string[]) => void; allowFree?: boolean }) {
  const [q, setQ] = useState("");
  const label = (v: string) => options.find((o) => o.value === v)?.label || v;
  const add = (v: string) => { if (v && !value.includes(v)) onChange([...value, v]); setQ(""); };
  const shown = options.filter((o) => !value.includes(o.value) && o.label.toLowerCase().includes(q.toLowerCase())).slice(0, 8);
  return (
    <div className="relative">
      <div className="flex min-h-[38px] flex-wrap items-center gap-1 rounded-lg border border-slate-300 bg-white px-2 py-1">
        {value.map((v) => <span key={v} className="inline-flex items-center gap-1 rounded bg-brand-100 px-1.5 py-0.5 text-xs text-brand-800">{label(v)}<button type="button" onClick={() => onChange(value.filter((x) => x !== v))} aria-label="Remove"><X className="h-3 w-3" /></button></span>)}
        <input className="min-w-[80px] flex-1 border-0 bg-transparent p-1 text-sm focus:outline-none" value={q} placeholder={value.length ? "" : "Type or choose…"} onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && allowFree && q.trim()) { e.preventDefault(); add(q.trim()); } }} />
      </div>
      {q && shown.length > 0 && (
        <div className="absolute z-20 mt-1 max-h-48 w-full overflow-y-auto rounded-lg border border-slate-200 bg-white py-1 shadow-lg">
          {shown.map((o) => <button type="button" key={o.value} className="block w-full px-3 py-1.5 text-start text-sm hover:bg-slate-50" onMouseDown={() => add(o.value)}>{o.label}</button>)}
        </div>
      )}
      {!q && options.length > 0 && options.length <= 12 && (
        <div className="mt-1 flex flex-wrap gap-1">{options.filter((o) => !value.includes(o.value)).map((o) => <button type="button" key={o.value} onClick={() => add(o.value)} className="rounded border border-slate-200 bg-white px-1.5 py-0.5 text-xs text-slate-600 hover:border-brand-300">+ {o.label}</button>)}</div>
      )}
    </div>
  );
}

function CompanyValues({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  const [opts, setOpts] = useState<{ value: string; label: string }[]>([]);
  const [q, setQ] = useState("");
  const [names, setNames] = useState<Record<string, string>>({});
  useEffect(() => {
    const t = setTimeout(async () => {
      const r = await api.get<Page<Company>>("/companies", { q, page_size: 10, sort: "name" });
      setOpts(r.items.map((c) => ({ value: c.id, label: c.name })));
      setNames((n) => ({ ...n, ...Object.fromEntries(r.items.map((c) => [c.id, c.name])) }));
    }, 250);
    return () => clearTimeout(t);
  }, [q]);
  return (
    <div>
      <ChipSelect options={[...opts, ...value.filter((v) => !opts.some((o) => o.value === v)).map((v) => ({ value: v, label: names[v] || "Selected company" }))]} value={value} onChange={onChange} />
      <input className="input mt-1 py-1 text-xs" placeholder="Search companies…" value={q} onChange={(e) => setQ(e.target.value)} />
    </div>
  );
}

export function useLiveCount(rules: RuleGroup) {
  const [counts, setCounts] = useState<SegmentCounts | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const key = JSON.stringify(rules);
  useEffect(() => {
    setLoading(true);
    const t = setTimeout(async () => {
      try { setCounts(await api.post<SegmentCounts>("/segments/count", { rules })); setError(null); }
      catch (e) { setError(e instanceof Error ? e.message : String(e)); }
      finally { setLoading(false); }
    }, 400);
    return () => clearTimeout(t);
  }, [key]);
  return { counts, error, loading };
}

export function CountPanel({ counts, error, loading }: { counts: SegmentCounts | null; error: string | null; loading: boolean }) {
  const ex = counts?.excluded || {};
  return (
    <div className="card p-4">
      <div className="text-xs font-medium text-slate-500">Eligible recipients</div>
      <div className={clsx("mt-1 text-4xl font-semibold tabular-nums text-emerald-700 transition-opacity", loading && "opacity-40")}>{counts ? fmtNum(counts.eligible) : "—"}</div>
      <div className="mt-1 text-sm text-slate-500">of {counts ? fmtNum(counts.total) : "—"} matching contacts</div>
      {error && <div className="mt-3 rounded-lg bg-red-50 p-2 text-xs text-red-700">{error}</div>}
      {counts && counts.total > counts.eligible && (
        <div className="mt-4 space-y-1.5 border-t border-slate-100 pt-3 text-xs">
          <div className="font-semibold text-slate-600">Excluded (a contact may have several reasons)</div>
          {[["Not subscribed / pending", ex.not_subscribed], ["On suppression list", ex.suppressed], ["Invalid email", ex.invalid_email], ["No active consent", ex.no_active_consent]].map(([l, v]) =>
            Number(v) > 0 && <div key={l as string} className="flex justify-between text-slate-600"><span>{l}</span><span className="tabular-nums">{fmtNum(Number(v))}</span></div>)}
        </div>
      )}
    </div>
  );
}
