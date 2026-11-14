"use client";

import { ArrowLeft, Pencil, ShieldCheck, UserX } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { ContactForm } from "@/components/ContactForm";
import { Alert, Badge, Button, Card, Confirm, ErrorState, Field, Loading, Modal, PageHeader, Select, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate, fullName, titleCase } from "@/lib/format";
import { useAction, useWsQuery } from "@/lib/hooks";
import type { Contact } from "@/lib/types";

export default function ContactPage() {
  const { id } = useParams<{ id: string }>();
  const { can } = useAuth();
  const q = useWsQuery(["contact", id], () => api.get<Contact>(`/contacts/${id}`));
  const [edit, setEdit] = useState(false);
  const [unsub, setUnsub] = useState(false);
  const [consent, setConsent] = useState(false);
  const [cf, setCf] = useState({ lawful_basis: "explicit_consent", source: "", evidence: "" });
  const doUnsub = useAction(() => api.post(`/contacts/${id}/unsubscribe`, { reason: "Manual" }), { success: "Contact unsubscribed and suppressed", invalidate: [["contact"], ["contacts"]], onSuccess: () => setUnsub(false) });
  const addConsent = useAction(() => api.post(`/contacts/${id}/consents`, cf), { success: "Consent recorded", invalidate: [["contact"], ["contacts"]], onSuccess: () => setConsent(false) });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} retry={q.refetch} />;
  const c = q.data!;
  const facts: [string, React.ReactNode][] = [
    ["Contact ID", c.code], ["Company", <Link key="c" className="text-brand-700 hover:underline" href={`/companies/${c.company_id}`}>{c.company_name}</Link>],
    ["Job title", c.job_title], ["Department", c.department], ["Email", c.email], ["Phone", c.phone], ["Country", c.country_code], ["City", c.city],
    ["Category", c.category], ["Email verification", <StatusBadge key="v" status={c.email_verification_status} />], ["Created", fmtDate(c.created_at)],
  ];
  return (
    <>
      <Link href="/contacts" className="mb-3 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800"><ArrowLeft className="h-4 w-4" />Contacts</Link>
      <PageHeader title={fullName(c)} subtitle={<span className="flex items-center gap-2"><StatusBadge status={c.subscription_status} />{c.job_title} · {c.company_name}</span>} actions={<>
        {can("marketer") && c.subscription_status !== "unsubscribed" && !c.suppressed && <Button icon={<UserX className="h-4 w-4" />} onClick={() => setUnsub(true)}>Unsubscribe</Button>}
        {can("marketer") && !c.suppressed && <Button icon={<ShieldCheck className="h-4 w-4" />} onClick={() => setConsent(true)}>Record consent</Button>}
        {can("marketer") && <Button variant="primary" icon={<Pencil className="h-4 w-4" />} onClick={() => setEdit(true)}>Edit</Button>}
      </>} />
      {c.suppressed && <div className="mb-5"><Alert tone="amber" title="Suppressed">This address is on the suppression list ({titleCase(c.suppressed)}). It is excluded from every campaign.</Alert></div>}
      {c.subscription_status === "pending" && <div className="mb-5"><Alert tone="blue">No marketing consent recorded yet. This contact will not receive campaigns until consent is recorded.</Alert></div>}
      <div className="grid gap-5 lg:grid-cols-3">
        <Card title="Details">
          <dl className="space-y-2.5 text-sm">{facts.map(([k, v]) => <div key={k} className="flex justify-between gap-3"><dt className="text-slate-500">{k}</dt><dd className="text-end font-medium text-slate-800">{v || "—"}</dd></div>)}</dl>
          {c.tags.length > 0 && <div className="mt-4 flex flex-wrap gap-1.5">{c.tags.map((t) => <Badge key={t.id} tone="brand">{t.name}</Badge>)}</div>}
        </Card>
        <Card title="Consent history" className="lg:col-span-2" bodyClass="p-0">
          {!c.consents?.length ? <div className="p-6 text-center text-sm text-slate-500">No consent records.</div> : (
            <table className="w-full">
              <thead><tr><th className="th">Lawful basis</th><th className="th">Source</th><th className="th">Granted</th><th className="th">Withdrawn</th></tr></thead>
              <tbody>{c.consents.map((x) => (
                <tr key={x.id}><td className="td">{titleCase(x.lawful_basis)}</td><td className="td">{x.source}{x.evidence && <div className="text-xs text-slate-400">{x.evidence}</div>}</td><td className="td">{fmtDate(x.granted_at, true)}</td><td className="td">{x.withdrawn_at ? <Badge tone="red">{fmtDate(x.withdrawn_at)}</Badge> : <Badge tone="green">Active</Badge>}</td></tr>
              ))}</tbody>
            </table>
          )}
          {c.notes && <div className="border-t border-slate-100 p-4 text-sm"><div className="label">Notes</div><p className="whitespace-pre-line">{c.notes}</p></div>}
        </Card>
      </div>
      <ContactForm open={edit} onClose={() => setEdit(false)} contact={c} />
      <Confirm open={unsub} onClose={() => setUnsub(false)} onConfirm={() => doUnsub.mutate(undefined)} loading={doUnsub.isPending} danger title="Unsubscribe contact" confirmLabel="Unsubscribe" message="Active consent is withdrawn and the address is added to the suppression list. It will be excluded from all future campaigns." />
      <Modal open={consent} onClose={() => setConsent(false)} title="Record marketing consent" footer={<><Button onClick={() => setConsent(false)}>Cancel</Button><Button variant="primary" loading={addConsent.isPending} disabled={cf.source.length < 2} onClick={() => addConsent.mutate(undefined)}>Record consent</Button></>}>
        <div className="space-y-3">
          <Field label="Lawful basis"><Select value={cf.lawful_basis} onChange={(v) => setCf({ ...cf, lawful_basis: v })} options={[{ value: "explicit_consent", label: "Explicit consent" }, { value: "legitimate_interest", label: "Legitimate interest" }, { value: "existing_customer", label: "Existing customer" }, { value: "contract", label: "Contract" }]} /></Field>
          <Field label="Source *"><input className="input" value={cf.source} onChange={(e) => setCf({ ...cf, source: e.target.value })} placeholder="e.g. Signed form at event, website opt-in" /></Field>
          <Field label="Evidence"><textarea className="input" value={cf.evidence} onChange={(e) => setCf({ ...cf, evidence: e.target.value })} placeholder="Where the proof is kept" /></Field>
        </div>
      </Modal>
    </>
  );
}
