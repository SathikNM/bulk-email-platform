"use client";

import { ArrowLeft, Copy, Save } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { CountPanel, SegmentBuilder, useLiveCount } from "@/components/SegmentBuilder";
import { Badge, Button, Card, ErrorState, Field, Loading, PageHeader, Pagination, StatusBadge, Toggle } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fullName } from "@/lib/format";
import { useAction, useWsQuery } from "@/lib/hooks";
import type { RuleGroup, Segment } from "@/lib/types";

type PreviewRow = { id: string; first_name: string | null; last_name: string | null; email: string; job_title: string | null; company_name: string; city: string | null; country_code: string | null; subscription_status: string; eligible: boolean };

export default function SegmentEditor() {
  const { id } = useParams<{ id: string }>();
  const isNew = id === "new";
  const router = useRouter();
  const { can } = useAuth();
  const seg = useWsQuery(["segment", id], () => api.get<Segment>(`/segments/${id}`), { enabled: !isNew });
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [rules, setRules] = useState<RuleGroup>({ op: "and", rules: [{ field: "subscription_status", operator: "eq", value: "subscribed" }] });
  const [page, setPage] = useState(1);
  const [eligibleOnly, setEligibleOnly] = useState(true);
  const live = useLiveCount(rules);
  const preview = useWsQuery(["segment-preview", JSON.stringify(rules), page, eligibleOnly], () => api.post<{ items: PreviewRow[]; total: number }>(`/segments/preview?page=${page}&page_size=10&eligible_only=${eligibleOnly}`, { rules }));

  useEffect(() => {
    if (seg.data) { setName(seg.data.name); setDescription(seg.data.description || ""); setRules(seg.data.rules); }
  }, [seg.data?.id]);

  const save = useAction(() => isNew ? api.post<Segment>("/segments", { name, description, rules }) : api.patch<Segment>(`/segments/${id}`, { name, description, rules }), {
    success: "Segment saved", invalidate: [["segments"], ["segment"]], onSuccess: (s) => isNew && router.replace(`/segments/${s.id}`),
  });
  const dup = useAction(() => api.post<Segment>(`/segments/${id}/duplicate`), { success: "Duplicated", invalidate: [["segments"]], onSuccess: (s) => router.push(`/segments/${s.id}`) });

  if (!isNew && seg.isLoading) return <Loading />;
  if (!isNew && seg.error) return <ErrorState error={seg.error} />;
  return (
    <>
      <Link href="/segments" className="mb-3 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800"><ArrowLeft className="h-4 w-4" />Segments</Link>
      <PageHeader title={isNew ? "New segment" : name || "Segment"} subtitle="Combine conditions with ALL (and) / ANY (or). Counts update as you edit."
        actions={can("marketer") && <>{!isNew && <Button icon={<Copy className="h-4 w-4" />} onClick={() => dup.mutate(undefined)}>Duplicate</Button>}<Button variant="primary" icon={<Save className="h-4 w-4" />} loading={save.isPending} disabled={!name.trim()} onClick={() => save.mutate(undefined)}>Save segment</Button></>} />
      <div className="grid gap-5 xl:grid-cols-[1fr_300px]">
        <div className="space-y-5">
          <Card>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Segment name *"><input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. KSA Construction finance leaders" /></Field>
              <Field label="Description"><input className="input" value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
            </div>
          </Card>
          <SegmentBuilder value={rules} onChange={(r) => { setRules(r); setPage(1); }} />
          <Card title="Preview matching contacts" bodyClass="p-0" actions={<Toggle checked={eligibleOnly} onChange={(v) => { setEligibleOnly(v); setPage(1); }} label="Eligible only" />}>
            {preview.isLoading ? <Loading /> : preview.error ? <ErrorState error={preview.error} /> : (
              <>
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead><tr><th className="th">Name</th><th className="th">Company</th><th className="th">Job title</th><th className="th">Location</th><th className="th">Status</th><th className="th">Eligible</th></tr></thead>
                    <tbody>{preview.data!.items.map((c) => (
                      <tr key={c.id}><td className="td"><Link href={`/contacts/${c.id}`} className="font-medium hover:text-brand-700">{fullName(c)}</Link><div className="text-xs text-slate-400">{c.email}</div></td><td className="td">{c.company_name}</td><td className="td">{c.job_title || "—"}</td><td className="td">{[c.city, c.country_code].filter(Boolean).join(", ") || "—"}</td><td className="td"><StatusBadge status={c.subscription_status} /></td><td className="td">{c.eligible ? <Badge tone="green">Yes</Badge> : <Badge tone="red">No</Badge>}</td></tr>
                    ))}</tbody>
                  </table>
                  {preview.data!.items.length === 0 && <div className="p-6 text-center text-sm text-slate-500">No contacts match.</div>}
                </div>
                <Pagination page={page} pageSize={10} total={preview.data!.total} onPage={setPage} />
              </>
            )}
          </Card>
        </div>
        <div className="xl:sticky xl:top-20 xl:self-start"><CountPanel {...live} /></div>
      </div>
    </>
  );
}
