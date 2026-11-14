"use client";

import { Copy, Download, Plus, Upload } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { CompanyForm } from "@/components/CompanyForm";
import { ImportWizard } from "@/components/ImportWizard";
import { Badge, Button, Confirm, Empty, ErrorState, Loading, Modal, MultiSelect, PageHeader, Pagination, SearchInput, StatusBadge } from "@/components/ui";
import { api, download } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { COMPANY_SIZES, COMPANY_STATUSES, COUNTRIES, fmtDate, titleCase } from "@/lib/format";
import { toOptions, useAction, useIndustries, useTags, useWsQuery } from "@/lib/hooks";
import type { Company, Page } from "@/lib/types";

type Dup = { a: { id: string; name: string; domain: string | null }; b: { id: string; name: string; domain: string | null }; score: number; same_domain: boolean };

export default function CompaniesPage() {
  const { can } = useAuth();
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState("-created_at");
  const [flt, setFlt] = useState<Record<string, string[]>>({ industry_id: [], country_code: [], company_size: [], status: [], tag_id: [] });
  const [edit, setEdit] = useState<Company | null | undefined>(undefined);
  const [imp, setImp] = useState(false);
  const [dupOpen, setDupOpen] = useState(false);
  const industries = useIndustries();
  const tags = useTags();
  const query = { q, page, page_size: 25, sort, ...flt };
  const list = useWsQuery(["companies", query], () => api.get<Page<Company>>("/companies", query));
  const setFilter = (k: string) => (v: string[]) => { setFlt({ ...flt, [k]: v }); setPage(1); };
  const sortBy = (k: string) => setSort(sort === k ? `-${k}` : k);
  const arrow = (k: string) => (sort === k ? " ↑" : sort === `-${k}` ? " ↓" : "");

  return (
    <>
      <PageHeader title="Companies" subtitle="Company master database with categories, tags and contacts." actions={<>
        {can("marketer") && <Button icon={<Copy className="h-4 w-4" />} onClick={() => setDupOpen(true)}>Duplicates</Button>}
        {can("analyst") && <Button icon={<Download className="h-4 w-4" />} onClick={() => download("/companies/export", { ...flt, q, format: "xlsx" })}>Export</Button>}
        {can("marketer") && <Button icon={<Upload className="h-4 w-4" />} onClick={() => setImp(true)}>Import</Button>}
        {can("marketer") && <Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => setEdit(null)}>Add company</Button>}
      </>} />
      <div className="card">
        <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 p-3">
          <SearchInput value={q} onChange={(v) => { setQ(v); setPage(1); }} placeholder="Search name, website, ID, city…" />
          <MultiSelect label="Industry" options={toOptions(industries.data)} value={flt.industry_id} onChange={setFilter("industry_id")} />
          <MultiSelect label="Country" options={COUNTRIES.map(([v, l]) => ({ value: v, label: l }))} value={flt.country_code} onChange={setFilter("country_code")} />
          <MultiSelect label="Size" options={COMPANY_SIZES.map((s) => ({ value: s, label: s }))} value={flt.company_size} onChange={setFilter("company_size")} />
          <MultiSelect label="Status" options={COMPANY_STATUSES.map((s) => ({ value: s, label: titleCase(s) }))} value={flt.status} onChange={setFilter("status")} />
          <MultiSelect label="Tags" options={toOptions(tags.data)} value={flt.tag_id} onChange={setFilter("tag_id")} />
        </div>
        {list.isLoading ? <Loading /> : list.error ? <ErrorState error={list.error} retry={list.refetch} /> : list.data!.items.length === 0 ? (
          <Empty title="No companies found" hint={q || Object.values(flt).some((v) => v.length) ? "Try changing your search or filters." : "Add your first company or import a spreadsheet."} action={can("marketer") && <Button variant="primary" onClick={() => setImp(true)}>Import companies</Button>} />
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead><tr>
                  <th className="th cursor-pointer" onClick={() => sortBy("name")}>Company{arrow("name")}</th>
                  <th className="th">Industry</th>
                  <th className="th cursor-pointer" onClick={() => sortBy("country")}>Location{arrow("country")}</th>
                  <th className="th">Size</th><th className="th">Contacts</th><th className="th">Tags</th><th className="th">Status</th>
                  <th className="th cursor-pointer" onClick={() => sortBy("created_at")}>Added{arrow("created_at")}</th>
                </tr></thead>
                <tbody>
                  {list.data!.items.map((c) => (
                    <tr key={c.id} className="hover:bg-slate-50">
                      <td className="td">
                        <Link href={`/companies/${c.id}`} className="font-medium text-slate-900 hover:text-brand-700">{c.name}</Link>
                        {c.name_ar && <div dir="rtl" className="text-start text-xs text-slate-500">{c.name_ar}</div>}
                        <div className="text-xs text-slate-400">{c.code}{c.domain && ` · ${c.domain}`}</div>
                      </td>
                      <td className="td">{c.industry || "—"}</td>
                      <td className="td">{[c.city, c.country_code].filter(Boolean).join(", ") || "—"}</td>
                      <td className="td">{c.company_size || "—"}</td>
                      <td className="td tabular-nums">{c.contact_count}</td>
                      <td className="td"><div className="flex max-w-[200px] flex-wrap gap-1">{c.tags.slice(0, 3).map((t) => <Badge key={t.id} tone="brand">{t.name}</Badge>)}{c.tags.length > 3 && <Badge>+{c.tags.length - 3}</Badge>}</div></td>
                      <td className="td"><StatusBadge status={c.status} /></td>
                      <td className="td text-slate-500">{fmtDate(c.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination page={page} pageSize={25} total={list.data!.total} onPage={setPage} />
          </>
        )}
      </div>
      <CompanyForm open={edit !== undefined} onClose={() => setEdit(undefined)} company={edit} />
      <ImportWizard entity="company" open={imp} onClose={() => setImp(false)} />
      <Duplicates open={dupOpen} onClose={() => setDupOpen(false)} />
    </>
  );
}

function Duplicates({ open, onClose }: { open: boolean; onClose: () => void }) {
  const q = useWsQuery(["companies", "duplicates"], () => api.get<Dup[]>("/companies/duplicates"), { enabled: open });
  const { can } = useAuth();
  const [merge, setMerge] = useState<{ keep: Dup["a"]; drop: Dup["b"] } | null>(null);
  const doMerge = useAction(() => api.post<{ contacts_moved: number }>("/companies/merge", { primary_id: merge!.keep.id, duplicate_ids: [merge!.drop.id] }), {
    success: (r) => `Merged. ${r.contacts_moved} contact(s) moved.`, invalidate: [["companies"]], onSuccess: () => setMerge(null),
  });
  return (
    <Modal open={open} onClose={onClose} title="Possible duplicate companies" wide>
      {!open ? null : q.isLoading || !q.data ? (q.error ? <ErrorState error={q.error} /> : <Loading />) : q.data.length === 0 ? <Empty title="No duplicates detected" hint="Companies are compared by website domain and name similarity." /> : (
        <table className="w-full">
          <thead><tr><th className="th">Company A</th><th className="th">Company B</th><th className="th">Match</th><th className="th" /></tr></thead>
          <tbody>
            {q.data.map((d) => (
              <tr key={d.a.id + d.b.id}>
                <td className="td"><Link className="hover:underline" href={`/companies/${d.a.id}`}>{d.a.name}</Link><div className="text-xs text-slate-400">{d.a.domain}</div></td>
                <td className="td"><Link className="hover:underline" href={`/companies/${d.b.id}`}>{d.b.name}</Link><div className="text-xs text-slate-400">{d.b.domain}</div></td>
                <td className="td">{d.same_domain ? <Badge tone="red">Same website</Badge> : <Badge tone="amber">{Math.round(d.score * 100)}% similar</Badge>}</td>
                <td className="td text-end">{can("admin") && <div className="flex justify-end gap-1"><Button size="sm" onClick={() => setMerge({ keep: d.a, drop: d.b })}>Keep A</Button><Button size="sm" onClick={() => setMerge({ keep: d.b, drop: d.a })}>Keep B</Button></div>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <Confirm open={!!merge} onClose={() => setMerge(null)} onConfirm={() => doMerge.mutate(undefined)} loading={doMerge.isPending} title="Merge companies" confirmLabel="Merge"
        message={merge && <>Contacts, tags and categories from <b>{merge.drop.name}</b> move to <b>{merge.keep.name}</b>, empty fields are filled in, and <b>{merge.drop.name}</b> is archived.</>} />
    </Modal>
  );
}
