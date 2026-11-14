"use client";

import { Copy, FileText, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Badge, Button, Confirm, Empty, ErrorState, Loading, PageHeader, SearchInput } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate } from "@/lib/format";
import { useAction, useWsQuery } from "@/lib/hooks";
import type { Page, Template } from "@/lib/types";

const MODE = { drag_drop: "Drag & drop", rich_text: "Rich text", html: "HTML" };

export default function TemplatesPage() {
  const { can } = useAuth();
  const router = useRouter();
  const [q, setQ] = useState("");
  const [del, setDel] = useState<Template | null>(null);
  const list = useWsQuery(["templates", q], () => api.get<Page<Template>>("/templates", { q, page_size: 200 }));
  const create = useAction(() => api.post<Template>("/templates", { name: "Untitled template", editor_type: "drag_drop", subject: "" }), { onSuccess: (t) => router.push(`/templates/${t.id}`) });
  const dup = useAction((id: string) => api.post<Template>(`/templates/${id}/duplicate`), { success: "Template duplicated", invalidate: [["templates"]] });
  const remove = useAction(() => api.del(`/templates/${del!.id}`), { success: "Template deleted", invalidate: [["templates"]], onSuccess: () => setDel(null) });
  return (
    <>
      <PageHeader title="Email Templates" subtitle="Reusable, personalised email designs in English or Arabic." actions={<><SearchInput value={q} onChange={setQ} placeholder="Search templates…" />{can("marketer") && <Button variant="primary" icon={<Plus className="h-4 w-4" />} loading={create.isPending} onClick={() => create.mutate(undefined)}>New template</Button>}</>} />
      {list.isLoading ? <Loading /> : list.error ? <ErrorState error={list.error} /> : list.data!.items.length === 0 ? (
        <div className="card"><Empty title="No templates yet" hint="Design a reusable email with the drag-and-drop builder, rich text editor or your own HTML." icon={<FileText className="h-6 w-6" />} action={can("marketer") && <Button variant="primary" onClick={() => create.mutate(undefined)}>Create template</Button>} /></div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {list.data!.items.map((t) => (
            <div key={t.id} className="card group flex flex-col p-4 transition-shadow hover:shadow-md">
              <Link href={`/templates/${t.id}`} className="flex-1">
                <div className="mb-3 flex h-28 items-center justify-center rounded-lg bg-gradient-to-br from-brand-50 to-slate-100 text-brand-300"><FileText className="h-10 w-10" /></div>
                <div className="font-semibold text-slate-900 group-hover:text-brand-700">{t.name}</div>
                <div className="mt-0.5 truncate text-sm text-slate-500" dir="auto">{t.subject || "No subject"}</div>
              </Link>
              <div className="mt-3 flex items-center gap-1.5">
                {t.is_draft ? <Badge tone="amber">Draft</Badge> : <Badge tone="green">Ready</Badge>}
                <Badge>{MODE[t.editor_type]}</Badge>
                {t.direction === "rtl" && <Badge tone="violet">العربية</Badge>}
                <span className="ms-auto text-xs text-slate-400">{fmtDate(t.updated_at)}</span>
              </div>
              {can("marketer") && (
                <div className="mt-3 flex gap-1 border-t border-slate-100 pt-3">
                  <Button size="sm" variant="ghost" icon={<Copy className="h-3.5 w-3.5" />} onClick={() => dup.mutate(t.id)}>Duplicate</Button>
                  <Button size="sm" variant="ghost" icon={<Trash2 className="h-3.5 w-3.5 text-red-600" />} onClick={() => setDel(t)}>Delete</Button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
      <Confirm open={!!del} onClose={() => setDel(null)} onConfirm={() => remove.mutate(undefined)} loading={remove.isPending} danger title="Delete template" confirmLabel="Delete" message={<>Delete <b>{del?.name}</b>? Campaigns already sent keep their own copy of the content.</>} />
    </>
  );
}
