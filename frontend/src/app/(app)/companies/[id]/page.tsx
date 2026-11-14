"use client";

import { ArrowLeft, Globe, Pencil, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { CompanyForm } from "@/components/CompanyForm";
import { ContactForm } from "@/components/ContactForm";
import { Badge, Button, Card, Confirm, Empty, ErrorState, Loading, PageHeader, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate, fullName } from "@/lib/format";
import { useAction, useWsQuery } from "@/lib/hooks";
import type { Company } from "@/lib/types";

export default function CompanyPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { can } = useAuth();
  const q = useWsQuery(["company", id], () => api.get<Company>(`/companies/${id}`));
  const [edit, setEdit] = useState(false);
  const [addContact, setAddContact] = useState(false);
  const [del, setDel] = useState(false);
  const remove = useAction((cascade: boolean) => api.del(`/companies/${id}${cascade ? "?cascade_archive=true" : ""}`), {
    success: "Company archived", invalidate: [["companies"]], onSuccess: () => router.push("/companies"),
  });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} retry={q.refetch} />;
  const c = q.data!;
  const facts: [string, React.ReactNode][] = [
    ["Company ID", c.code], ["Industry", c.industry], ["Business type", c.business_type], ["Country", c.country_code], ["City", c.city],
    ["Size", c.company_size && `${c.company_size} employees`], ["Annual revenue", c.annual_revenue && Number(c.annual_revenue).toLocaleString()],
    ["Data source", c.data_source], ["Created", fmtDate(c.created_at)], ["Updated", fmtDate(c.updated_at)],
  ];
  return (
    <>
      <Link href="/companies" className="mb-3 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800"><ArrowLeft className="h-4 w-4" />Companies</Link>
      <PageHeader title={c.name} subtitle={<span className="flex items-center gap-2"><StatusBadge status={c.status} />{c.website && <a href={c.website} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-brand-700 hover:underline"><Globe className="h-3.5 w-3.5" />{c.domain}</a>}</span>}
        actions={<>
          {can("admin") && <Button icon={<Trash2 className="h-4 w-4" />} onClick={() => setDel(true)}>Archive</Button>}
          {can("marketer") && <Button variant="primary" icon={<Pencil className="h-4 w-4" />} onClick={() => setEdit(true)}>Edit</Button>}
        </>} />
      <div className="grid gap-5 lg:grid-cols-3">
        <div className="space-y-5">
          <Card title="Profile">
            <dl className="space-y-2.5 text-sm">
              {facts.map(([k, v]) => <div key={k} className="flex justify-between gap-3"><dt className="text-slate-500">{k}</dt><dd className="text-end font-medium text-slate-800">{v || "—"}</dd></div>)}
            </dl>
          </Card>
          <Card title="Categories & tags">
            <div className="flex flex-wrap gap-1.5">
              {c.categories.map((x) => <Badge key={x.id} tone="violet">{x.name}</Badge>)}
              {c.tags.map((t) => <Badge key={t.id} tone="brand">{t.name}</Badge>)}
              {!c.categories.length && !c.tags.length && <span className="text-sm text-slate-400">None</span>}
            </div>
          </Card>
          {c.notes && <Card title="Notes"><p className="whitespace-pre-line text-sm text-slate-700">{c.notes}</p></Card>}
        </div>
        <div className="space-y-5 lg:col-span-2">
          <Card title={`Contacts (${c.contact_count})`} bodyClass="p-0" actions={can("marketer") && <Button size="sm" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setAddContact(true)}>Add contact</Button>}>
            {c.contacts!.length === 0 ? <Empty title="No contacts yet" hint="Add the people you work with at this company." /> : (
              <table className="w-full">
                <thead><tr><th className="th">Name</th><th className="th">Job title</th><th className="th">Email</th><th className="th">Subscription</th></tr></thead>
                <tbody>{c.contacts!.map((p) => (
                  <tr key={p.id} className="hover:bg-slate-50">
                    <td className="td"><Link className="font-medium hover:text-brand-700" href={`/contacts/${p.id}`}>{fullName(p)}</Link></td>
                    <td className="td">{p.job_title || "—"}{p.department && <div className="text-xs text-slate-400">{p.department}</div>}</td>
                    <td className="td">{p.email}</td>
                    <td className="td"><StatusBadge status={p.subscription_status} /></td>
                  </tr>))}
                </tbody>
              </table>
            )}
          </Card>
          <Card title="Campaign history" bodyClass="p-0">
            {c.campaigns!.length === 0 ? <div className="p-6 text-center text-sm text-slate-500">No campaigns have reached this company yet.</div> : (
              <table className="w-full"><tbody>{c.campaigns!.map((x) => (
                <tr key={x.id}><td className="td"><Link className="hover:underline" href={`/campaigns/${x.id}`}>{x.name}</Link></td><td className="td"><StatusBadge status={x.status} /></td><td className="td text-end text-slate-500">{x.sent} recipient(s)</td></tr>
              ))}</tbody></table>
            )}
          </Card>
        </div>
      </div>
      <CompanyForm open={edit} onClose={() => setEdit(false)} company={c} />
      <ContactForm open={addContact} onClose={() => setAddContact(false)} defaultCompany={{ id: c.id, name: c.name }} />
      <Confirm open={del} onClose={() => setDel(false)} danger confirmLabel={c.contact_count > 0 ? "Archive company and contacts" : "Archive"} loading={remove.isPending} title="Archive company"
        message={c.contact_count > 0 ? <>This company has <b>{c.contact_count}</b> contact(s). Archiving it will also archive them. Campaign history is kept.</> : "The company will be archived. Campaign history is kept."}
        onConfirm={() => remove.mutate(c.contact_count > 0)} />
    </>
  );
}
