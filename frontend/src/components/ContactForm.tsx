"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { COUNTRIES } from "@/lib/format";
import { toOptions, useAction, useCategories, useTags } from "@/lib/hooks";
import type { Company, Contact, Page } from "@/lib/types";
import { Alert, Button, Drawer, Field, MultiSelect, Select } from "./ui";

type Form = {
  company_id: string; email: string; first_name: string; last_name: string; name_ar: string; job_title: string; department: string;
  phone: string; country_code: string; city: string; category_id: string; notes: string; tag_ids: string[];
  consent_source: string; consent_date: string; lawful_basis: string;
};

export function CompanyPicker({ value, onChange, initialLabel }: { value: string; onChange: (id: string, name: string) => void; initialLabel?: string }) {
  const [q, setQ] = useState(initialLabel || "");
  const [opts, setOpts] = useState<Company[]>([]);
  const [open, setOpen] = useState(false);
  useEffect(() => setQ(initialLabel || ""), [initialLabel]);
  useEffect(() => {
    if (!open) return;
    const t = setTimeout(async () => setOpts((await api.get<Page<Company>>("/companies", { q, page_size: 10, sort: "name" })).items), 250);
    return () => clearTimeout(t);
  }, [q, open]);
  return (
    <div className="relative">
      <input className="input" value={q} placeholder="Search companies…" onFocus={() => setOpen(true)} onBlur={() => setTimeout(() => setOpen(false), 150)} onChange={(e) => { setQ(e.target.value); if (value) onChange("", ""); }} />
      {open && opts.length > 0 && (
        <div className="absolute z-30 mt-1 max-h-60 w-full overflow-y-auto rounded-lg border border-slate-200 bg-white py-1 shadow-lg">
          {opts.map((c) => <button type="button" key={c.id} className="block w-full px-3 py-2 text-start text-sm hover:bg-slate-50" onMouseDown={() => { onChange(c.id, c.name); setQ(c.name); setOpen(false); }}>{c.name}<span className="ms-2 text-xs text-slate-400">{c.city}</span></button>)}
        </div>
      )}
    </div>
  );
}

export function ContactForm({ open, onClose, contact, defaultCompany, onSaved }: { open: boolean; onClose: () => void; contact?: Contact | null; defaultCompany?: { id: string; name: string }; onSaved?: (c: Contact) => void }) {
  const tags = useTags();
  const cats = useCategories("contact");
  const blank: Form = { company_id: defaultCompany?.id || "", email: "", first_name: "", last_name: "", name_ar: "", job_title: "", department: "", phone: "", country_code: "", city: "", category_id: "", notes: "", tag_ids: [], consent_source: "", consent_date: "", lawful_basis: "explicit_consent" };
  const [f, setF] = useState<Form>(blank);
  const [companyName, setCompanyName] = useState(defaultCompany?.name || "");
  const [emailCheck, setEmailCheck] = useState<{ exists: boolean; suppressed: string | null; role_account: boolean } | null>(null);

  useEffect(() => {
    if (!open) return;
    if (contact) {
      setF({ ...blank, ...Object.fromEntries(Object.entries(contact).map(([k, v]) => [k, v ?? ""])), tag_ids: contact.tags.map((t) => t.id) } as Form);
      setCompanyName(contact.company_name || "");
    } else { setF(blank); setCompanyName(defaultCompany?.name || ""); }
    setEmailCheck(null);
  }, [open, contact?.id]);

  useEffect(() => {
    if (!open || contact || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(f.email)) return setEmailCheck(null);
    const t = setTimeout(async () => setEmailCheck(await api.get("/contacts/check-email", { email: f.email })), 350);
    return () => clearTimeout(t);
  }, [f.email, open]);

  const save = useAction(() => {
    const nul = (v: string) => v || null;
    const base = { company_id: f.company_id, email: f.email, first_name: nul(f.first_name), last_name: nul(f.last_name), name_ar: nul(f.name_ar), job_title: nul(f.job_title), department: nul(f.department), phone: nul(f.phone), country_code: nul(f.country_code), city: nul(f.city), category_id: nul(f.category_id), notes: nul(f.notes), tag_ids: f.tag_ids };
    return contact
      ? api.patch<Contact>(`/contacts/${contact.id}`, base)
      : api.post<Contact>("/contacts", { ...base, consent_source: nul(f.consent_source), consent_date: f.consent_date ? new Date(f.consent_date).toISOString() : null, lawful_basis: f.lawful_basis });
  }, { success: contact ? "Contact updated" : "Contact created", invalidate: [["contacts"], ["contact"], ["company"], ["companies"]], onSuccess: (c) => { onSaved?.(c); onClose(); } });

  const set = (k: keyof Form) => (v: string | string[]) => setF({ ...f, [k]: v });
  const inp = (k: keyof Form, props: React.InputHTMLAttributes<HTMLInputElement> = {}) => <input className="input" value={f[k] as string} onChange={(e) => set(k)(e.target.value)} {...props} />;

  return (
    <Drawer open={open} onClose={onClose} title={contact ? "Edit contact" : "Add contact"} footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={save.isPending} disabled={!f.company_id || !f.email || emailCheck?.exists} onClick={() => save.mutate(undefined)}>Save</Button></>}>
      <div className="grid grid-cols-2 gap-4">
        <Field label="Company *" className="col-span-2"><CompanyPicker value={f.company_id} initialLabel={companyName} onChange={(id) => set("company_id")(id)} /></Field>
        <Field label="First name">{inp("first_name")}</Field>
        <Field label="Last name">{inp("last_name")}</Field>
        <Field label="Full name (Arabic)" className="col-span-2">{inp("name_ar", { dir: "rtl", placeholder: "الاسم بالعربي" })}</Field>
        <Field label="Business email *" className="col-span-2">{inp("email", { type: "email" })}</Field>
        {emailCheck?.exists && <div className="col-span-2"><Alert tone="red">A contact with this email already exists.</Alert></div>}
        {emailCheck?.suppressed && <div className="col-span-2"><Alert tone="amber">This address is on the suppression list ({emailCheck.suppressed}). It will be saved as unsubscribed.</Alert></div>}
        {emailCheck?.role_account && !emailCheck.exists && <div className="col-span-2"><Alert tone="blue">Role address (info@, sales@…). These usually reach a shared inbox.</Alert></div>}
        <Field label="Job title">{inp("job_title")}</Field>
        <Field label="Department">{inp("department")}</Field>
        <Field label="Phone">{inp("phone", { type: "tel" })}</Field>
        <Field label="Contact category"><Select value={f.category_id} onChange={set("category_id")} options={toOptions(cats.data)} placeholder="—" /></Field>
        <Field label="Country"><Select value={f.country_code} onChange={set("country_code")} options={COUNTRIES.map(([v, l]) => ({ value: v, label: l }))} placeholder="Same as company" /></Field>
        <Field label="City">{inp("city", { placeholder: "Same as company" })}</Field>
        <Field label="Tags" className="col-span-2"><MultiSelect label="Select tags" options={toOptions(tags.data)} value={f.tag_ids} onChange={set("tag_ids")} /></Field>
        {!contact && (
          <fieldset className="col-span-2 rounded-lg border border-slate-200 p-3">
            <legend className="px-1 text-xs font-semibold text-slate-600">Marketing consent</legend>
            <p className="mb-3 text-xs text-slate-500">Leave empty if this person has not agreed to receive marketing. They will stay <b>pending</b> and will not be emailed.</p>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Consent source">{inp("consent_source", { placeholder: "e.g. Website form, event badge scan" })}</Field>
              <Field label="Consent date">{inp("consent_date", { type: "date" })}</Field>
              <Field label="Lawful basis" className="col-span-2"><Select value={f.lawful_basis} onChange={set("lawful_basis")} options={[{ value: "explicit_consent", label: "Explicit consent" }, { value: "legitimate_interest", label: "Legitimate interest" }, { value: "existing_customer", label: "Existing customer" }, { value: "contract", label: "Contract" }]} /></Field>
            </div>
          </fieldset>
        )}
        <Field label="Notes" className="col-span-2"><textarea className="input min-h-20" value={f.notes} onChange={(e) => set("notes")(e.target.value)} /></Field>
      </div>
    </Drawer>
  );
}
