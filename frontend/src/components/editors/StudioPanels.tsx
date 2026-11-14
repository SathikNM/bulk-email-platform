"use client";

import clsx from "clsx";
import { Monitor, Smartphone, Sparkles } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { api, errorMessage } from "@/lib/api";
import { useWsQuery } from "@/lib/hooks";
import type { Rendered, SendingAccount } from "@/lib/types";
import { Alert, Badge, Button, Field, Modal, Select } from "../ui";

export function VariablesMenu({ onInsert }: { onInsert: (token: string) => void }) {
  const q = useWsQuery(["variables"], () => api.get<{ contact: { name: string; token: string; sample: string | null }[]; system: { name: string; token: string }[]; fallback_syntax: string }>("/templates/variables"));
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <Button size="sm" onClick={() => setOpen(!open)}>{"{{ }}"} Variables</Button>
      {open && (
        <div className="absolute end-0 z-30 mt-1 w-72 rounded-lg border border-slate-200 bg-white p-2 shadow-lg" onMouseLeave={() => setOpen(false)}>
          <div className="px-2 pb-1 text-[11px] font-semibold uppercase text-slate-400">Contact</div>
          {q.data?.contact.map((v) => (
            <button key={v.name} className="flex w-full items-center justify-between rounded px-2 py-1.5 text-sm hover:bg-slate-50" onClick={() => { onInsert(v.token); setOpen(false); }}>
              <code className="text-brand-700">{v.token}</code><span className="text-xs text-slate-400">{v.sample}</span>
            </button>
          ))}
          <div className="px-2 pb-1 pt-2 text-[11px] font-semibold uppercase text-slate-400">System</div>
          {q.data?.system.map((v) => <button key={v.name} className="block w-full rounded px-2 py-1.5 text-start text-sm hover:bg-slate-50" onClick={() => { onInsert(v.token); setOpen(false); }}><code className="text-brand-700">{v.token}</code></button>)}
          <p className="mt-2 border-t border-slate-100 px-2 pt-2 text-xs text-slate-500">Fallback when empty: <code>{q.data?.fallback_syntax}</code></p>
        </div>
      )}
    </div>
  );
}

export function PreviewPane({ rendered, loading }: { rendered: Rendered | null; loading: boolean }) {
  const [device, setDevice] = useState<"desktop" | "mobile">("desktop");
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="inline-flex overflow-hidden rounded-lg border border-slate-300 text-sm">
          {(["desktop", "mobile"] as const).map((d) => (
            <button key={d} onClick={() => setDevice(d)} className={clsx("inline-flex items-center gap-1.5 px-3 py-1.5", device === d ? "bg-brand-700 text-white" : "bg-white text-slate-600 hover:bg-slate-50")}>
              {d === "desktop" ? <Monitor className="h-4 w-4" /> : <Smartphone className="h-4 w-4" />}{d === "desktop" ? "Desktop" : "Mobile"}
            </button>
          ))}
        </div>
        {loading && <span className="text-xs text-slate-400">Rendering…</span>}
      </div>
      {rendered && (
        <>
          <div className="rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm">
            <div className="text-xs text-slate-500">Subject (sample contact)</div>
            <div className="font-medium">{rendered.subject || <span className="text-red-600">No subject</span>}</div>
          </div>
          {rendered.warnings.map((w) => <Alert key={w} tone="amber">{w}</Alert>)}
          <div className={clsx("mx-auto overflow-hidden rounded-xl border border-slate-300 bg-slate-100 shadow-sm transition-all", device === "mobile" ? "w-[390px]" : "w-full")}>
            {device === "mobile" && <div className="flex justify-center bg-slate-800 py-1.5"><span className="h-1.5 w-16 rounded-full bg-slate-600" /></div>}
            <iframe title="Email preview" sandbox="allow-popups" srcDoc={rendered.html} className="h-[640px] w-full bg-white" />
          </div>
        </>
      )}
    </div>
  );
}

export function TestSendModal({ open, onClose, send }: { open: boolean; onClose: () => void; send: (to: string[], accountId: string | null) => Promise<{ results: { to: string; ok: boolean; error?: string }[]; from: string; provider: string }> }) {
  const accounts = useWsQuery(["sending-accounts"], () => api.get<SendingAccount[]>("/sending-accounts"), { enabled: open });
  const [to, setTo] = useState("");
  const [acct, setAcct] = useState("");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<{ results: { to: string; ok: boolean; error?: string }[]; from: string; provider: string } | null>(null);
  const run = async () => {
    setBusy(true); setRes(null);
    try { setRes(await send(to.split(/[,\s;]+/).filter(Boolean), acct || null)); }
    catch (e) { toast.error(errorMessage(e)); }
    finally { setBusy(false); }
  };
  return (
    <Modal open={open} onClose={() => { setRes(null); onClose(); }} title="Send a test email" footer={<><Button onClick={onClose}>Close</Button><Button variant="primary" loading={busy} disabled={!to.trim()} onClick={run}>Send test</Button></>}>
      <div className="space-y-4">
        <Field label="Recipients (up to 5)" hint="Separate addresses with commas. Test emails are personalised with sample data and prefixed with [TEST]."><input className="input" value={to} onChange={(e) => setTo(e.target.value)} placeholder="you@company.com" /></Field>
        <Field label="Sending account"><Select value={acct} onChange={setAcct} placeholder="Default account" options={(accounts.data || []).map((a) => ({ value: a.id, label: `${a.from_email} (${a.provider.toUpperCase()})` }))} /></Field>
        {accounts.data && accounts.data.length === 0 && <Alert tone="amber">No sending account is configured yet. Add one under Sending Accounts.</Alert>}
        {res && (
          <div className="space-y-1.5">
            {res.results.map((r) => <div key={r.to} className="flex items-center justify-between rounded-lg border border-slate-200 px-3 py-2 text-sm"><span>{r.to}</span>{r.ok ? <Badge tone="green">Accepted by {res.provider.toUpperCase()}</Badge> : <Badge tone="red">{r.error}</Badge>}</div>)}
            <p className="text-xs text-slate-500">“Accepted” means the provider took the message. Check the inbox to confirm delivery and rendering.</p>
          </div>
        )}
      </div>
    </Modal>
  );
}

export function AiPanel({ onSubject, onInsert }: { onSubject: (s: string) => void; onInsert: (html: string) => void }) {
  const status = useWsQuery(["ai-status"], () => api.get<{ enabled: boolean }>("/ai/status"));
  const [kind, setKind] = useState("subject");
  const [language, setLanguage] = useState("en");
  const [tone, setTone] = useState("professional");
  const [context, setContext] = useState("");
  const [out, setOut] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try { setOut((await api.post<{ suggestions: string[] }>("/ai/generate", { kind, language, tone, context })).suggestions); }
    catch (e) { toast.error(errorMessage(e)); }
    finally { setBusy(false); }
  };
  if (status.data && !status.data.enabled) {
    return <Alert tone="blue" title="AI assistant not configured">Ask your administrator to set <code>LLM_API_KEY</code> on the server to enable AI-written subject lines, emails and calls to action.</Alert>;
  }
  const isText = kind === "subject" || kind === "cta";
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2">
        <Field label="Generate"><Select value={kind} onChange={setKind} options={[{ value: "subject", label: "Subject lines" }, { value: "body", label: "Email content" }, { value: "marketing", label: "Marketing message" }, { value: "follow_up", label: "Follow-up" }, { value: "cta", label: "Calls to action" }]} /></Field>
        <Field label="Language"><Select value={language} onChange={setLanguage} options={[{ value: "en", label: "English" }, { value: "ar", label: "العربية" }]} /></Field>
      </div>
      <Field label="Tone"><Select value={tone} onChange={setTone} options={["professional", "friendly", "persuasive", "concise", "formal"].map((t) => ({ value: t, label: t[0].toUpperCase() + t.slice(1) }))} /></Field>
      <Field label="What is the email about?"><textarea className="input min-h-24" value={context} onChange={(e) => setContext(e.target.value)} placeholder="e.g. Invite CFOs of construction firms in Riyadh to a webinar on cash-flow forecasting on 3 December." /></Field>
      <Button variant="accent" icon={<Sparkles className="h-4 w-4" />} loading={busy} disabled={context.length < 10} onClick={run} className="w-full">Generate</Button>
      {out.map((s, i) => (
        <div key={i} className="rounded-lg border border-slate-200 p-3 text-sm" dir={language === "ar" ? "rtl" : "ltr"}>
          {isText ? <div>{s}</div> : <div className="prose-sm max-h-48 overflow-y-auto" dangerouslySetInnerHTML={{ __html: s.replace(/<script[\s\S]*?<\/script>/gi, "") }} />}
          <div className="mt-2 flex gap-2">
            {kind === "subject" && <Button size="sm" onClick={() => onSubject(s)}>Use as subject</Button>}
            {!isText && <Button size="sm" onClick={() => onInsert(s)}>Insert into email</Button>}
            {kind === "cta" && <Button size="sm" onClick={() => { navigator.clipboard.writeText(s); toast.success("Copied"); }}>Copy</Button>}
          </div>
        </div>
      ))}
    </div>
  );
}
