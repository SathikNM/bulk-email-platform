"use client";

import { CheckCircle2, Gauge, Pencil, Plus, ShieldCheck, Star, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Alert, Badge, Button, Card, Confirm, Drawer, Empty, ErrorState, Field, Loading, Modal, PageHeader, Select, StatusBadge } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtNum } from "@/lib/format";
import { useAction, useWsQuery } from "@/lib/hooks";
import type { SendingAccount } from "@/lib/types";

type Dns = { type: string; name: string; value: string; purpose: string }[];
const REGIONS = ["me-central-1", "me-south-1", "eu-west-1", "eu-central-1", "eu-west-2", "us-east-1", "us-west-2", "ap-south-1", "ap-southeast-1"];

export default function SendingAccountsPage() {
  const { can } = useAuth();
  const list = useWsQuery(["sending-accounts"], () => api.get<SendingAccount[]>("/sending-accounts"));
  const [edit, setEdit] = useState<SendingAccount | null | undefined>(undefined);
  const [dns, setDns] = useState<{ a: SendingAccount; records: Dns; ok: boolean; error?: string } | null>(null);
  const [quota, setQuota] = useState<Record<string, unknown> | null>(null);
  const [del, setDel] = useState<SendingAccount | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const remove = useAction(() => api.del(`/sending-accounts/${del!.id}`), { success: "Account removed", invalidate: [["sending-accounts"]], onSuccess: () => setDel(null) });
  const makeDefault = useAction((id: string) => api.patch(`/sending-accounts/${id}`, { is_default: true }), { success: "Default account updated", invalidate: [["sending-accounts"]] });
  const verify = async (a: SendingAccount) => {
    setBusy(a.id);
    try {
      const r = await api.post<{ ok: boolean; error?: string; dns_records: Dns }>(`/sending-accounts/${a.id}/verify`);
      setDns({ a, records: r.dns_records || [], ok: r.ok, error: r.error });
      r.ok ? toast.success("Account verified") : toast.warning(r.error || "Not verified yet");
      list.refetch();
    } catch (e) { toast.error(errorMessage(e)); } finally { setBusy(null); }
  };
  const showQuota = async (a: SendingAccount) => {
    try { setQuota({ name: a.name, ...(await api.get<Record<string, unknown>>(`/sending-accounts/${a.id}/quota`)) }); }
    catch (e) { toast.error(errorMessage(e)); }
  };
  return (
    <>
      <PageHeader title="Sending Accounts" subtitle="Amazon SES or SMTP accounts used to deliver campaigns. Credentials are encrypted and never shown again." actions={can("admin") && <Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => setEdit(null)}>Add account</Button>} />
      <div className="mb-5"><Alert tone="blue" title="Deliverability checklist">Verify your sending domain, publish SPF, DKIM and DMARC records, and request SES production access before sending at volume. Keep bounces under 5% and complaints under 0.1%.</Alert></div>
      {list.isLoading ? <Loading /> : list.error ? <ErrorState error={list.error} /> : list.data!.length === 0 ? (
        <div className="card"><Empty title="No sending account yet" hint="Add an Amazon SES account (recommended) or any SMTP relay." action={can("admin") && <Button variant="primary" onClick={() => setEdit(null)}>Add account</Button>} /></div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {list.data!.map((a) => (
            <Card key={a.id} title={<span className="flex items-center gap-2">{a.name}{a.is_default && <Badge tone="brand"><Star className="h-3 w-3" />Default</Badge>}</span>} actions={<StatusBadge status={a.verification_status} />}>
              <dl className="grid grid-cols-2 gap-y-2 text-sm">
                <dt className="text-slate-500">Provider</dt><dd className="font-medium">{a.provider === "ses" ? `Amazon SES (${a.region})` : "SMTP"}</dd>
                <dt className="text-slate-500">From</dt><dd className="font-medium">{a.from_name ? `${a.from_name} <${a.from_email}>` : a.from_email}</dd>
                <dt className="text-slate-500">Domain</dt><dd className="font-medium">{a.domain}</dd>
                <dt className="text-slate-500">Limits</dt><dd className="font-medium">{a.max_per_second}/sec · {fmtNum(a.max_per_day)}/day</dd>
                <dt className="text-slate-500">Credentials</dt><dd className="font-medium">{a.credentials_set ? Object.entries(a.credentials_hint).map(([k, v]) => `${k}: ${v}`).join(", ") : a.provider === "ses" ? "Server IAM role" : "Not set"}</dd>
              </dl>
              {can("admin") && (
                <div className="mt-4 flex flex-wrap gap-2 border-t border-slate-100 pt-3">
                  <Button size="sm" icon={<ShieldCheck className="h-3.5 w-3.5" />} loading={busy === a.id} onClick={() => verify(a)}>Verify & DNS</Button>
                  {a.provider === "ses" && <Button size="sm" icon={<Gauge className="h-3.5 w-3.5" />} onClick={() => showQuota(a)}>Quota</Button>}
                  {!a.is_default && <Button size="sm" icon={<Star className="h-3.5 w-3.5" />} onClick={() => makeDefault.mutate(a.id)}>Make default</Button>}
                  <Button size="sm" icon={<Pencil className="h-3.5 w-3.5" />} onClick={() => setEdit(a)}>Edit</Button>
                  <Button size="sm" variant="ghost" icon={<Trash2 className="h-3.5 w-3.5 text-red-600" />} onClick={() => setDel(a)}>Remove</Button>
                </div>
              )}
            </Card>
          ))}
        </div>
      )}
      <AccountForm open={edit !== undefined} account={edit} onClose={() => setEdit(undefined)} />
      <Modal open={!!dns} onClose={() => setDns(null)} wide title={`DNS records for ${dns?.a.domain}`}>
        {dns && <div className="space-y-3">
          {dns.ok ? <Alert tone="green" title="Verified"><span className="inline-flex items-center gap-1"><CheckCircle2 className="h-4 w-4" />This account can send.</span></Alert> : <Alert tone="amber" title="Not verified yet">{dns.error || "Publish the records below at your DNS provider, wait for propagation, then verify again."}</Alert>}
          <table className="w-full text-sm"><thead><tr><th className="th">Type</th><th className="th">Name</th><th className="th">Value</th></tr></thead>
            <tbody>{dns.records.map((r) => <tr key={r.name + r.value}><td className="td font-mono text-xs">{r.type}</td><td className="td break-all font-mono text-xs">{r.name}<div className="mt-1 font-sans text-[11px] text-slate-500">{r.purpose}</div></td><td className="td break-all font-mono text-xs"><button className="text-start hover:text-brand-700" onClick={() => { navigator.clipboard.writeText(r.value); toast.success("Copied"); }}>{r.value}</button></td></tr>)}</tbody></table>
        </div>}
      </Modal>
      <Modal open={!!quota} onClose={() => setQuota(null)} title={`SES quota · ${quota?.name}`}>
        {quota && <dl className="grid grid-cols-2 gap-y-2 text-sm">{Object.entries(quota).filter(([k]) => k !== "name").map(([k, v]) => <div key={k} className="contents"><dt className="text-slate-500">{k.replace(/_/g, " ")}</dt><dd className="font-medium">{String(v ?? "—")}</dd></div>)}</dl>}
      </Modal>
      <Confirm open={!!del} onClose={() => setDel(null)} onConfirm={() => remove.mutate(undefined)} loading={remove.isPending} danger title="Remove sending account" confirmLabel="Remove" message={`Remove ${del?.from_email}? Accounts already used by campaigns cannot be removed.`} />
    </>
  );
}

function AccountForm({ open, account, onClose }: { open: boolean; account?: SendingAccount | null; onClose: () => void }) {
  const [f, setF] = useState<Record<string, string>>({});
  const [creds, setCreds] = useState<Record<string, string>>({});
  const [init, setInit] = useState<string | null>(null);
  const key = account?.id ?? "new";
  if (open && init !== key) {
    setInit(key);
    setF({ name: account?.name || "", provider: account?.provider || "ses", from_email: account?.from_email || "", from_name: account?.from_name || "", reply_to: account?.reply_to || "", region: account?.region || "me-central-1", configuration_set: account?.configuration_set || "", max_per_second: String(account?.max_per_second ?? 10), max_per_day: String(account?.max_per_day ?? 50000) });
    setCreds(account?.provider === "smtp" ? { host: account.credentials_hint.host || "", port: String(account.credentials_hint.port || "587"), username: account.credentials_hint.username || "", security: account.credentials_hint.security || "starttls" } : account?.provider === "ses" ? { access_key_id: account.credentials_hint.access_key_id || "" } : { port: "587", security: "starttls" });
  }
  if (!open && init !== null) setInit(null);
  const save = useAction(() => {
    const isSes = f.provider === "ses";
    const c = isSes ? (creds.access_key_id ? { access_key_id: creds.access_key_id, secret_access_key: creds.secret_access_key } : undefined) : { host: creds.host, port: Number(creds.port), username: creds.username || undefined, password: creds.password || undefined, security: creds.security };
    const body: Record<string, unknown> = { name: f.name, from_name: f.from_name || null, reply_to: f.reply_to || null, region: isSes ? f.region : null, configuration_set: f.configuration_set || null, max_per_second: Number(f.max_per_second), max_per_day: Number(f.max_per_day) };
    if (c && Object.values(c).some(Boolean)) body.credentials = c; // server merges: blank fields keep saved values
    return account ? api.patch(`/sending-accounts/${account.id}`, body) : api.post("/sending-accounts", { ...body, provider: f.provider, from_email: f.from_email });
  }, { success: "Sending account saved", invalidate: [["sending-accounts"]], onSuccess: onClose });
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });
  const setc = (k: string) => (e: React.ChangeEvent<HTMLInputElement>) => setCreds({ ...creds, [k]: e.target.value });
  const isSes = f.provider === "ses";
  return (
    <Drawer open={open} onClose={onClose} title={account ? "Edit sending account" : "Add sending account"} footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={save.isPending} onClick={() => save.mutate(undefined)} disabled={!f.name || !f.from_email}>Save</Button></>}>
      <div className="grid grid-cols-2 gap-4">
        <Field label="Account name *" className="col-span-2"><input className="input" value={f.name || ""} onChange={set("name")} placeholder="e.g. Marketing (SES Bahrain)" /></Field>
        <Field label="Provider"><Select value={f.provider} onChange={(v) => setF({ ...f, provider: v })} disabled={!!account} options={[{ value: "ses", label: "Amazon SES" }, { value: "smtp", label: "SMTP relay" }]} /></Field>
        {isSes && <Field label="AWS region"><Select value={f.region} onChange={(v) => setF({ ...f, region: v })} options={REGIONS.map((r) => ({ value: r, label: r }))} /></Field>}
        <Field label="From email *"><input className="input" type="email" disabled={!!account} value={f.from_email || ""} onChange={set("from_email")} placeholder="news@yourdomain.com" /></Field>
        <Field label="From name"><input className="input" value={f.from_name || ""} onChange={set("from_name")} /></Field>
        <Field label="Reply-to"><input className="input" type="email" value={f.reply_to || ""} onChange={set("reply_to")} /></Field>
        {isSes && <Field label="Configuration set" hint="Publishes bounce/complaint/delivery events to SNS"><input className="input" value={f.configuration_set || ""} onChange={set("configuration_set")} /></Field>}
        <Field label="Max emails per second"><input className="input" type="number" min={1} value={f.max_per_second || ""} onChange={set("max_per_second")} /></Field>
        <Field label="Max emails per day"><input className="input" type="number" min={1} value={f.max_per_day || ""} onChange={set("max_per_day")} /></Field>
        <fieldset className="col-span-2 rounded-lg border border-slate-200 p-3">
          <legend className="px-1 text-xs font-semibold text-slate-600">Credentials {account && "(leave blank to keep current)"}</legend>
          {isSes ? (
            <div className="grid grid-cols-2 gap-3">
              <Field label="Access key ID"><input className="input" autoComplete="off" value={creds.access_key_id || ""} onChange={setc("access_key_id")} /></Field>
              <Field label="Secret access key"><input className="input" type="password" name="aws-secret" autoComplete="new-password" data-lpignore="true" readOnly onFocus={(e) => e.currentTarget.removeAttribute("readonly")} value={creds.secret_access_key || ""} onChange={setc("secret_access_key")} /></Field>
              <p className="col-span-2 text-xs text-slate-500">Leave empty to use the server&apos;s IAM role. The key needs ses:SendRawEmail, ses:GetEmailIdentity, ses:CreateEmailIdentity and ses:GetAccount.</p>
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-3">
              <Field label="SMTP host"><input className="input" value={creds.host || ""} onChange={setc("host")} /></Field>
              <Field label="Port"><input className="input" type="number" value={creds.port || ""} onChange={setc("port")} /></Field>
              <Field label="Username"><input className="input" autoComplete="off" value={creds.username || ""} onChange={setc("username")} /></Field>
              <Field label="Password" hint={account?.credentials_hint.password ? "Leave blank to keep the saved password" : "Gmail: use a 16-letter app password"}><input className="input" type="password" name="smtp-app-secret" autoComplete="new-password" data-lpignore="true" readOnly onFocus={(e) => e.currentTarget.removeAttribute("readonly")} value={creds.password || ""} onChange={setc("password")} /></Field>
              <Field label="Security" className="col-span-2"><Select value={creds.security} onChange={(v) => setCreds({ ...creds, security: v })} options={[{ value: "starttls", label: "STARTTLS (587)" }, { value: "ssl", label: "SSL/TLS (465)" }, { value: "none", label: "None (local testing only)" }]} /></Field>
            </div>
          )}
        </fieldset>
      </div>
    </Drawer>
  );
}
