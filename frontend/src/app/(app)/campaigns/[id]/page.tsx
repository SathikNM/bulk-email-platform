"use client";

import { ArrowLeft, Ban, Copy, Pause, Play, Send } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { C, GroupedBars } from "@/components/charts";
import { Alert, Button, Card, Confirm, ErrorState, Loading, MultiSelect, PageHeader, Pagination, Progress, SearchInput, Stat, StatusBadge, Tabs } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate, fmtNum, fmtPct, titleCase } from "@/lib/format";
import { useAction, useWsQuery } from "@/lib/hooks";
import type { Campaign, Page } from "@/lib/types";

type Rec = { id: string; email: string; name: string | null; company_name: string | null; status: string; attempts: number; last_error: string | null; sent_at: string | null; delivered_at: string | null; first_opened_at: string | null; first_clicked_at: string | null };
type Ev = { id: number; event_type: string; email: string | null; url: string | null; is_machine: boolean; occurred_at: string };
const REC_STATUS = ["queued", "sending", "sent", "delivered", "bounced", "complained", "failed", "skipped_suppressed"];

export default function CampaignDetail() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { can } = useAuth();
  const [tab, setTab] = useState("overview");
  const [confirm, setConfirm] = useState<"cancel" | "send" | null>(null);
  const q = useWsQuery(["campaign", id], () => api.get<Campaign>(`/campaigns/${id}`), { refetchInterval: 4000 });
  const opts = (msg: string) => ({ success: msg, invalidate: [["campaign", id], ["campaigns"]], onSuccess: () => setConfirm(null) });
  const pause = useAction(() => api.post<Campaign>(`/campaigns/${id}/pause`), opts("Campaign paused"));
  const resume = useAction(() => api.post<Campaign>(`/campaigns/${id}/resume`), opts("Campaign resumed"));
  const cancel = useAction(() => api.post<Campaign>(`/campaigns/${id}/cancel`), opts("Campaign cancelled"));
  const sendNow = useAction(() => api.post<Campaign>(`/campaigns/${id}/send`), opts("Sending started"));
  const dup = useAction(() => api.post<Campaign>(`/campaigns/${id}/duplicate`), { success: "Duplicated as draft", invalidate: [["campaigns"]], onSuccess: (c) => router.push(`/campaigns/new?id=${c.id}`) });

  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} retry={q.refetch} />;
  const c = q.data!;
  const s = c.stats;
  const canPause = ["scheduled", "processing", "sending"].includes(c.status);
  return (
    <>
      <Link href="/campaigns" className="mb-3 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800"><ArrowLeft className="h-4 w-4" />Campaign history</Link>
      <PageHeader title={c.name} subtitle={<span className="flex flex-wrap items-center gap-2"><StatusBadge status={c.status} /><span dir="auto">{c.subject}</span></span>} actions={<>
        {can("marketer") && <Button icon={<Copy className="h-4 w-4" />} onClick={() => dup.mutate(undefined)}>Duplicate</Button>}
        {can("admin") && canPause && <Button icon={<Pause className="h-4 w-4" />} loading={pause.isPending} onClick={() => pause.mutate(undefined)}>Pause</Button>}
        {can("admin") && c.status === "paused" && <Button variant="primary" icon={<Play className="h-4 w-4" />} loading={resume.isPending} onClick={() => resume.mutate(undefined)}>Resume</Button>}
        {can("admin") && c.status === "scheduled" && <Button variant="primary" icon={<Send className="h-4 w-4" />} onClick={() => setConfirm("send")}>Send now</Button>}
        {can("admin") && ["draft", "scheduled", "paused", "sending", "processing"].includes(c.status) && <Button icon={<Ban className="h-4 w-4" />} onClick={() => setConfirm("cancel")}>Cancel</Button>}
      </>} />
      {c.last_error && <div className="mb-4"><Alert tone={c.status === "paused" || c.status === "failed" ? "red" : "amber"}>{c.last_error}</Alert></div>}
      {c.status === "scheduled" && <div className="mb-4"><Alert tone="blue">Scheduled for {fmtDate(c.scheduled_at, true)}.</Alert></div>}
      {s.recipients > 0 && (
        <div className="card mb-5 p-4">
          <div className="mb-2 flex justify-between text-sm"><span className="font-medium">Sending progress</span><span className="tabular-nums text-slate-500">{fmtNum(s.recipients - s.queued)} / {fmtNum(s.recipients)} processed</span></div>
          <Progress value={s.progress} tone={c.status === "completed" ? "green" : "brand"} />
        </div>
      )}
      <Tabs value={tab} onChange={setTab} tabs={[{ value: "overview", label: "Overview" }, { value: "recipients", label: `Recipients (${fmtNum(s.recipients)})` }, { value: "links", label: "Links" }, { value: "log", label: "Sending log" }, { value: "content", label: "Content" }]} />
      {tab === "overview" && (
        <div className="space-y-5">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
            <Stat label="Recipients" value={fmtNum(s.recipients)} />
            <Stat label="Sent" value={fmtNum(s.sent)} />
            <Stat label="Delivered" value={fmtNum(s.delivered)} hint={s.sent > 0 && s.delivered === 0 ? "Needs SES delivery events" : fmtPct(s.delivery_rate)} tone="green" />
            <Stat label="Opens" value={fmtNum(s.unique_opens)} hint={fmtPct(s.open_rate)} />
            <Stat label="Clicks" value={fmtNum(s.unique_clicks)} hint={fmtPct(s.click_rate)} tone="violet" />
            <Stat label="Bounced" value={fmtNum(s.bounced)} hint={fmtPct(s.bounce_rate)} tone="red" />
            <Stat label="Unsubscribed" value={fmtNum(s.unsubscribes)} hint={fmtPct(s.unsubscribe_rate)} tone="amber" />
            <Stat label="Failed / skipped" value={`${fmtNum(s.failed)} / ${fmtNum(s.skipped)}`} tone="amber" />
          </div>
          <div className="grid gap-5 lg:grid-cols-2">
            <Card title="Engagement funnel"><GroupedBars data={[{ k: "Sent", v: s.sent }, { k: "Delivered", v: s.delivered }, { k: "Opened", v: s.unique_opens }, { k: "Clicked", v: s.unique_clicks }]} xKey="k" series={[{ key: "v", label: "Recipients", color: C.brand }]} height={240} /></Card>
            <Card title="Details"><dl className="space-y-2 text-sm">
              {[["From", c.sending_account], ["Segment", c.segment_name], ["Individual contacts", c.manual_contact_count || "—"], ["Template", c.template_name], ["Approved", fmtDate(c.approved_at, true)], ["Started", fmtDate(c.started_at, true)], ["Completed", fmtDate(c.completed_at, true)]].map(([k, v]) => <div key={String(k)} className="flex justify-between"><dt className="text-slate-500">{k}</dt><dd className="font-medium">{v || "—"}</dd></div>)}
            </dl></Card>
          </div>
        </div>
      )}
      {tab === "recipients" && <Recipients id={id} />}
      {tab === "links" && <Links id={id} />}
      {tab === "log" && <Log id={id} />}
      {tab === "content" && <Card><iframe title="Sent content" sandbox="" srcDoc={(c as Campaign & { html_snapshot?: string }).html_snapshot?.replace(/\{\{__L:[^}]+\}\}/g, "#") || c.content_html || "<p style='font-family:sans-serif;color:#64748b'>Content is frozen when the campaign is approved.</p>"} className="h-[640px] w-full rounded-lg border border-slate-200" /></Card>}
      <Confirm open={confirm === "cancel"} onClose={() => setConfirm(null)} onConfirm={() => cancel.mutate(undefined)} loading={cancel.isPending} danger title="Cancel campaign" confirmLabel="Cancel campaign" message="Unsent recipients will not receive this email. This cannot be undone; duplicate the campaign to send again." />
      <Confirm open={confirm === "send"} onClose={() => setConfirm(null)} onConfirm={() => sendNow.mutate(undefined)} loading={sendNow.isPending} title="Send now" confirmLabel="Send now" message="Start sending immediately instead of waiting for the scheduled time?" />
    </>
  );
}

function Recipients({ id }: { id: string }) {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState<string[]>([]);
  const [page, setPage] = useState(1);
  const r = useWsQuery(["campaign-recipients", id, q, status, page], () => api.get<Page<Rec>>(`/campaigns/${id}/recipients`, { q, status, page, page_size: 50 }));
  return (
    <div className="card">
      <div className="flex flex-wrap gap-2 border-b border-slate-100 p-3"><SearchInput value={q} onChange={(v) => { setQ(v); setPage(1); }} placeholder="Search email…" /><MultiSelect label="Status" options={REC_STATUS.map((s) => ({ value: s, label: titleCase(s === "skipped_suppressed" ? "skipped" : s) }))} value={status} onChange={(v) => { setStatus(v); setPage(1); }} /></div>
      {r.isLoading ? <Loading /> : r.error ? <ErrorState error={r.error} /> : (
        <>
          <div className="overflow-x-auto"><table className="w-full">
            <thead><tr>{["Recipient", "Company", "Status", "Sent", "Opened", "Clicked", "Detail"].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
            <tbody>{r.data!.items.map((x) => (
              <tr key={x.id}><td className="td">{x.email}<div className="text-xs text-slate-400">{x.name}</div></td><td className="td">{x.company_name}</td><td className="td"><StatusBadge status={x.status} /></td><td className="td text-xs">{fmtDate(x.sent_at, true)}</td><td className="td text-xs">{fmtDate(x.first_opened_at, true)}</td><td className="td text-xs">{fmtDate(x.first_clicked_at, true)}</td><td className="td max-w-xs truncate text-xs text-slate-500" title={x.last_error || ""}>{x.last_error || (x.attempts > 1 ? `${x.attempts} attempts` : "")}</td></tr>
            ))}</tbody>
          </table></div>
          <Pagination page={page} pageSize={50} total={r.data!.total} onPage={setPage} />
        </>
      )}
    </div>
  );
}

function Links({ id }: { id: string }) {
  const r = useWsQuery(["campaign-links", id], () => api.get<{ url: string; clicks: number; unique_clicks: number }[]>(`/campaigns/${id}/links`));
  return (
    <Card bodyClass="p-0">{r.isLoading ? <Loading /> : !r.data?.length ? <div className="p-6 text-center text-sm text-slate-500">No tracked links (links are registered at approval).</div> : (
      <table className="w-full"><thead><tr><th className="th">Link</th><th className="th">Unique clicks</th><th className="th">Total clicks</th></tr></thead>
        <tbody>{r.data.map((l) => <tr key={l.url}><td className="td max-w-xl truncate"><a href={l.url} target="_blank" rel="noopener noreferrer" className="text-brand-700 hover:underline">{l.url}</a></td><td className="td tabular-nums">{l.unique_clicks}</td><td className="td tabular-nums">{l.clicks}</td></tr>)}</tbody></table>
    )}</Card>
  );
}

function Log({ id }: { id: string }) {
  const [page, setPage] = useState(1);
  const [types, setTypes] = useState<string[]>([]);
  const r = useWsQuery(["campaign-log", id, page, types], () => api.get<Page<Ev>>(`/campaigns/${id}/logs`, { page, page_size: 100, event_type: types }));
  const ET = ["send", "delivery", "bounce_hard", "bounce_soft", "complaint", "open", "click", "unsubscribe", "reject"];
  return (
    <div className="card">
      <div className="border-b border-slate-100 p-3"><MultiSelect label="Event type" options={ET.map((e) => ({ value: e, label: titleCase(e) }))} value={types} onChange={(v) => { setTypes(v); setPage(1); }} /></div>
      {r.isLoading ? <Loading /> : r.error ? <ErrorState error={r.error} /> : (
        <>
          <table className="w-full"><thead><tr><th className="th">Time</th><th className="th">Event</th><th className="th">Recipient</th><th className="th">Detail</th></tr></thead>
            <tbody>{r.data!.items.map((e) => <tr key={e.id}><td className="td text-xs">{fmtDate(e.occurred_at, true)}</td><td className="td">{titleCase(e.event_type)}{e.is_machine && <span className="ms-1 text-xs text-slate-400">(automated)</span>}</td><td className="td">{e.email}</td><td className="td max-w-md truncate text-xs text-slate-500">{e.url}</td></tr>)}</tbody></table>
          <Pagination page={page} pageSize={100} total={r.data!.total} onPage={setPage} />
        </>
      )}
    </div>
  );
}
