"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { COMPANY_SIZES, COMPANY_STATUSES, COUNTRIES, titleCase } from "@/lib/format";
import { toOptions, useAction, useCategories, useIndustries, useTags } from "@/lib/hooks";
import type { Company } from "@/lib/types";
import { Alert, Button, Drawer, Field, MultiSelect, Select } from "./ui";

type Form = Partial<Record<keyof Company, unknown>> & { tag_ids: string[]; category_ids: string[] };

export function CompanyForm({ open, onClose, company, onSaved }: { open: boolean; onClose: () => void; company?: Company | null; onSaved?: (c: Company) => void }) {
  const industries = useIndustries();
  const tags = useTags();
  const cats = useCategories("company");
  const empty: Form = { name: "", status: "active", tag_ids: [], category_ids: [] };
  const [f, setF] = useState<Form>(empty);
  const [dups, setDups] = useState<{ id: string; name: string; score: number; same_domain: boolean }[]>([]);

  useEffect(() => {
    if (!open) return;
    setF(company ? { ...company, tag_ids: company.tags.map((t) => t.id), category_ids: company.categories.map((c) => c.id) } : empty);
    setDups([]);
  }, [open, company?.id]);

  useEffect(() => {
    if (!open || String(f.name || "").length < 3) return setDups([]);
    const t = setTimeout(async () => {
      try {
        setDups(await api.get("/companies/check-duplicate", { name: String(f.name), website: (f.website as string) || undefined, exclude_id: company?.id }));
      } catch { /* advisory only */ }
    }, 400);
    return () => clearTimeout(t);
  }, [f.name, f.website, open]);

  const save = useAction(
    () => {
      const body = {
        name: f.name, name_ar: f.name_ar || null, industry_id: f.industry_id || null, business_type: f.business_type || null, country_code: f.country_code || null,
        city: f.city || null, website: f.website || null, company_size: f.company_size || null, annual_revenue: f.annual_revenue || null,
        status: f.status, data_source: f.data_source || null, notes: f.notes || null, tag_ids: f.tag_ids, category_ids: f.category_ids,
      };
      return company ? api.patch<Company>(`/companies/${company.id}`, body) : api.post<Company>("/companies", body);
    },
    { success: company ? "Company updated" : "Company created", invalidate: [["companies"], ["company"]], onSuccess: (c) => { onSaved?.(c); onClose(); } },
  );

  const set = (k: string) => (v: unknown) => setF({ ...f, [k]: v });
  const inp = (k: keyof Company, props: React.InputHTMLAttributes<HTMLInputElement> = {}) => (
    <input className="input" value={(f[k] as string) ?? ""} onChange={(e) => set(k)(e.target.value)} {...props} />
  );

  return (
    <Drawer open={open} onClose={onClose} title={company ? `Edit ${company.name}` : "Add company"} footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={save.isPending} onClick={() => save.mutate(undefined)} disabled={!String(f.name || "").trim()}>Save</Button></>}>
      <div className="grid grid-cols-2 gap-4">
        <Field label="Company name *" className="col-span-2">{inp("name", { autoFocus: true })}</Field>
        <Field label="Company name (Arabic)" className="col-span-2">{inp("name_ar", { dir: "rtl", placeholder: "اسم الشركة بالعربي" })}</Field>
        {dups.length > 0 && (
          <div className="col-span-2"><Alert tone="amber" title="Possible duplicate">{dups.map((d) => `${d.name}${d.same_domain ? " (same website)" : ` (${Math.round(d.score * 100)}% similar)`}`).join("\n")}</Alert></div>
        )}
        <Field label="Industry"><Select value={f.industry_id as string} onChange={set("industry_id")} options={toOptions(industries.data)} placeholder="—" /></Field>
        <Field label="Business type">{inp("business_type", { placeholder: "e.g. Contractor, Distributor" })}</Field>
        <Field label="Country"><Select value={f.country_code as string} onChange={set("country_code")} options={COUNTRIES.map(([v, l]) => ({ value: v, label: l }))} placeholder="—" /></Field>
        <Field label="City">{inp("city")}</Field>
        <Field label="Website" className="col-span-2">{inp("website", { placeholder: "https://example.com" })}</Field>
        <Field label="Company size"><Select value={f.company_size as string} onChange={set("company_size")} options={COMPANY_SIZES.map((s) => ({ value: s, label: `${s} employees` }))} placeholder="—" /></Field>
        <Field label="Annual revenue (optional)">{inp("annual_revenue", { type: "number", min: 0, step: "any" })}</Field>
        <Field label="Status"><Select value={f.status as string} onChange={set("status")} options={COMPANY_STATUSES.map((s) => ({ value: s, label: titleCase(s) }))} /></Field>
        <Field label="Data source">{inp("data_source", { placeholder: "e.g. Trade show, Referral" })}</Field>
        <Field label="Categories"><MultiSelect label="Select categories" options={toOptions(cats.data)} value={f.category_ids} onChange={set("category_ids")} /></Field>
        <Field label="Tags"><MultiSelect label="Select tags" options={toOptions(tags.data)} value={f.tag_ids} onChange={set("tag_ids")} /></Field>
        <Field label="Notes" className="col-span-2"><textarea className="input min-h-24" value={(f.notes as string) ?? ""} onChange={(e) => set("notes")(e.target.value)} /></Field>
      </div>
    </Drawer>
  );
}
