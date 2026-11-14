"use client";

import { Plus, Trash2, Upload } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { ImportWizard } from "@/components/ImportWizard";
import { Alert, Badge, Button, Card, Confirm, ErrorState, Field, Loading, Modal, PageHeader, Pagination, SearchInput, Select, Tabs } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate, titleCase } from "@/lib/format";
import { useAction, useWsQuery } from "@/lib/hooks";
import type { Page, Role } from "@/lib/types";

const ROLES: Role[] = ["owner", "admin", "marketer", "analyst", "viewer"];

function SettingsInner() {
  const { can } = useAuth();
  const [tab, setTab] = useState(useSearchParams().get("tab") || "workspace");
  const tabs = [{ value: "workspace", label: "Workspace" }, { value: "members", label: "Users & roles" }, { value: "suppressions", label: "Suppression list" }, ...(can("admin") ? [{ value: "audit", label: "Audit log" }] : []), { value: "account", label: "My account" }];
  return (
    <>
      <PageHeader title="Settings" subtitle="Workspace, team, compliance and account settings." />
      <Tabs value={tab} onChange={setTab} tabs={tabs} />
      {tab === "workspace" && <WorkspaceSettings />}
      {tab === "members" && <Members />}
      {tab === "suppressions" && <Suppressions />}
      {tab === "audit" && <Audit />}
      {tab === "account" && <div className="space-y-5"><Account /><TwoFactor /></div>}
    </>
  );
}

function WorkspaceSettings() {
  const { can } = useAuth();
  const q = useWsQuery(["workspace"], () => api.get<{ name: string; legal_address: string | null; default_locale: string; timezone: string; compliance_settings: Record<string, unknown> }>("/workspace"));
  const [f, setF] = useState<Record<string, string>>({});
  useEffect(() => { if (q.data) setF({ name: q.data.name, legal_address: q.data.legal_address || "", default_locale: q.data.default_locale, timezone: q.data.timezone, regimes: String((q.data.compliance_settings?.regimes as string[] | undefined)?.join(", ") || "") }); }, [q.data]);
  const save = useAction(() => api.patch("/workspace", { name: f.name, legal_address: f.legal_address || null, default_locale: f.default_locale, timezone: f.timezone, compliance_settings: { regimes: f.regimes.split(",").map((s) => s.trim()).filter(Boolean) } }), { success: "Workspace saved", invalidate: [["workspace"]] });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} />;
  return (
    <Card className="max-w-2xl"><div className="space-y-4">
      <Field label="Workspace name"><input className="input" disabled={!can("admin")} value={f.name || ""} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
      <Field label="Sender postal address *" hint="Shown in every email footer. Anti-spam laws (CAN-SPAM, PDPL, GDPR/PECR) require a valid physical address."><textarea className="input" disabled={!can("admin")} value={f.legal_address || ""} onChange={(e) => setF({ ...f, legal_address: e.target.value })} /></Field>
      <div className="grid grid-cols-2 gap-4">
        <Field label="Default language"><Select value={f.default_locale} disabled={!can("admin")} onChange={(v) => setF({ ...f, default_locale: v })} options={[{ value: "en", label: "English" }, { value: "ar", label: "العربية" }]} /></Field>
        <Field label="Time zone"><input className="input" disabled={!can("admin")} value={f.timezone || ""} onChange={(e) => setF({ ...f, timezone: e.target.value })} /></Field>
      </div>
      <Field label="Applicable privacy regimes" hint="For your records, e.g. KSA PDPL, UAE PDPL, GDPR, CAN-SPAM"><input className="input" disabled={!can("admin")} value={f.regimes || ""} onChange={(e) => setF({ ...f, regimes: e.target.value })} /></Field>
      {can("admin") && <Button variant="primary" loading={save.isPending} onClick={() => save.mutate(undefined)}>Save</Button>}
    </div></Card>
  );
}

type Member = { user_id: string; email: string; full_name: string; role: Role; last_login_at: string | null; joined_at: string };
function Members() {
  const { can, me } = useAuth();
  const q = useWsQuery(["members"], () => api.get<Member[]>("/members"));
  const [add, setAdd] = useState(false);
  const [f, setF] = useState({ email: "", full_name: "", role: "marketer", password: "" });
  const [del, setDel] = useState<Member | null>(null);
  const create = useAction(() => api.post("/members", { ...f, password: f.password || undefined }), { success: "Member added", invalidate: [["members"]], onSuccess: () => { setAdd(false); setF({ email: "", full_name: "", role: "marketer", password: "" }); } });
  const change = useAction((v: { id: string; role: string }) => api.patch(`/members/${v.id}`, { role: v.role }), { success: "Role updated", invalidate: [["members"]] });
  const remove = useAction(() => api.del(`/members/${del!.user_id}`), { success: "Member removed", invalidate: [["members"]], onSuccess: () => setDel(null) });
  return (
    <>
      <div className="mb-4 flex items-center justify-between">
        <p className="text-sm text-slate-500">Owner: everything · Admin: approve/send, accounts, suppressions · Marketer: data, segments, templates, drafts · Analyst: reports and exports · Viewer: read only.</p>
        {can("admin") && <Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => setAdd(true)}>Add member</Button>}
      </div>
      <Card bodyClass="p-0">{q.isLoading ? <Loading /> : q.error ? <ErrorState error={q.error} /> : (
        <table className="w-full"><thead><tr><th className="th">Name</th><th className="th">Role</th><th className="th">Last sign-in</th><th className="th" /></tr></thead>
          <tbody>{q.data!.map((m) => (
            <tr key={m.user_id}><td className="td"><div className="font-medium">{m.full_name}</div><div className="text-xs text-slate-400">{m.email}</div></td>
              <td className="td w-48">{can("admin") && m.user_id !== me?.id ? <Select value={m.role} onChange={(role) => change.mutate({ id: m.user_id, role })} options={ROLES.map((r) => ({ value: r, label: titleCase(r) }))} /> : <Badge tone="brand">{titleCase(m.role)}</Badge>}</td>
              <td className="td text-sm text-slate-500">{fmtDate(m.last_login_at, true)}</td>
              <td className="td text-end">{can("admin") && m.user_id !== me?.id && <Button size="sm" variant="ghost" onClick={() => setDel(m)} aria-label="Remove"><Trash2 className="h-3.5 w-3.5 text-red-600" /></Button>}</td></tr>
          ))}</tbody></table>
      )}</Card>
      <Modal open={add} onClose={() => setAdd(false)} title="Add team member" footer={<><Button onClick={() => setAdd(false)}>Cancel</Button><Button variant="primary" loading={create.isPending} onClick={() => create.mutate(undefined)}>Add</Button></>}>
        <div className="space-y-3">
          <Field label="Email"><input className="input" type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
          <Field label="Full name"><input className="input" value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} /></Field>
          <Field label="Role"><Select value={f.role} onChange={(role) => setF({ ...f, role })} options={ROLES.map((r) => ({ value: r, label: titleCase(r) }))} /></Field>
          <Field label="Initial password" hint="Required for new users: 10+ characters mixing upper/lower case, digits or symbols. Existing users keep their password."><input className="input" type="password" autoComplete="new-password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></Field>
        </div>
      </Modal>
      <Confirm open={!!del} onClose={() => setDel(null)} onConfirm={() => remove.mutate(undefined)} loading={remove.isPending} danger title="Remove member" confirmLabel="Remove" message={`Remove ${del?.full_name} from this workspace?`} />
    </>
  );
}

type Sup = { id: string; email: string; reason: string; source: string | null; created_at: string };
function Suppressions() {
  const { can } = useAuth();
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const list = useWsQuery(["suppressions", q, page], () => api.get<Page<Sup>>("/suppressions", { q, page, page_size: 50 }));
  const [add, setAdd] = useState(false);
  const [imp, setImp] = useState(false);
  const [f, setF] = useState({ email: "", reason: "manual" });
  const [rm, setRm] = useState<Sup | null>(null);
  const [why, setWhy] = useState("");
  const create = useAction(() => api.post("/suppressions", f), { success: "Address suppressed", invalidate: [["suppressions"], ["contacts"]], onSuccess: () => { setAdd(false); setF({ email: "", reason: "manual" }); } });
  const remove = useAction(() => api.del(`/suppressions/${rm!.id}`, { justification: why }), { success: "Suppression removed. The contact stays unsubscribed until new consent is recorded.", invalidate: [["suppressions"]], onSuccess: () => { setRm(null); setWhy(""); } });
  return (
    <>
      <div className="mb-4"><Alert tone="blue">Suppressed addresses are never emailed, regardless of segment or manual selection. Hard bounces, spam complaints and unsubscribes are added automatically.</Alert></div>
      <div className="card">
        <div className="flex flex-wrap gap-2 border-b border-slate-100 p-3">
          <SearchInput value={q} onChange={(v) => { setQ(v); setPage(1); }} placeholder="Search email…" />
          {can("admin") && <div className="ms-auto flex gap-2"><Button icon={<Upload className="h-4 w-4" />} onClick={() => setImp(true)}>Import</Button><Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => setAdd(true)}>Add address</Button></div>}
        </div>
        {list.isLoading ? <Loading /> : list.error ? <ErrorState error={list.error} /> : (
          <>
            <table className="w-full"><thead><tr><th className="th">Email</th><th className="th">Reason</th><th className="th">Source</th><th className="th">Added</th><th className="th" /></tr></thead>
              <tbody>{list.data!.items.map((s) => (
                <tr key={s.id}><td className="td">{s.email}</td><td className="td"><Badge tone={s.reason === "complaint" || s.reason === "hard_bounce" ? "red" : "gray"}>{titleCase(s.reason)}</Badge></td><td className="td text-xs text-slate-500">{s.source}</td><td className="td text-xs">{fmtDate(s.created_at, true)}</td>
                  <td className="td text-end">{can("admin") && s.reason !== "complaint" && <Button size="sm" variant="ghost" onClick={() => setRm(s)}>Remove</Button>}</td></tr>
              ))}</tbody></table>
            {list.data!.items.length === 0 && <div className="p-6 text-center text-sm text-slate-500">No suppressed addresses.</div>}
            <Pagination page={page} pageSize={50} total={list.data!.total} onPage={setPage} />
          </>
        )}
      </div>
      <Modal open={add} onClose={() => setAdd(false)} title="Suppress an address" footer={<><Button onClick={() => setAdd(false)}>Cancel</Button><Button variant="primary" loading={create.isPending} onClick={() => create.mutate(undefined)}>Suppress</Button></>}>
        <div className="space-y-3"><Field label="Email"><input className="input" type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
          <Field label="Reason"><Select value={f.reason} onChange={(reason) => setF({ ...f, reason })} options={["manual", "unsubscribe", "hard_bounce", "complaint", "role_account", "invalid"].map((r) => ({ value: r, label: titleCase(r) }))} /></Field></div>
      </Modal>
      <Modal open={!!rm} onClose={() => setRm(null)} title="Remove suppression" footer={<><Button onClick={() => setRm(null)}>Cancel</Button><Button variant="danger" loading={remove.isPending} disabled={why.length < 5} onClick={() => remove.mutate(undefined)}>Remove</Button></>}>
        <div className="space-y-3"><p className="text-sm text-slate-600">Removing <b>{rm?.email}</b> does not re-subscribe it. Record why (kept in the audit log).</p><Field label="Justification"><textarea className="input" value={why} onChange={(e) => setWhy(e.target.value)} /></Field></div>
      </Modal>
      <ImportWizard entity="suppression" open={imp} onClose={() => setImp(false)} />
    </>
  );
}

type Log = { id: number; action: string; entity_type: string; entity_id: string | null; user_name: string | null; ip: string | null; created_at: string; after: Record<string, unknown> | null };
function Audit() {
  const [page, setPage] = useState(1);
  const [entity, setEntity] = useState("");
  const q = useWsQuery(["audit", page, entity], () => api.get<Page<Log>>("/audit-logs", { page, page_size: 50, entity_type: entity || undefined }));
  return (
    <div className="card">
      <div className="border-b border-slate-100 p-3"><Select className="w-56" value={entity} onChange={(v) => { setEntity(v); setPage(1); }} placeholder="All entities" options={["campaign", "company", "contact", "segment", "template", "sending_account", "suppression", "workspace_member", "workspace"].map((e) => ({ value: e, label: titleCase(e) }))} /></div>
      {q.isLoading ? <Loading /> : q.error ? <ErrorState error={q.error} /> : (
        <>
          <table className="w-full"><thead><tr><th className="th">When</th><th className="th">User</th><th className="th">Action</th><th className="th">Entity</th><th className="th">IP</th></tr></thead>
            <tbody>{q.data!.items.map((l) => <tr key={l.id}><td className="td text-xs">{fmtDate(l.created_at, true)}</td><td className="td">{l.user_name || "System"}</td><td className="td"><Badge tone="brand">{titleCase(l.action)}</Badge></td><td className="td text-xs">{titleCase(l.entity_type)} <span className="font-mono text-slate-400">{l.entity_id?.slice(0, 8)}</span></td><td className="td font-mono text-xs text-slate-500">{l.ip}</td></tr>)}</tbody></table>
          <Pagination page={page} pageSize={50} total={q.data!.total} onPage={setPage} />
        </>
      )}
    </div>
  );
}

function Account() {
  const { me } = useAuth();
  const [f, setF] = useState({ current_password: "", new_password: "", confirm: "" });
  const save = useAction(() => api.post("/auth/change-password", { current_password: f.current_password, new_password: f.new_password }), { success: "Password changed. Other sessions were signed out.", onSuccess: () => setF({ current_password: "", new_password: "", confirm: "" }) });
  return (
    <Card className="max-w-lg" title={`${me?.full_name} · ${me?.email}`}><div className="space-y-3">
      <Field label="Current password"><input className="input" type="password" autoComplete="current-password" value={f.current_password} onChange={(e) => setF({ ...f, current_password: e.target.value })} /></Field>
      <Field label="New password" hint="At least 10 characters, mixing upper/lower case, digits or symbols."><input className="input" type="password" autoComplete="new-password" value={f.new_password} onChange={(e) => setF({ ...f, new_password: e.target.value })} /></Field>
      <Field label="Confirm new password" error={f.confirm && f.confirm !== f.new_password ? "Passwords do not match" : undefined}><input className="input" type="password" autoComplete="new-password" value={f.confirm} onChange={(e) => setF({ ...f, confirm: e.target.value })} /></Field>
      <Button variant="primary" loading={save.isPending} disabled={!f.current_password || f.new_password.length < 10 || f.new_password !== f.confirm} onClick={() => save.mutate(undefined)}>Change password</Button>
    </div></Card>
  );
}

function TwoFactor() {
  const { me, reload } = useAuth();
  const [setup, setSetup] = useState<{ secret: string; qr: string } | null>(null);
  const [code, setCode] = useState("");
  const [pw, setPw] = useState("");
  const start = useAction(async () => {
    const r = await api.post<{ secret: string; otpauth_uri: string }>("/auth/2fa/setup");
    const QR = await import("qrcode");
    setSetup({ secret: r.secret, qr: await QR.toDataURL(r.otpauth_uri, { margin: 1, width: 200 }) });
    setCode("");
  });
  const enable = useAction(() => api.post("/auth/2fa/enable", { code }), { success: "Two-factor sign-in is on", onSuccess: () => { setSetup(null); setCode(""); reload(); } });
  const disable = useAction(() => api.post("/auth/2fa/disable", { code, password: pw }), { success: "Two-factor sign-in turned off", onSuccess: () => { setCode(""); setPw(""); reload(); } });
  const codeInput = <Field label="6-digit code"><input className="input tracking-[0.3em]" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} /></Field>;
  return (
    <Card className="max-w-lg" title="Two-factor sign-in">
      {me?.totp_enabled ? (
        <div className="space-y-3">
          <Alert tone="green">On: signing in needs your password and a code from your authenticator app.</Alert>
          <Field label="Current password"><input className="input" type="password" autoComplete="current-password" value={pw} onChange={(e) => setPw(e.target.value)} /></Field>
          {codeInput}
          <Button variant="danger" loading={disable.isPending} disabled={!pw || code.length !== 6} onClick={() => disable.mutate(undefined)}>Turn off</Button>
        </div>
      ) : setup ? (
        <div className="space-y-3">
          <p className="text-sm text-slate-600">Scan this with Google Authenticator, Microsoft Authenticator or 1Password, then enter the code it shows.</p>
          <img src={setup.qr} alt="Authenticator QR code" className="h-48 w-48 rounded border border-slate-200" />
          <p className="break-all text-xs text-slate-500">Can&apos;t scan? Enter this key manually: <span className="font-mono">{setup.secret}</span></p>
          {codeInput}
          <div className="flex gap-2"><Button onClick={() => setSetup(null)}>Cancel</Button><Button variant="primary" loading={enable.isPending} disabled={code.length !== 6} onClick={() => enable.mutate(undefined)}>Turn on</Button></div>
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-sm text-slate-600">Protect this account with a code from your phone in addition to your password.</p>
          <Button variant="primary" loading={start.isPending} onClick={() => start.mutate(undefined)}>Set up two-factor sign-in</Button>
        </div>
      )}
    </Card>
  );
}

export default function SettingsPage() {
  return <Suspense><SettingsInner /></Suspense>;
}
