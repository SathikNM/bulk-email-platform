"use client";

import { ArrowLeft, Copy, Save, Send } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { type ComposerHandle, EmailComposer } from "@/components/editors/EmailComposer";
import { TestSendModal } from "@/components/editors/StudioPanels";
import { Button, ErrorState, Loading, Toggle } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useAction, useWsQuery } from "@/lib/hooks";
import type { Template } from "@/lib/types";

export default function TemplateStudio() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { can } = useAuth();
  const q = useWsQuery(["template", id], () => api.get<Template>(`/templates/${id}`));
  const composer = useRef<ComposerHandle>(null);
  const [name, setName] = useState<string | null>(null);
  const [ready, setReady] = useState<boolean | null>(null);
  const [test, setTest] = useState(false);

  const save = useAction(async () => {
    const c = composer.current!.collect();
    return api.patch<Template>(`/templates/${id}`, { name: name ?? q.data!.name, subject: c.subject, preheader: c.preheader, editor_type: c.editor_type, html: c.html, design_json: c.design_json, direction: c.direction, locale: c.direction === "rtl" ? "ar" : "en", is_draft: !(ready ?? !q.data!.is_draft) });
  }, { success: "Template saved", invalidate: [["templates"], ["template", id]] });
  const dup = useAction(() => api.post<Template>(`/templates/${id}/duplicate`), { success: "Duplicated", invalidate: [["templates"]], onSuccess: (t) => router.push(`/templates/${t.id}`) });

  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} retry={q.refetch} />;
  const t = q.data!;
  return (
    <>
      <Link href="/templates" className="mb-3 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800"><ArrowLeft className="h-4 w-4" />Templates</Link>
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <input className="min-w-0 flex-1 rounded-lg border border-transparent bg-transparent px-2 py-1 text-xl font-semibold hover:border-slate-200 focus:border-brand-400 focus:outline-none" value={name ?? t.name} onChange={(e) => setName(e.target.value)} aria-label="Template name" />
        <Toggle checked={ready ?? !t.is_draft} onChange={setReady} label="Ready to use" />
        <Button icon={<Send className="h-4 w-4" />} onClick={async () => { await save.mutateAsync(undefined); setTest(true); }}>Send test</Button>
        {can("marketer") && <Button icon={<Copy className="h-4 w-4" />} onClick={() => dup.mutate(undefined)}>Duplicate</Button>}
        {can("marketer") && <Button variant="primary" icon={<Save className="h-4 w-4" />} loading={save.isPending} onClick={() => save.mutate(undefined)}>Save</Button>}
      </div>
      <EmailComposer ref={composer} initial={{ subject: t.subject || "", preheader: t.preheader || "", editor_type: t.editor_type, html: t.html || "", design_json: t.design_json, direction: t.direction }} />
      <TestSendModal open={test} onClose={() => setTest(false)} send={(to, account) => api.post(`/templates/${id}/test-send`, { to, sending_account_id: account })} />
    </>
  );
}
