"use client";

import { BadgeCheck, Download, Plus, Tag, Trash2, Upload, UserX } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { ContactForm } from "@/components/ContactForm";
import { ImportWizard } from "@/components/ImportWizard";
import { Badge, Button, Confirm, Empty, ErrorState, Loading, Modal, MultiSelect, PageHeader, Pagination, SearchInput, Select, StatusBadge } from "@/components/ui";
import { api, download } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { SUB_STATUSES, VERIFY_STATUSES, fullName, titleCase } from "@/lib/format";
import { toOptions, useAction, useCategories, useIndustries, useTags, useWsQuery } from "@/lib/hooks";
import type { Contact, Page } from "@/lib/types";

export default function ContactsPage() {
  const { can } = useAuth();
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState("-created_at");
  const [flt, setFlt] = useState<Record<string, string[]>>({ department: [], job_title: [], subscription_status: [], verification: [], category_id: [], tag_id: [], industry_id: [] });
  const [sel, setSel] = useState<string[]>([]);
  const [edit, setEdit] = useState<Contact | null | undefined>(undefined);
  const [imp, setImp] = useState(false);
  const [bulk, setBulk] = useState<"tag" | "unsubscribe" | "delete" | null>(null);
  const facets = useWsQuery(["contacts", "facets"], () => api.get<{ departments: string[]; job_titles: string[] }>("/contacts/facets"));
  const tags = useTags();
  const cats = useCategories("contact");
  const inds = useIndustries();
  const query = { q, page, page_size: 25, sort, ...flt };
  const list = useWsQuery(["contacts", query], () => api.get<Page<Contact>>("/contacts", query));
  const setFilter = (k: string) => (v: string[]) => { setFlt({ ...flt, [k]: v }); setPage(1); };
  const items = list.data?.items || [];
  const allSel = items.length > 0 && items.every((c) => sel.includes(c.id));
  const verify = useAction((ids: string[] | null) => api.post<{ queued: number }>("/contacts/verify", { contact_ids: ids }), { success: (r) => `Verification queued for ${r.queued} contact(s)`, invalidate: [["contacts"]] });
  const sortBy = (k: string) => setSort(sort === k ? `-${k}` : k);
  const arrow = (k: string) => (sort === k ? " ↑" : sort === `-${k}` ? " ↓" : "");

  return (
    <>
      <PageHeader title="Contacts" subtitle="People at your companies, with consent and subscription status." actions={<>
        {can("marketer") && <Button icon={<BadgeCheck className="h-4 w-4" />} loading={verify.isPending} onClick={() => verify.mutate(sel.length ? sel : null)}>{sel.length ? `Verify ${sel.length}` : "Verify unverified"}</Button>}
        {can("analyst") && <Button icon={<Download className="h-4 w-4" />} onClick={() => download("/contacts/export", { ...flt, q, format: "xlsx" })}>Export</Button>}
        {can("marketer") && <Button icon={<Upload className="h-4 w-4" />} onClick={() => setImp(true)}>Import</Button>}
        {can("marketer") && <Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => setEdit(null)}>Add contact</Button>}
      </>} />
      <div className="card">
        <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 p-3">
          <SearchInput value={q} onChange={(v) => { setQ(v); setPage(1); }} placeholder="Search name, company, position, email…" className="w-72" />
          <MultiSelect label="Department" options={(facets.data?.departments || []).map((d) => ({ value: d, label: d }))} value={flt.department} onChange={setFilter("department")} />
          <MultiSelect label="Job title" options={(facets.data?.job_titles || []).map((d) => ({ value: d, label: d }))} value={flt.job_title} onChange={setFilter("job_title")} />
          <MultiSelect label="Subscription" options={SUB_STATUSES.map((s) => ({ value: s, label: titleCase(s) }))} value={flt.subscription_status} onChange={setFilter("subscription_status")} />
          <MultiSelect label="Verification" options={VERIFY_STATUSES.map((s) => ({ value: s, label: titleCase(s) }))} value={flt.verification} onChange={setFilter("verification")} />
          <MultiSelect label="Industry" options={toOptions(inds.data)} value={flt.industry_id} onChange={setFilter("industry_id")} />
          <MultiSelect label="Category" options={toOptions(cats.data)} value={flt.category_id} onChange={setFilter("category_id")} />
          <MultiSelect label="Tags" options={toOptions(tags.data)} value={flt.tag_id} onChange={setFilter("tag_id")} />
        </div>
        {sel.length > 0 && can("marketer") && (
          <div className="flex items-center gap-2 border-b border-slate-100 bg-brand-50 px-3 py-2 text-sm">
            <span className="font-medium text-brand-800">{sel.length} selected</span>
            <Button size="sm" icon={<Tag className="h-3.5 w-3.5" />} onClick={() => setBulk("tag")}>Tag / categorise</Button>
            <Button size="sm" icon={<UserX className="h-3.5 w-3.5" />} onClick={() => setBulk("unsubscribe")}>Unsubscribe</Button>
            {can("admin") && <Button size="sm" icon={<Trash2 className="h-3.5 w-3.5" />} onClick={() => setBulk("delete")}>Delete</Button>}
            <button className="ms-auto text-xs text-slate-500 hover:underline" onClick={() => setSel([])}>Clear</button>
          </div>
        )}
        {list.isLoading ? <Loading /> : list.error ? <ErrorState error={list.error} retry={list.refetch} /> : items.length === 0 ? (
          <Empty title="No contacts found" hint="Change filters, add a contact, or import a spreadsheet." action={can("marketer") && <Button variant="primary" onClick={() => setImp(true)}>Import contacts</Button>} />
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead><tr>
                  <th className="th w-8"><input type="checkbox" aria-label="Select all" checked={allSel} onChange={(e) => setSel(e.target.checked ? Array.from(new Set([...sel, ...items.map((c) => c.id)])) : sel.filter((id) => !items.some((c) => c.id === id)))} /></th>
                  <th className="th cursor-pointer" onClick={() => sortBy("name")}>Name{arrow("name")}</th>
                  <th className="th cursor-pointer" onClick={() => sortBy("company")}>Company{arrow("company")}</th>
                  <th className="th cursor-pointer" onClick={() => sortBy("job_title")}>Position{arrow("job_title")}</th>
                  <th className="th cursor-pointer" onClick={() => sortBy("email")}>Email{arrow("email")}</th>
                  <th className="th">Phone</th>
                  <th className="th">Subscription</th><th className="th">Email check</th><th className="th">Tags</th>
                </tr></thead>
                <tbody>
                  {items.map((c) => (
                    <tr key={c.id} className={sel.includes(c.id) ? "bg-brand-50/50" : "hover:bg-slate-50"}>
                      <td className="td"><input type="checkbox" aria-label={`Select ${c.email}`} checked={sel.includes(c.id)} onChange={(e) => setSel(e.target.checked ? [...sel, c.id] : sel.filter((x) => x !== c.id))} /></td>
                      <td className="td"><Link href={`/contacts/${c.id}`} className="font-medium text-slate-900 hover:text-brand-700">{fullName(c)}</Link>{c.name_ar && <div dir="rtl" className="text-start text-xs text-slate-600">{c.name_ar}</div>}<div className="text-xs text-slate-400">{c.code}</div></td>
                      <td className="td"><Link href={`/companies/${c.company_id}`} className="hover:underline">{c.company_name}</Link>{c.company_name_ar && <div dir="rtl" className="text-start text-xs text-slate-500">{c.company_name_ar}</div>}</td>
                      <td className="td">{c.job_title || "—"}{c.department && <div className="text-xs text-slate-400">{c.department}</div>}</td>
                      <td className="td">{c.email}{c.is_role_account && <Badge className="ms-1.5">role</Badge>}</td>
                      <td className="td whitespace-nowrap" dir="ltr">{c.phone ? <a className="hover:text-brand-700" href={`tel:${c.phone.replace(/\s/g, "")}`}>{c.phone}</a> : "—"}</td>
                      <td className="td"><StatusBadge status={c.subscription_status} /></td>
                      <td className="td"><StatusBadge status={c.email_verification_status} /></td>
                      <td className="td"><div className="flex max-w-[180px] flex-wrap gap-1">{c.tags.slice(0, 2).map((t) => <Badge key={t.id} tone="brand">{t.name}</Badge>)}{c.tags.length > 2 && <Badge>+{c.tags.length - 2}</Badge>}</div></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination page={page} pageSize={25} total={list.data!.total} onPage={setPage} />
          </>
        )}
      </div>
      <ContactForm open={edit !== undefined} onClose={() => setEdit(undefined)} contact={edit} />
      <ImportWizard entity="contact" open={imp} onClose={() => setImp(false)} />
      <BulkDialog mode={bulk} ids={sel} onClose={() => setBulk(null)} onDone={() => { setBulk(null); setSel([]); }} />
    </>
  );
}

function BulkDialog({ mode, ids, onClose, onDone }: { mode: "tag" | "unsubscribe" | "delete" | null; ids: string[]; onClose: () => void; onDone: () => void }) {
  const tags = useTags();
  const cats = useCategories("contact");
  const [add, setAdd] = useState<string[]>([]);
  const [remove, setRemove] = useState<string[]>([]);
  const [cat, setCat] = useState("");
  const run = useAction((body: Record<string, unknown>) => api.post<{ affected: number }>("/contacts/bulk", { contact_ids: ids, ...body }), {
    success: (r) => `${r.affected} contact(s) updated`, invalidate: [["contacts"]], onSuccess: onDone,
  });
  if (mode === "unsubscribe" || mode === "delete") {
    return <Confirm open onClose={onClose} danger title={mode === "delete" ? "Delete contacts" : "Unsubscribe contacts"} confirmLabel={mode === "delete" ? "Delete" : "Unsubscribe"} loading={run.isPending}
      message={mode === "delete" ? `Archive ${ids.length} contact(s)? Campaign history is kept.` : `Unsubscribe ${ids.length} contact(s) and add them to the suppression list? They will not receive marketing again unless new consent is recorded.`}
      onConfirm={() => run.mutate(mode === "delete" ? { delete: true } : { unsubscribe: true })} />;
  }
  return (
    <Modal open={mode === "tag"} onClose={onClose} title={`Update ${ids.length} contact(s)`} footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={run.isPending} onClick={() => run.mutate({ add_tag_ids: add, remove_tag_ids: remove, category_id: cat || null })}>Apply</Button></>}>
      <div className="space-y-4">
        <div><div className="label">Add tags</div><MultiSelect label="Choose tags" options={toOptions(tags.data)} value={add} onChange={setAdd} /></div>
        <div><div className="label">Remove tags</div><MultiSelect label="Choose tags" options={toOptions(tags.data)} value={remove} onChange={setRemove} /></div>
        <div><div className="label">Set category</div><Select value={cat} onChange={setCat} options={toOptions(cats.data)} placeholder="Leave unchanged" /></div>
      </div>
    </Modal>
  );
}
