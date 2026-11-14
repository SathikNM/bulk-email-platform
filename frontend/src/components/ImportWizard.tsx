"use client";

import { CheckCircle2, Download, FileSpreadsheet, Upload } from "lucide-react";
import { useEffect, useState } from "react";
import { api, download, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Modal, Progress, Toggle } from "./ui";

type Preview = { headers: string[]; rows: Record<string, string | null>[]; total_rows: number; suggested_mapping: Record<string, string | null>; fields: string[]; required: string[] };
type Job = { id: string; status: string; total_rows: number; inserted: number; updated: number; skipped: number; errors: { row: number; error: string }[]; options: Record<string, unknown> };

const LABEL: Record<string, string> = {
  name: "Company name", name_ar: "Name (Arabic)", company_name_ar: "Company name (Arabic)", company_name: "Company name", company_website: "Company website", full_name: "Full name",
  consent_source: "Consent source", consent_date: "Consent date (YYYY-MM-DD)", subscription_status: "Subscription status",
};
const label = (f: string) => LABEL[f] || f.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

export function ImportWizard({ entity, open, onClose }: { entity: "company" | "contact" | "suppression"; open: boolean; onClose: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [mapping, setMapping] = useState<Record<string, string | null>>({});
  const [updateExisting, setUpdateExisting] = useState(true);
  const [createTaxonomy, setCreateTaxonomy] = useState(true);
  const [lawfulBasis, setLawfulBasis] = useState("explicit_consent");
  const [job, setJob] = useState<Job | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const qc = useQueryClient();
  const { workspaceId } = useAuth();

  const reset = () => { setFile(null); setPreview(null); setMapping({}); setJob(null); setErr(null); };
  const close = () => { reset(); onClose(); };

  useEffect(() => {
    if (!job || job.status === "completed" || job.status === "failed") {
      if (job?.status === "completed") qc.invalidateQueries({ queryKey: [workspaceId] });
      return;
    }
    const t = setInterval(async () => setJob(await api.get<Job>(`/imports/${job.id}`)), 1200);
    return () => clearInterval(t);
  }, [job?.id, job?.status]);

  const upload = async (f: File) => {
    setFile(f); setErr(null); setBusy(true);
    try {
      const fd = new FormData();
      fd.append("entity", entity); fd.append("file", f);
      const p = await api.upload<Preview>("/imports/preview", fd);
      setPreview(p); setMapping(p.suggested_mapping);
    } catch (e) { setErr(errorMessage(e)); setFile(null); } finally { setBusy(false); }
  };

  const start = async () => {
    if (!file) return;
    setBusy(true); setErr(null);
    try {
      const fd = new FormData();
      fd.append("entity", entity); fd.append("file", file);
      fd.append("column_mapping", JSON.stringify(mapping));
      fd.append("options", JSON.stringify({ update_existing: updateExisting, create_missing_taxonomy: createTaxonomy, lawful_basis: lawfulBasis }));
      setJob(await api.upload<Job>("/imports", fd));
    } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  };

  const mapped = new Set(Object.values(mapping).filter(Boolean));
  const missing = (preview?.required || []).filter((r) => !mapped.has(r) && !(r === "name" && mapped.has("company_name")));
  const title = { company: "Import companies", contact: "Import contacts", suppression: "Import suppression list" }[entity];

  return (
    <Modal open={open} onClose={close} title={title} wide footer={
      job ? <Button variant="primary" onClick={close}>Done</Button> :
      preview ? <><Button onClick={reset}>Back</Button><Button variant="primary" onClick={start} loading={busy} disabled={missing.length > 0}>Import {preview.total_rows.toLocaleString()} rows</Button></> :
      <Button onClick={close}>Cancel</Button>
    }>
      {err && <div className="mb-3"><Alert tone="red">{err}</Alert></div>}
      {!preview && !job && (
        <div className="space-y-4">
          <label className="flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed border-slate-300 px-6 py-12 text-center hover:border-brand-400 hover:bg-brand-50/40">
            <Upload className="mb-2 h-7 w-7 text-slate-400" />
            <span className="text-sm font-medium text-slate-800">{busy ? "Reading file…" : "Choose a CSV or Excel file"}</span>
            <span className="mt-1 text-xs text-slate-500">.csv or .xlsx, up to 25 MB. The first row must contain column headers.</span>
            <input type="file" accept=".csv,.xlsx,.xlsm,.txt" className="hidden" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
          </label>
          <button className="inline-flex items-center gap-1.5 text-sm text-brand-700 hover:underline" onClick={() => download(`/imports/templates/${entity}.csv`)}><Download className="h-4 w-4" />Download a template</button>
          {entity === "contact" && <Alert tone="blue" title="Consent">Contacts are imported as <b>pending</b> and are not emailed unless you map a <b>consent source</b> and <b>consent date</b> for them. A publicly available business email address is not consent.</Alert>}
        </div>
      )}
      {preview && !job && (
        <div className="space-y-4">
          <div className="flex items-center gap-2 text-sm text-slate-600"><FileSpreadsheet className="h-4 w-4" />{file?.name} · {preview.total_rows.toLocaleString()} rows detected</div>
          <div className="overflow-hidden rounded-lg border border-slate-200">
            <table className="w-full">
              <thead><tr><th className="th">File column</th><th className="th">Sample</th><th className="th">Import as</th></tr></thead>
              <tbody>
                {preview.headers.map((h) => (
                  <tr key={h}>
                    <td className="td font-medium">{h}</td>
                    <td className="td max-w-[220px] truncate text-slate-500">{preview.rows.map((r) => r[h]).filter(Boolean).slice(0, 2).join(", ") || "—"}</td>
                    <td className="td w-64">
                      <select className="input py-1.5" value={mapping[h] || ""} onChange={(e) => setMapping({ ...mapping, [h]: e.target.value || null })}>
                        <option value="">— Skip column —</option>
                        {preview.fields.map((f) => <option key={f} value={f} disabled={mapped.has(f) && mapping[h] !== f}>{label(f)}{preview.required.includes(f) ? " *" : ""}</option>)}
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {missing.length > 0 && <Alert tone="red">Map the required column(s): {missing.map(label).join(", ")}</Alert>}
          {entity !== "suppression" && (
            <div className="flex flex-wrap gap-6">
              <Toggle checked={updateExisting} onChange={setUpdateExisting} label="Update existing records" />
              <Toggle checked={createTaxonomy} onChange={setCreateTaxonomy} label="Create missing industries, categories and tags" />
            </div>
          )}
          {entity === "contact" && mapped.has("consent_source") && (
            <div className="w-72">
              <label className="label">Lawful basis for mapped consent</label>
              <select className="input" value={lawfulBasis} onChange={(e) => setLawfulBasis(e.target.value)}>
                <option value="explicit_consent">Explicit consent</option>
                <option value="legitimate_interest">Legitimate interest</option>
                <option value="existing_customer">Existing customer</option>
                <option value="contract">Contract</option>
              </select>
            </div>
          )}
        </div>
      )}
      {job && (
        <div className="space-y-4">
          {job.status === "completed" ? (
            <div className="flex items-center gap-2 text-emerald-700"><CheckCircle2 className="h-5 w-5" /><span className="font-semibold">Import complete</span></div>
          ) : job.status === "failed" ? <Alert tone="red" title="Import failed">{job.errors[0]?.error}</Alert> : (
            <><div className="text-sm text-slate-600">Importing… {job.total_rows.toLocaleString()} rows processed</div><Progress value={50} /></>
          )}
          <div className="grid grid-cols-3 gap-3 text-center">
            {[["Inserted", job.inserted, "text-emerald-700"], ["Updated", job.updated, "text-brand-700"], ["Skipped", job.skipped, "text-amber-700"]].map(([l, v, c]) => (
              <div key={l as string} className="rounded-lg border border-slate-200 p-3"><div className={`text-2xl font-semibold ${c}`}>{(v as number).toLocaleString()}</div><div className="text-xs text-slate-500">{l}</div></div>
            ))}
          </div>
          {Boolean(job.options?.role_accounts) && <Alert tone="amber">{String(job.options.role_accounts)} role addresses (info@, sales@…) were imported. They often have lower engagement.</Alert>}
          {job.errors.length > 0 && job.status === "completed" && (
            <div>
              <div className="mb-2 flex items-center justify-between"><span className="text-sm font-medium">Rows with problems</span><Button size="sm" icon={<Download className="h-3.5 w-3.5" />} onClick={() => download(`/imports/${job.id}/errors.csv`)}>Download errors</Button></div>
              <div className="max-h-48 overflow-y-auto rounded-lg border border-slate-200 text-sm">
                {job.errors.slice(0, 50).map((e) => <div key={e.row} className="border-b border-slate-100 px-3 py-1.5"><span className="font-mono text-xs text-slate-500">Row {e.row}</span> · {e.error}</div>)}
              </div>
            </div>
          )}
        </div>
      )}
    </Modal>
  );
}
