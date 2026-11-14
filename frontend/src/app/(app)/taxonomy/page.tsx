"use client";

import { Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { Button, Card, Confirm, Empty, ErrorState, Field, Loading, Modal, PageHeader, Select, Tabs } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useAction, useCategories, useIndustries, useTags } from "@/lib/hooks";

type Kind = "industries" | "categories" | "tags";
type Item = { id: string; name: string; color?: string | null; scope?: string; company_count?: number; contact_count?: number; usage_count?: number };
const COLORS = ["#2f5a8c", "#0e9f8f", "#7c3aed", "#d97706", "#dc2626", "#0284c7", "#16a34a", "#64748b"];

export default function TaxonomyPage() {
  const [tab, setTab] = useState<Kind>("tags");
  const { can } = useAuth();
  const tags = useTags();
  const cats = useCategories();
  const inds = useIndustries();
  const [edit, setEdit] = useState<Item | null | undefined>(undefined);
  const [del, setDel] = useState<Item | null>(null);
  const [form, setForm] = useState({ name: "", color: COLORS[0], scope: "company" });
  const q = { tags, categories: cats, industries: inds }[tab];
  const save = useAction(() => {
    const body = tab === "industries" ? { name: form.name } : tab === "categories" ? (edit ? { name: form.name, color: form.color } : form) : { name: form.name, color: form.color };
    return edit ? api.patch(`/${tab}/${edit.id}`, body) : api.post(`/${tab}`, body);
  }, { success: "Saved", invalidate: [[tab]], onSuccess: () => setEdit(undefined) });
  const remove = useAction(() => api.del(`/${tab}/${del!.id}`), { success: "Deleted", invalidate: [[tab]], onSuccess: () => setDel(null) });
  const open = (it: Item | null) => { setForm({ name: it?.name || "", color: it?.color || COLORS[0], scope: it?.scope || "company" }); setEdit(it); };
  const usage = (it: Item) => tab === "tags" ? `${it.company_count} companies · ${it.contact_count} contacts` : tab === "industries" ? `${it.company_count} companies` : `${it.usage_count} records`;
  const singular = { tags: "tag", categories: "category", industries: "industry" }[tab];

  return (
    <>
      <PageHeader title="Categories & Tags" subtitle="Organise companies and contacts for filtering and segmentation." actions={can("marketer") && <Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => open(null)}>Add {singular}</Button>} />
      <Tabs value={tab} onChange={(v) => setTab(v as Kind)} tabs={[{ value: "tags", label: "Tags" }, { value: "categories", label: "Categories" }, { value: "industries", label: "Industries" }]} />
      <Card bodyClass="p-0">
        {q.isLoading ? <Loading /> : q.error ? <ErrorState error={q.error} /> : !(q.data as Item[]).length ? <Empty title={`No ${tab} yet`} /> : (
          <table className="w-full">
            <thead><tr><th className="th">Name</th>{tab === "categories" && <th className="th">Applies to</th>}<th className="th">Usage</th><th className="th" /></tr></thead>
            <tbody>{(q.data as Item[]).map((it) => (
              <tr key={it.id} className="hover:bg-slate-50">
                <td className="td"><span className="inline-flex items-center gap-2 font-medium">{tab !== "industries" && <span className="h-2.5 w-2.5 rounded-full" style={{ background: it.color || "#94a3b8" }} />}{it.name}</span></td>
                {tab === "categories" && <td className="td capitalize">{it.scope}</td>}
                <td className="td text-slate-500">{usage(it)}</td>
                <td className="td text-end">{can("marketer") && <div className="flex justify-end gap-1"><Button size="sm" variant="ghost" onClick={() => open(it)} aria-label="Edit"><Pencil className="h-3.5 w-3.5" /></Button><Button size="sm" variant="ghost" onClick={() => setDel(it)} aria-label="Delete"><Trash2 className="h-3.5 w-3.5 text-red-600" /></Button></div>}</td>
              </tr>))}
            </tbody>
          </table>
        )}
      </Card>
      <Modal open={edit !== undefined} onClose={() => setEdit(undefined)} title={`${edit ? "Edit" : "Add"} ${singular}`} footer={<><Button onClick={() => setEdit(undefined)}>Cancel</Button><Button variant="primary" loading={save.isPending} disabled={!form.name.trim()} onClick={() => save.mutate(undefined)}>Save</Button></>}>
        <div className="space-y-4">
          <Field label="Name"><input className="input" autoFocus value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          {tab === "categories" && !edit && <Field label="Applies to"><Select value={form.scope} onChange={(v) => setForm({ ...form, scope: v })} options={[{ value: "company", label: "Companies" }, { value: "contact", label: "Contacts" }]} /></Field>}
          {tab !== "industries" && (
            <Field label="Colour"><div className="flex gap-2">{COLORS.map((c) => <button key={c} type="button" aria-label={c} onClick={() => setForm({ ...form, color: c })} className={`h-7 w-7 rounded-full ring-offset-2 ${form.color === c ? "ring-2 ring-slate-800" : ""}`} style={{ background: c }} />)}</div></Field>
          )}
        </div>
      </Modal>
      <Confirm open={!!del} onClose={() => setDel(null)} onConfirm={() => remove.mutate(undefined)} loading={remove.isPending} danger title={`Delete ${singular}`} confirmLabel="Delete" message={<>Delete <b>{del?.name}</b>? It will be removed from all companies and contacts.</>} />
    </>
  );
}
