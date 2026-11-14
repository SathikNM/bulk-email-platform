"use client";

import { Building2, MailCheck, MailOpen, MousePointerClick, Send, ShieldCheck, Undo2, Users, UserX } from "lucide-react";
import Link from "next/link";
import { api } from "@/lib/api";
import { fmtDate, fmtNum, fmtPct } from "@/lib/format";
import { useWsQuery } from "@/lib/hooks";
import { C, GroupedBars, GrowthChart, TrendChart } from "./charts";
import { Card, ErrorState, Loading, MultiSelect, Stat, StatusBadge } from "./ui";

export type Filters = { date_from: string; date_to: string; campaign_id: string[] };

type Overview = Record<string, number> & { period: { from: string; to: string } };
type TrendRow = { date: string; sent: number; delivered: number; bounced: number; unique_opened: number; unique_clicked: number; open_rate: number; click_rate: number; unsubscribed: number };

export function FiltersBar({ f, setF }: { f: Filters; setF: (f: Filters) => void }) {
  const opts = useWsQuery(["analytics", "campaign-options"], () => api.get<{ id: string; name: string }[]>("/analytics/campaign-options"));
  const preset = (days: number) => {
    const to = new Date();
    const from = new Date();
    from.setDate(from.getDate() - (days - 1));
    setF({ ...f, date_from: from.toISOString().slice(0, 10), date_to: to.toISOString().slice(0, 10) });
  };
  return (
    <div className="mb-5 flex flex-wrap items-end gap-2">
      <div><label className="label">From</label><input type="date" className="input w-40" value={f.date_from} onChange={(e) => setF({ ...f, date_from: e.target.value })} /></div>
      <div><label className="label">To</label><input type="date" className="input w-40" value={f.date_to} onChange={(e) => setF({ ...f, date_to: e.target.value })} /></div>
      <div className="flex gap-1">
        {[7, 30, 90, 365].map((d) => <button key={d} onClick={() => preset(d)} className="rounded-lg border border-slate-300 bg-white px-2.5 py-2 text-xs font-medium text-slate-600 hover:bg-slate-50">{d === 365 ? "1y" : `${d}d`}</button>)}
      </div>
      <MultiSelect label="Campaigns" options={(opts.data || []).map((c) => ({ value: c.id, label: c.name }))} value={f.campaign_id} onChange={(v) => setF({ ...f, campaign_id: v })} />
    </div>
  );
}

export function defaultFilters(days = 30): Filters {
  return { date_from: new Date(Date.now() - (days - 1) * 86400000).toISOString().slice(0, 10), date_to: new Date().toISOString().slice(0, 10), campaign_id: [] };
}

export function KpiGrid({ f }: { f: Filters }) {
  const q = useWsQuery(["analytics", "overview", f], () => api.get<Overview>("/analytics/overview", f));
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} retry={q.refetch} />;
  const o = q.data!;
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
      <Stat label="Total Companies" value={fmtNum(o.total_companies)} icon={<Building2 className="h-4 w-4" />} />
      <Stat label="Total Contacts" value={fmtNum(o.total_contacts)} icon={<Users className="h-4 w-4" />} />
      <Stat label="Eligible Subscribers" value={fmtNum(o.eligible_subscribers)} hint={`${fmtPct(o.total_contacts ? (100 * o.eligible_subscribers) / o.total_contacts : 0)} of contacts`} icon={<ShieldCheck className="h-4 w-4" />} tone="green" />
      <Stat label="Total Campaigns" value={fmtNum(o.total_campaigns)} hint={`${fmtNum(o.campaigns_sent_in_period)} sent in period`} icon={<Send className="h-4 w-4" />} tone="violet" />
      <Stat label="Emails Sent" value={fmtNum(o.emails_sent)} icon={<Send className="h-4 w-4" />} tone="violet" />
      <Stat label="Emails Delivered" value={fmtNum(o.emails_delivered)} hint={o.emails_sent > 0 && o.emails_delivered === 0 ? "Confirmed via SES delivery events" : `${fmtPct(o.delivery_rate)} delivery rate`} icon={<MailCheck className="h-4 w-4" />} tone="green" />
      <Stat label="Bounce Rate" value={fmtPct(o.bounce_rate)} hint={`${fmtNum(o.bounces)} hard bounces`} icon={<Undo2 className="h-4 w-4" />} tone={o.bounce_rate > 5 ? "red" : "amber"} />
      <Stat label="Open Rate" value={fmtPct(o.open_rate)} hint={`${fmtNum(o.unique_opens)} unique opens`} icon={<MailOpen className="h-4 w-4" />} />
      <Stat label="Click Rate" value={fmtPct(o.click_rate)} hint={`CTOR ${fmtPct(o.click_to_open_rate)}`} icon={<MousePointerClick className="h-4 w-4" />} />
      <Stat label="Unsubscribe Rate" value={fmtPct(o.unsubscribe_rate)} hint={`${fmtNum(o.unsubscribes)} unsubscribes`} icon={<UserX className="h-4 w-4" />} tone="amber" />
    </div>
  );
}

export function TrendsCard({ f, interval = "day" }: { f: Filters; interval?: string }) {
  const q = useWsQuery(["analytics", "trends", f, interval], () => api.get<TrendRow[]>("/analytics/trends", { ...f, interval }));
  return (
    <Card title="Campaign performance trends">
      {q.isLoading ? <Loading /> : q.error ? <ErrorState error={q.error} /> : (
        <TrendChart data={q.data!} series={[{ key: "sent", label: "Sent", color: C.brand }, { key: "unique_opened", label: "Unique opens", color: C.accent }, { key: "unique_clicked", label: "Unique clicks", color: C.violet }, { key: "bounced", label: "Bounces", color: C.red }]} />
      )}
    </Card>
  );
}

export function RatesCard({ f }: { f: Filters }) {
  const q = useWsQuery(["analytics", "trends", f, "week"], () => api.get<TrendRow[]>("/analytics/trends", { ...f, interval: "week" }));
  return (
    <Card title="Open vs click rate (weekly)">
      {q.isLoading ? <Loading /> : q.error ? <ErrorState error={q.error} /> : (
        <GroupedBars data={q.data!.filter((r) => r.sent > 0).map((r) => ({ ...r, date: new Date(r.date).toLocaleDateString("en-GB", { day: "2-digit", month: "short" }) }))} xKey="date" percent series={[{ key: "open_rate", label: "Open rate", color: C.accent }, { key: "click_rate", label: "Click rate", color: C.violet }]} />
      )}
    </Card>
  );
}

export function DeliveryCard({ f }: { f: Filters }) {
  const q = useWsQuery(["analytics", "delivery", f], () => api.get<{ status: string; count: number }[]>("/analytics/delivery", f));
  const labels: Record<string, string> = { queued: "Queued", sending: "Sending", sent: "Sent (awaiting)", delivered: "Delivered", bounced: "Bounced", complained: "Complained", failed: "Failed", skipped_suppressed: "Skipped" };
  return (
    <Card title="Delivery performance">
      {q.isLoading ? <Loading /> : q.error ? <ErrorState error={q.error} /> : (
        <GroupedBars horizontal data={q.data!.filter((r) => r.count > 0).map((r) => ({ label: labels[r.status] || r.status, count: r.count }))} xKey="label" series={[{ key: "count", label: "Recipients", color: C.brand }]} height={240} />
      )}
    </Card>
  );
}

export function DistributionCard({ by, title }: { by: "industry" | "country" | "city" | "company_size" | "department"; title: string }) {
  const q = useWsQuery(["analytics", "distribution", by], () => api.get<{ label: string; count: number; share: number }[]>("/analytics/distribution", { by, limit: 10 }));
  return (
    <Card title={title}>
      {q.isLoading ? <Loading /> : q.error ? <ErrorState error={q.error} /> : (
        <GroupedBars horizontal data={q.data!} xKey="label" series={[{ key: "count", label: "Contacts", color: by === "country" ? C.accent : C.brand }]} height={Math.max(180, 30 * q.data!.length + 40)} />
      )}
    </Card>
  );
}

export function GrowthCard({ f }: { f: Filters }) {
  const q = useWsQuery(["analytics", "growth", f], () => api.get<Record<string, number | string>[]>("/analytics/audience-growth", f));
  return <Card title="Audience growth">{q.isLoading ? <Loading /> : q.error ? <ErrorState error={q.error} /> : <GrowthChart data={q.data!} />}</Card>;
}

type CampRow = { id: string; name: string; status: string; started_at: string; sent: number; delivered: number; open_rate: number; click_rate: number; bounce_rate: number; unsubscribe_rate: number; unique_opens: number; unique_clicks: number };
export function CampaignTable({ f, limit = 50 }: { f: Filters; limit?: number }) {
  const q = useWsQuery(["analytics", "campaigns", f, limit], () => api.get<CampRow[]>("/analytics/campaigns", { ...f, limit }));
  return (
    <Card title="Campaign-wise performance" bodyClass="p-0">
      {q.isLoading ? <Loading /> : q.error ? <ErrorState error={q.error} /> : q.data!.length === 0 ? <div className="p-6 text-center text-sm text-slate-500">No campaigns sent in this period.</div> : (
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead><tr>{["Campaign", "Status", "Sent", "Delivered", "Open rate", "Click rate", "Bounce", "Unsub", "Started"].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
            <tbody>
              {q.data!.map((c) => (
                <tr key={c.id} className="hover:bg-slate-50">
                  <td className="td font-medium"><Link className="text-brand-700 hover:underline" href={`/campaigns/${c.id}`}>{c.name}</Link></td>
                  <td className="td"><StatusBadge status={c.status} /></td>
                  <td className="td tabular-nums">{fmtNum(c.sent)}</td>
                  <td className="td tabular-nums">{fmtNum(c.delivered)}</td>
                  <td className="td tabular-nums">{fmtPct(c.open_rate)}</td>
                  <td className="td tabular-nums">{fmtPct(c.click_rate)}</td>
                  <td className="td tabular-nums">{fmtPct(c.bounce_rate)}</td>
                  <td className="td tabular-nums">{fmtPct(c.unsubscribe_rate)}</td>
                  <td className="td text-slate-500">{fmtDate(c.started_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
