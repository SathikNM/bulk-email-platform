"use client";

import { Copy, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button, Empty, ErrorState, Loading, MultiSelect, PageHeader, Pagination, Progress, SearchInput, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate, fmtNum, fmtPct, titleCase } from "@/lib/format";
import { useAction, useWsQuery } from "@/lib/hooks";
import type { Campaign, Page } from "@/lib/types";

const STATUSES = ["draft", "scheduled", "processing", "sending", "completed", "paused", "failed", "cancelled"];

export default function CampaignHistory() {
  const { can } = useAuth();
  const router = useRouter();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState<string[]>([]);
  const [page, setPage] = useState(1);
  const query = { q, status, page, page_size: 20 };
  const list = useWsQuery(["campaigns", query], () => api.get<Page<Campaign>>("/campaigns", query), { refetchInterval: 5000 });
  const dup = useAction((id: string) => api.post<Campaign>(`/campaigns/${id}/duplicate`), { success: "Campaign duplicated", invalidate: [["campaigns"]], onSuccess: (c) => router.push(`/campaigns/new?id=${c.id}`) });
  return (
    <>
      <PageHeader title="Campaign History" subtitle="Every campaign with its status and results." actions={can("marketer") && <Link href="/campaigns/new"><Button variant="primary" icon={<Plus className="h-4 w-4" />}>Create campaign</Button></Link>} />
      <div className="card">
        <div className="flex flex-wrap gap-2 border-b border-slate-100 p-3">
          <SearchInput value={q} onChange={(v) => { setQ(v); setPage(1); }} placeholder="Search name or subject…" />
          <MultiSelect label="Status" options={STATUSES.map((s) => ({ value: s, label: titleCase(s) }))} value={status} onChange={(v) => { setStatus(v); setPage(1); }} />
        </div>
        {list.isLoading ? <Loading /> : list.error ? <ErrorState error={list.error} retry={list.refetch} /> : list.data!.items.length === 0 ? (
          <Empty title="No campaigns yet" action={can("marketer") && <Link href="/campaigns/new"><Button variant="primary">Create your first campaign</Button></Link>} />
        ) : (
          <>
            <div className="overflow-x-auto"><table className="w-full">
              <thead><tr>{["Campaign", "Status", "Audience", "Progress", "Sent", "Open", "Click", "Bounce", "Date", ""].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
              <tbody>{list.data!.items.map((c) => (
                <tr key={c.id} className="hover:bg-slate-50">
                  <td className="td"><Link href={c.status === "draft" ? `/campaigns/new?id=${c.id}` : `/campaigns/${c.id}`} className="font-medium text-slate-900 hover:text-brand-700">{c.name}</Link><div className="max-w-xs truncate text-xs text-slate-400" dir="auto">{c.subject}</div></td>
                  <td className="td"><StatusBadge status={c.status} />{c.status === "draft" && c.is_approved && <div className="mt-0.5 text-[11px] text-emerald-700">Approved</div>}</td>
                  <td className="td text-xs">{c.segment_name || (c.manual_contact_count ? `${c.manual_contact_count} contact(s)` : "—")}</td>
                  <td className="td w-32">{c.stats.recipients > 0 ? <><Progress value={c.stats.progress} tone={c.status === "completed" ? "green" : "brand"} /><div className="mt-0.5 text-[11px] text-slate-400">{fmtPct(c.stats.progress)}</div></> : <span className="text-slate-400">—</span>}</td>
                  <td className="td tabular-nums">{fmtNum(c.stats.sent)}</td>
                  <td className="td tabular-nums">{c.stats.sent ? fmtPct(c.stats.open_rate) : "—"}</td>
                  <td className="td tabular-nums">{c.stats.sent ? fmtPct(c.stats.click_rate) : "—"}</td>
                  <td className="td tabular-nums">{c.stats.sent ? fmtPct(c.stats.bounce_rate) : "—"}</td>
                  <td className="td text-xs text-slate-500">{c.scheduled_at && c.status === "scheduled" ? `Scheduled ${fmtDate(c.scheduled_at, true)}` : fmtDate(c.started_at || c.created_at)}</td>
                  <td className="td">{can("marketer") && <Button size="sm" variant="ghost" onClick={() => dup.mutate(c.id)} aria-label="Duplicate"><Copy className="h-3.5 w-3.5" /></Button>}</td>
                </tr>))}
              </tbody>
            </table></div>
            <Pagination page={page} pageSize={20} total={list.data!.total} onPage={setPage} />
          </>
        )}
      </div>
    </>
  );
}
