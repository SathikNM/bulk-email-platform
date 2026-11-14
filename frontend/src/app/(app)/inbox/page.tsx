"use client";

import clsx from "clsx";
import { AlertTriangle, ArrowLeft, Inbox as InboxIcon, Reply, Send } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Alert, Badge, Button, Empty, ErrorState, Loading, PageHeader, Pagination, SearchInput, Tabs } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate } from "@/lib/format";
import { useAction, useWsQuery } from "@/lib/hooks";
import type { Page } from "@/lib/types";

type Msg = {
  id: string; thread_id: string; direction: "in" | "out"; kind: string; status: string; from_addr: string;
  from_name: string | null; to_addr: string; subject: string; preview: string; is_read: boolean; error: string | null;
  campaign_id: string | null; contact_id: string | null; created_at: string; body_text?: string | null; body_html?: string | null;
};
type Thread = { thread_id: string; subject: string; contact: { id: string; email: string; name: string | null } | null; campaign: { id: string; name: string } | null; messages: Msg[] };

const KIND: Record<string, string> = { test: "Test", campaign: "Campaign", reply: "Reply", inbound: "Reply", auto_reply: "Auto-reply" };

export default function InboxPage() {
  const { can } = useAuth();
  const [folder, setFolder] = useState("inbox");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState<string | null>(null);
  const summary = useWsQuery(["mailbox-summary"], () => api.get<{ unread: number; reply_capture: boolean; inbound_domain: string | null }>("/mailbox/summary"), { refetchInterval: 30000 });
  const list = useWsQuery(["mailbox", folder, q, page], () => api.get<Page<Msg>>("/mailbox", { folder, q: q || undefined, page }), { refetchInterval: 30000 });
  useEffect(() => { setPage(1); setOpen(null); }, [folder, q]);
  const unread = summary.data?.unread ?? 0;

  return (
    <>
      <PageHeader title="Inbox" subtitle="Every email the platform sends, and the replies it receives, in one place." />
      {summary.data && !summary.data.reply_capture && (
        <div className="mb-4"><Alert tone="amber" title="Replies are not captured yet">Replies currently go to each sending account&apos;s own mailbox (e.g. Outlook). They will appear here once the platform runs on the mail server with reply capture turned on. The Sent folder already works.</Alert></div>
      )}
      <Tabs value={folder} onChange={setFolder} tabs={[
        { value: "inbox", label: <span className="inline-flex items-center gap-1.5">Inbox{unread > 0 && <Badge tone="brand">{unread}</Badge>}</span> },
        { value: "sent", label: "Sent" },
        { value: "failed", label: "Failed" },
      ]} />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <div className={clsx("card overflow-hidden", open && "hidden lg:block")}>
          <div className="border-b border-slate-100 p-3"><SearchInput value={q} onChange={setQ} placeholder="Search subject, sender or recipient…" /></div>
          {list.isLoading ? <Loading /> : list.error ? <ErrorState error={list.error} /> : list.data!.items.length === 0 ? (
            <Empty icon={folder === "inbox" ? <InboxIcon className="h-6 w-6" /> : <Send className="h-6 w-6" />} title={folder === "inbox" ? "No replies yet" : folder === "sent" ? "Nothing sent yet" : "No failed emails"} />
          ) : (
            <>
              <ul className="divide-y divide-slate-100">
                {list.data!.items.map((m) => (
                  <li key={m.id}>
                    <button onClick={() => setOpen(m.thread_id)} className={clsx("block w-full px-4 py-3 text-start hover:bg-slate-50", open === m.thread_id && "bg-brand-50")}>
                      <div className="flex items-center justify-between gap-2">
                        <span className={clsx("truncate text-sm", !m.is_read ? "font-semibold text-slate-900" : "text-slate-700")}>
                          {m.direction === "in" ? (m.from_name || m.from_addr) : `To: ${m.to_addr}`}
                        </span>
                        <span className="shrink-0 text-xs text-slate-400">{fmtDate(m.created_at, true)}</span>
                      </div>
                      <div className={clsx("truncate text-sm", !m.is_read ? "font-medium" : "text-slate-600")}>{m.subject || "(no subject)"}</div>
                      <div className="flex items-center gap-2">
                        <span className="truncate text-xs text-slate-400">{m.preview}</span>
                        {m.status === "failed" && <Badge tone="red">Failed</Badge>}
                        {m.direction === "out" && <Badge tone="gray" className="shrink-0">{KIND[m.kind] ?? m.kind}</Badge>}
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
              <div className="border-t border-slate-100 p-3"><Pagination page={page} pageSize={50} total={list.data!.total} onPage={setPage} /></div>
            </>
          )}
        </div>
        <div className={clsx(!open && "hidden lg:block")}>
          {open ? <ThreadView id={open} canReply={can("marketer")} onBack={() => setOpen(null)} onRead={() => { summary.refetch(); list.refetch(); }} /> : (
            <div className="card"><Empty title="Select a conversation" hint="Pick an email on the left to read the whole conversation and reply." /></div>
          )}
        </div>
      </div>
    </>
  );
}

function ThreadView({ id, canReply, onBack, onRead }: { id: string; canReply: boolean; onBack: () => void; onRead: () => void }) {
  const t = useWsQuery(["mailbox-thread", id], () => api.get<Thread>(`/mailbox/threads/${id}`));
  const [body, setBody] = useState("");
  useEffect(() => { if (t.data) onRead(); }, [t.data?.thread_id]);
  const last = t.data?.messages[t.data.messages.length - 1];
  const target = t.data ? ([...t.data.messages].reverse().find((m) => m.direction === "in") ?? last) : undefined;
  const send = useAction(() => api.post(`/mailbox/${target!.id}/reply`, { body }), { success: "Reply sent", invalidate: [["mailbox-thread", id], ["mailbox"]], onSuccess: () => setBody("") });
  if (t.isLoading) return <div className="card"><Loading /></div>;
  if (t.error) return <div className="card"><ErrorState error={t.error} /></div>;
  const th = t.data!;
  const to = target ? (target.direction === "in" ? target.from_addr : target.to_addr) : "";
  return (
    <div className="card">
      <div className="border-b border-slate-100 p-4">
        <button className="mb-2 inline-flex items-center gap-1 text-xs text-slate-500 lg:hidden" onClick={onBack}><ArrowLeft className="h-3.5 w-3.5" />Back</button>
        <h2 className="text-base font-semibold">{th.subject || "(no subject)"}</h2>
        <div className="mt-1 flex flex-wrap gap-3 text-xs text-slate-500">
          {th.contact && <Link className="hover:text-brand-700" href={`/contacts/${th.contact.id}`}>Contact: {th.contact.name || th.contact.email}</Link>}
          {th.campaign && <Link className="hover:text-brand-700" href={`/campaigns/${th.campaign.id}`}>Campaign: {th.campaign.name}</Link>}
        </div>
      </div>
      <div className="space-y-3 p-4">
        {th.messages.map((m) => (
          <div key={m.id} className={clsx("rounded-lg border p-3", m.direction === "in" ? "border-brand-100 bg-brand-50/40" : "border-slate-200")}>
            <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
              <span><b className="text-slate-800">{m.from_name || m.from_addr}</b> <span className="text-slate-500">&lt;{m.from_addr}&gt; → {m.to_addr}</span></span>
              <span className="text-slate-400">{fmtDate(m.created_at, true)}</span>
            </div>
            {m.status === "failed" && <div className="mt-2 flex items-start gap-1.5 text-xs text-red-700"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />Not delivered: {m.error}</div>}
            {m.body_html ? (
              <iframe title="Message" sandbox="" className="mt-2 h-72 w-full rounded border border-slate-100 bg-white" srcDoc={m.body_html} />
            ) : (
              <pre className="mt-2 whitespace-pre-wrap font-sans text-sm text-slate-700">{m.body_text || (m.kind === "campaign" ? "Campaign email: open the campaign to see its content." : "")}</pre>
            )}
          </div>
        ))}
      </div>
      {canReply && target && (
        <div className="border-t border-slate-100 p-4">
          <div className="mb-2 text-xs text-slate-500">Reply to <b>{to}</b></div>
          <textarea className="input min-h-28" placeholder="Write your reply…" value={body} onChange={(e) => setBody(e.target.value)} />
          <div className="mt-2 flex justify-end"><Button variant="primary" icon={<Reply className="h-4 w-4" />} loading={send.isPending} disabled={!body.trim()} onClick={() => send.mutate(undefined)}>Send reply</Button></div>
        </div>
      )}
    </div>
  );
}
