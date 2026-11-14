"use client";

import clsx from "clsx";
import { Check, ChevronLeft, ChevronRight, Send } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { CompanyPicker } from "@/components/ContactForm";
import { type ComposerHandle, EmailComposer } from "@/components/editors/EmailComposer";
import { TestSendModal } from "@/components/editors/StudioPanels";
import { Alert, Badge, Button, Card, Field, Loading, Select, StatusBadge } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtNum, fullName, toLocalInput } from "@/lib/format";
import { useWsQuery } from "@/lib/hooks";
import type { Campaign, Contact, Page, Segment, SendingAccount, Template, Validation } from "@/lib/types";

const STEPS = ["Details", "Audience", "Content", "Review & validate", "Test", "Approve & send"];

function Wizard() {
  const router = useRouter();
  const params = useSearchParams();
  const { can } = useAuth();
  const [step, setStep] = useState(0);
  const [c, setC] = useState<Campaign | null>(null);
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("");
  const [segmentId, setSegmentId] = useState("");
  const [manual, setManual] = useState<Contact[]>([]);
  const [templateId, setTemplateId] = useState("");
  const [customise, setCustomise] = useState(false);
  const [accountId, setAccountId] = useState("");
  const [validation, setValidation] = useState<Validation | null>(null);
  const [test, setTest] = useState(false);
  const [when, setWhen] = useState<"now" | "later">("now");
  const [at, setAt] = useState(() => toLocalInput(new Date(Date.now() + 3600_000)));
  const composer = useRef<ComposerHandle>(null);
  const segments = useWsQuery(["segments", "all"], () => api.get<Page<Segment>>("/segments", { page_size: 200 }));
  const templates = useWsQuery(["templates", "all"], () => api.get<Page<Template>>("/templates", { page_size: 200 }));
  const accounts = useWsQuery(["sending-accounts"], () => api.get<SendingAccount[]>("/sending-accounts"));
  const tpl = useWsQuery(["template", templateId], () => api.get<Template>(`/templates/${templateId}`), { enabled: !!templateId });

  useEffect(() => {
    const id = params.get("id");
    if (!id) return;
    api.get<Campaign>(`/campaigns/${id}`).then(async (x) => {
      setC(x); setName(x.name); setSegmentId(x.segment_id || ""); setTemplateId(x.template_id || ""); setAccountId(x.sending_account_id || ""); setCustomise(!!x.content_html);
      if (x.manual_contact_ids.length) setManual(await Promise.all(x.manual_contact_ids.slice(0, 50).map((cid) => api.get<Contact>(`/contacts/${cid}`))));
    });
  }, []);

  const saveDraft = async (extra: Record<string, unknown> = {}) => {
    const body = { name: name || "Untitled campaign", segment_id: segmentId || null, manual_contact_ids: manual.map((m) => m.id), template_id: templateId || null, sending_account_id: accountId || null, ...extra };
    const out = c ? await api.patch<Campaign>(`/campaigns/${c.id}`, body) : await api.post<Campaign>("/campaigns", body);
    setC(out);
    if (!c) router.replace(`/campaigns/new?id=${out.id}`);
    return out;
  };

  const next = async () => {
    setBusy(true);
    try {
      if (step === 0 && !name.trim()) throw new Error("Enter a campaign name");
      if (step === 1 && !segmentId && manual.length === 0) throw new Error("Select a segment or at least one contact");
      if (step === 2) {
        if (!templateId) throw new Error("Select a template");
        const comp = composer.current?.collect();
        const t = tpl.data!;
        const saved = await saveDraft(customise && comp
          ? { subject: comp.subject, preheader: comp.preheader, content_html: comp.html, direction: comp.direction }
          : { subject: t.subject, preheader: t.preheader, content_html: null, direction: null });
        setValidation(await api.post<Validation>(`/campaigns/${saved.id}/validate`));
      } else if (c?.status === "draft" || !c) await saveDraft();
      if (step === 3 && validation && !validation.ok) throw new Error("Fix the validation errors before continuing");
      setStep(step + 1);
    } catch (e) { toast.error(errorMessage(e)); } finally { setBusy(false); }
  };

  const launch = async () => {
    if (!c) return;
    setBusy(true);
    try {
      if (!c.is_approved) await api.post(`/campaigns/${c.id}/approve`, {});
      if (when === "now") await api.post(`/campaigns/${c.id}/send`);
      else await api.post(`/campaigns/${c.id}/schedule`, { scheduled_at: new Date(at).toISOString() });
      toast.success(when === "now" ? "Campaign is sending" : "Campaign scheduled");
      router.push(`/campaigns/${c.id}`);
    } catch (e) { toast.error(errorMessage(e)); } finally { setBusy(false); }
  };

  const seg = segments.data?.items.find((s) => s.id === segmentId);
  return (
    <>
      <h1 className="mb-1 text-xl font-semibold">{c ? `Edit campaign: ${c.name}` : "Create campaign"}</h1>
      <p className="mb-6 text-sm text-slate-500">Every recipient is re-checked against unsubscribe and suppression lists at send time.</p>
      <ol className="mb-6 flex flex-wrap gap-2">
        {STEPS.map((s, i) => (
          <li key={s} className={clsx("flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium", i === step ? "border-brand-700 bg-brand-700 text-white" : i < step ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-slate-200 bg-white text-slate-500")}>
            <span className={clsx("flex h-5 w-5 items-center justify-center rounded-full text-[11px]", i === step ? "bg-white/20" : i < step ? "bg-emerald-600 text-white" : "bg-slate-100")}>{i < step ? <Check className="h-3 w-3" /> : i + 1}</span>{s}
          </li>
        ))}
      </ol>

      {step === 0 && (
        <Card className="max-w-2xl"><div className="space-y-4">
          <Field label="Campaign name *"><input className="input" autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Q4 CFO advisory webinar invite" /></Field>
          <Field label="Sending account" hint="Messages are sent from this verified address."><Select value={accountId} onChange={setAccountId} placeholder="Default account" options={(accounts.data || []).map((a) => ({ value: a.id, label: `${a.from_name ? a.from_name + " · " : ""}${a.from_email}${a.verification_status !== "verified" ? " (not verified)" : ""}` }))} /></Field>
          {accounts.data?.length === 0 && <Alert tone="amber">No sending account yet. Add and verify one under Sending Accounts before you can send.</Alert>}
        </div></Card>
      )}

      {step === 1 && (
        <div className="grid max-w-5xl gap-5 lg:grid-cols-2">
          <Card title="Audience segment">
            <Select value={segmentId} onChange={setSegmentId} placeholder="No segment" options={(segments.data?.items || []).map((s) => ({ value: s.id, label: `${s.name} · ${fmtNum(s.cached_eligible_count)} eligible` }))} />
            {seg && <p className="mt-2 text-sm text-slate-500">{seg.description}</p>}
            <a href="/segments/new" target="_blank" className="mt-3 inline-block text-sm text-brand-700 hover:underline">Create a new segment ↗</a>
          </Card>
          <Card title="Individual contacts (optional)"><ContactAdder value={manual} onChange={setManual} /></Card>
        </div>
      )}

      {step === 2 && (
        <div className="space-y-4">
          <Card className="max-w-3xl"><div className="grid gap-4 sm:grid-cols-2">
            <Field label="Email template *"><Select value={templateId} onChange={(v) => { setTemplateId(v); setCustomise(false); }} placeholder="Select…" options={(templates.data?.items || []).map((t) => ({ value: t.id, label: `${t.name}${t.is_draft ? " (draft)" : ""}` }))} /></Field>
            <div className="flex items-end"><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={customise} disabled={!templateId} onChange={(e) => setCustomise(e.target.checked)} />Personalise content for this campaign</label></div>
          </div></Card>
          {templateId && tpl.data && (customise ? (
            <EmailComposer ref={composer} initial={{ subject: c?.subject || tpl.data.subject || "", preheader: c?.preheader || tpl.data.preheader || "", editor_type: tpl.data.editor_type === "drag_drop" ? "html" : tpl.data.editor_type, html: c?.content_html || tpl.data.html || "", design_json: null, direction: c?.direction || tpl.data.direction }} />
          ) : (
            <Card title={`Subject: ${tpl.data.subject || "(none)"}`}><iframe title="Template" sandbox="" srcDoc={tpl.data.html || ""} className="h-[520px] w-full rounded-lg border border-slate-200" /></Card>
          ))}
        </div>
      )}

      {step === 3 && validation && (
        <div className="grid max-w-5xl gap-5 lg:grid-cols-[1fr_320px]">
          <div className="space-y-3">
            {validation.ok ? <Alert tone="green" title="Ready to send">All checks passed.</Alert> : <Alert tone="red" title="Fix before sending">{validation.errors.join("\n")}</Alert>}
            {validation.warnings.map((w) => <Alert key={w} tone="amber">{w}</Alert>)}
            <Card title="Summary"><dl className="space-y-2 text-sm">
              {[["Campaign", c?.name], ["From", validation.sending_account?.from], ["Subject", c?.subject], ["Segment", seg?.name || "—"], ["Individual contacts", manual.length], ["Template", tpl.data?.name]].map(([k, v]) => <div key={String(k)} className="flex justify-between gap-4"><dt className="text-slate-500">{k}</dt><dd className="text-end font-medium" dir="auto">{v ?? "—"}</dd></div>)}
            </dl></Card>
          </div>
          <div className="card p-4">
            <div className="text-xs font-medium text-slate-500">Recipients who will receive this email</div>
            <div className="mt-1 text-4xl font-semibold text-emerald-700">{fmtNum(validation.audience.eligible)}</div>
            <div className="mt-1 text-sm text-slate-500">of {fmtNum(validation.audience.total_matched)} matched</div>
            <div className="mt-4 space-y-1.5 border-t border-slate-100 pt-3 text-xs text-slate-600">
              {[["Not subscribed / pending", validation.audience.excluded.not_subscribed], ["Suppressed", validation.audience.excluded.suppressed], ["Invalid email", validation.audience.excluded.invalid_email], ["Duplicate emails removed", validation.audience.duplicates_removed]].map(([l, v]) => Number(v) > 0 && <div key={l as string} className="flex justify-between"><span>{l}</span><span>{fmtNum(Number(v))}</span></div>)}
            </div>
          </div>
        </div>
      )}

      {step === 4 && c && (
        <Card className="max-w-2xl" title="Send a test email">
          <p className="text-sm text-slate-600">Check the email in real inboxes (Gmail, Outlook, mobile) before approving.</p>
          <Button className="mt-4" icon={<Send className="h-4 w-4" />} onClick={() => setTest(true)}>Send test email</Button>
          <TestSendModal open={test} onClose={() => setTest(false)} send={(to, acct) => api.post(`/campaigns/${c.id}/test-send`, { to, sending_account_id: acct })} />
        </Card>
      )}

      {step === 5 && c && (
        <Card className="max-w-2xl" title="Approve and send">
          {!can("admin") ? <Alert tone="amber">Approval requires an Admin or Owner. Your draft is saved; ask an admin to approve <b>{c.name}</b> from Campaign History.</Alert> : (
            <div className="space-y-4">
              <p className="text-sm text-slate-600">Approving freezes the content. You will send to <b>{fmtNum(validation?.audience.eligible)}</b> recipient(s) from <b>{validation?.sending_account?.from}</b>.</p>
              <div className="flex gap-4 text-sm">
                <label className="flex items-center gap-2"><input type="radio" checked={when === "now"} onChange={() => setWhen("now")} />Send immediately</label>
                <label className="flex items-center gap-2"><input type="radio" checked={when === "later"} onChange={() => setWhen("later")} />Schedule</label>
              </div>
              {when === "later" && <Field label="Send at (your local time)"><input type="datetime-local" className="input w-64" value={at} onChange={(e) => setAt(e.target.value)} /></Field>}
              <Button variant="primary" icon={<Send className="h-4 w-4" />} loading={busy} onClick={launch}>{when === "now" ? "Approve & send now" : "Approve & schedule"}</Button>
            </div>
          )}
        </Card>
      )}

      <div className="mt-6 flex max-w-5xl justify-between">
        <Button icon={<ChevronLeft className="h-4 w-4" />} disabled={step === 0 || busy} onClick={() => setStep(step - 1)}>Back</Button>
        {step < 5 && <Button variant="primary" loading={busy} onClick={next}>{step === 2 ? "Save & validate" : "Continue"}<ChevronRight className="h-4 w-4" /></Button>}
      </div>
    </>
  );
}

function ContactAdder({ value, onChange }: { value: Contact[]; onChange: (v: Contact[]) => void }) {
  const [companyId, setCompanyId] = useState("");
  const [q, setQ] = useState("");
  const list = useWsQuery(["contacts", "picker", q, companyId], () => api.get<Page<Contact>>("/contacts", { q, company_id: companyId ? [companyId] : undefined, page_size: 8 }));
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2">
        <CompanyPicker value={companyId} onChange={(id) => setCompanyId(id)} />
        <input className="input" placeholder="Search contacts…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <div className="max-h-56 overflow-y-auto rounded-lg border border-slate-200">
        {list.isLoading ? <Loading className="py-4" /> : list.data?.items.map((p) => {
          const picked = value.some((v) => v.id === p.id);
          return (
            <button key={p.id} type="button" onClick={() => onChange(picked ? value.filter((v) => v.id !== p.id) : [...value, p])} className={clsx("flex w-full items-center justify-between border-b border-slate-100 px-3 py-2 text-start text-sm", picked ? "bg-brand-50" : "hover:bg-slate-50")}>
              <span><span className="font-medium">{fullName(p)}</span> <span className="text-slate-400">{p.email}</span></span>
              <span className="flex items-center gap-2"><StatusBadge status={p.subscription_status} />{picked && <Check className="h-4 w-4 text-brand-700" />}</span>
            </button>
          );
        })}
      </div>
      {value.length > 0 && <div className="flex flex-wrap gap-1">{value.map((p) => <Badge key={p.id} tone="brand">{p.email}</Badge>)}</div>}
      <p className="text-xs text-slate-500">Contacts who are not subscribed, are suppressed or lack consent are excluded automatically.</p>
    </div>
  );
}

export default function NewCampaignPage() {
  return <Suspense><Wizard /></Suspense>;
}
