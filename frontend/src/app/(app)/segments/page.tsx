"use client";

import { Copy, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button, Card, Confirm, Empty, ErrorState, Loading, PageHeader, SearchInput } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate, fmtNum } from "@/lib/format";
import { useAction, useWsQuery } from "@/lib/hooks";
import type { Page, Segment } from "@/lib/types";

export default function SegmentsPage() {
  const { can } = useAuth();
  const router = useRouter();
  const [q, setQ] = useState("");
  const [del, setDel] = useState<Segment | null>(null);
  const list = useWsQuery(["segments", q], () => api.get<Page<Segment>>("/segments", { q, page_size: 200 }));
  const dup = useAction((id: string) => api.post<Segment>(`/segments/${id}/duplicate`), { success: "Segment duplicated", invalidate: [["segments"]], onSuccess: (s) => router.push(`/segments/${s.id}`) });
  const remove = useAction(() => api.del(`/segments/${del!.id}`), { success: "Segment deleted", invalidate: [["segments"]], onSuccess: () => setDel(null) });
  return (
    <>
      <PageHeader title="Audience Segments" subtitle="Saved audiences built from company and contact filters. Counts exclude anyone who cannot legally be emailed."
        actions={<>{<SearchInput value={q} onChange={setQ} placeholder="Search segments…" />}{can("marketer") && <Link href="/segments/new"><Button variant="primary" icon={<Plus className="h-4 w-4" />}>New segment</Button></Link>}</>} />
      <Card bodyClass="p-0">
        {list.isLoading ? <Loading /> : list.error ? <ErrorState error={list.error} /> : list.data!.items.length === 0 ? (
          <Empty title="No segments yet" hint="Create a segment such as “Construction CFOs in Riyadh”." action={can("marketer") && <Link href="/segments/new"><Button variant="primary">Create segment</Button></Link>} />
        ) : (
          <table className="w-full">
            <thead><tr><th className="th">Segment</th><th className="th">Eligible</th><th className="th">Matching</th><th className="th">Used in</th><th className="th">Updated</th><th className="th" /></tr></thead>
            <tbody>{list.data!.items.map((s) => (
              <tr key={s.id} className="hover:bg-slate-50">
                <td className="td"><Link href={`/segments/${s.id}`} className="font-medium text-slate-900 hover:text-brand-700">{s.name}</Link>{s.description && <div className="max-w-md truncate text-xs text-slate-400">{s.description}</div>}</td>
                <td className="td font-semibold tabular-nums text-emerald-700">{fmtNum(s.cached_eligible_count)}</td>
                <td className="td tabular-nums">{fmtNum(s.cached_count)}</td>
                <td className="td">{s.campaign_count ? `${s.campaign_count} campaign(s)` : "—"}</td>
                <td className="td text-slate-500">{fmtDate(s.updated_at)}</td>
                <td className="td text-end">{can("marketer") && <div className="flex justify-end gap-1">
                  <Button size="sm" variant="ghost" onClick={() => dup.mutate(s.id)} aria-label="Duplicate"><Copy className="h-3.5 w-3.5" /></Button>
                  <Button size="sm" variant="ghost" onClick={() => setDel(s)} aria-label="Delete"><Trash2 className="h-3.5 w-3.5 text-red-600" /></Button>
                </div>}</td>
              </tr>))}
            </tbody>
          </table>
        )}
      </Card>
      <Confirm open={!!del} onClose={() => setDel(null)} onConfirm={() => remove.mutate(undefined)} loading={remove.isPending} danger title="Delete segment" confirmLabel="Delete" message={<>Delete <b>{del?.name}</b>? Campaigns that already used it keep their recipient list.</>} />
    </>
  );
}
