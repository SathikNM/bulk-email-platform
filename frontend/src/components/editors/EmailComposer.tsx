"use client";

import dynamic from "next/dynamic";
import { Code2, Eye, LayoutTemplate, Sparkles, Type } from "lucide-react";
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { Rendered } from "@/lib/types";
import { Card, Field, Tabs, Toggle } from "../ui";
import type { GrapesHandle } from "./GrapesEditor";
import { type RichHandle, RichEditor } from "./RichEditor";
import { AiPanel, PreviewPane, VariablesMenu } from "./StudioPanels";

const GrapesEditor = dynamic(() => import("./GrapesEditor").then((m) => m.GrapesEditor), {
  ssr: false,
  loading: () => <div className="flex h-[640px] items-center justify-center rounded-xl border border-slate-200 text-sm text-slate-500">Loading drag-and-drop builder…</div>,
});

export type EditorType = "drag_drop" | "rich_text" | "html";
export type ComposerValue = { subject: string; preheader: string; editor_type: EditorType; html: string; design_json: Record<string, unknown> | null; direction: "ltr" | "rtl" };
export type ComposerHandle = { collect: () => ComposerValue };

export const EmailComposer = forwardRef<ComposerHandle, { initial: ComposerValue; contactId?: string | null }>(function EmailComposer({ initial, contactId }, ref) {
  const [v, setV] = useState<ComposerValue>(initial);
  const [view, setView] = useState<"edit" | "preview" | "ai">("edit");
  const [rendered, setRendered] = useState<Rendered | null>(null);
  const [rendering, setRendering] = useState(false);
  const grapes = useRef<GrapesHandle>(null);
  const rich = useRef<RichHandle>(null);
  const htmlRef = useRef<HTMLTextAreaElement>(null);
  const subjRef = useRef<HTMLInputElement>(null);
  const [editorKey, setEditorKey] = useState(0);

  const currentHtml = (): { html: string; design: Record<string, unknown> | null } => {
    if (v.editor_type === "drag_drop") {
      const c = grapes.current?.getContent();
      return c ? { html: c.html, design: c.design } : { html: v.html, design: v.design_json };
    }
    if (v.editor_type === "rich_text") return { html: rich.current?.getHtml() ?? v.html, design: null };
    return { html: v.html, design: null };
  };
  const collect = (): ComposerValue => {
    const c = currentHtml();
    return { ...v, html: c.html, design_json: c.design };
  };
  useImperativeHandle(ref, () => ({ collect }));

  const switchMode = (mode: EditorType) => {
    if (mode === v.editor_type) return;
    const c = currentHtml();
    if (mode === "drag_drop" && v.editor_type !== "drag_drop" && !window.confirm("Switching to the drag-and-drop builder converts your content into blocks. Continue?")) return;
    setV({ ...v, editor_type: mode, html: c.html, design_json: mode === "drag_drop" ? null : v.design_json });
    setEditorKey((k) => k + 1);
  };

  const preview = async () => {
    const c = collect();
    setV(c);
    setView("preview");
    setRendering(true);
    try {
      setRendered(await api.post<Rendered>("/templates/render", { html: c.html, subject: c.subject, preheader: c.preheader, direction: c.direction, contact_id: contactId || null }));
    } catch (e) {
      toast.error(String(e));
    } finally {
      setRendering(false);
    }
  };

  const insertToken = (token: string) => {
    if (document.activeElement === subjRef.current) {
      const el = subjRef.current!;
      const s = el.selectionStart ?? v.subject.length;
      setV({ ...v, subject: v.subject.slice(0, s) + token + v.subject.slice(el.selectionEnd ?? s) });
      return;
    }
    if (v.editor_type === "rich_text") return rich.current?.insert(token);
    if (v.editor_type === "html" && htmlRef.current) {
      const el = htmlRef.current;
      const s = el.selectionStart;
      setV({ ...v, html: v.html.slice(0, s) + token + v.html.slice(el.selectionEnd) });
      return;
    }
    navigator.clipboard.writeText(token);
    toast.success(`${token} copied. Paste it into a text block.`);
  };

  useEffect(() => { if (view === "preview") preview(); }, [contactId]);

  return (
    <div className="space-y-4">
      <Card>
        <div className="grid gap-4 md:grid-cols-[1fr_1fr_auto]">
          <Field label="Subject line *"><input ref={subjRef} className="input" dir="auto" value={v.subject} onChange={(e) => setV({ ...v, subject: e.target.value })} placeholder="e.g. {{FirstName|Hello}}, your Q4 finance outlook" /></Field>
          <Field label="Preheader (inbox preview text)"><input className="input" dir="auto" value={v.preheader} onChange={(e) => setV({ ...v, preheader: e.target.value })} /></Field>
          <div className="flex items-end gap-3 pb-1">
            <Toggle checked={v.direction === "rtl"} onChange={(rtl) => { const c = collect(); setV({ ...c, direction: rtl ? "rtl" : "ltr" }); setEditorKey((k) => k + 1); }} label="Arabic / RTL" />
          </div>
        </div>
      </Card>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Tabs value={view} onChange={(x) => (x === "preview" ? preview() : setView(x as "edit" | "ai"))} tabs={[
          { value: "edit", label: <span className="inline-flex items-center gap-1.5"><Type className="h-4 w-4" />Edit</span> },
          { value: "preview", label: <span className="inline-flex items-center gap-1.5"><Eye className="h-4 w-4" />Preview</span> },
          { value: "ai", label: <span className="inline-flex items-center gap-1.5"><Sparkles className="h-4 w-4" />AI assistant</span> },
        ]} />
        {view === "edit" && (
          <div className="flex items-center gap-2">
            <div className="inline-flex overflow-hidden rounded-lg border border-slate-300 text-xs font-medium">
              {([["drag_drop", "Drag & drop", LayoutTemplate], ["rich_text", "Rich text", Type], ["html", "HTML", Code2]] as const).map(([m, l, Icon]) => (
                <button key={m} onClick={() => switchMode(m)} className={`inline-flex items-center gap-1 px-2.5 py-1.5 ${v.editor_type === m ? "bg-brand-700 text-white" : "bg-white text-slate-600 hover:bg-slate-50"}`}><Icon className="h-3.5 w-3.5" />{l}</button>
              ))}
            </div>
            <VariablesMenu onInsert={insertToken} />
          </div>
        )}
      </div>
      <div className={view === "edit" ? "" : "hidden"}>
        {v.editor_type === "drag_drop" && <GrapesEditor key={editorKey} ref={grapes} html={v.html} design={v.design_json} rtl={v.direction === "rtl"} />}
        {v.editor_type === "rich_text" && <RichEditor key={editorKey} ref={rich} html={v.html} rtl={v.direction === "rtl"} />}
        {v.editor_type === "html" && (
          <textarea ref={htmlRef} dir="ltr" spellCheck={false} className="input h-[640px] font-mono text-xs leading-relaxed" value={v.html} onChange={(e) => setV({ ...v, html: e.target.value })} placeholder="<table>…</table>" />
        )}
      </div>
      {view === "preview" && <PreviewPane rendered={rendered} loading={rendering} />}
      {view === "ai" && (
        <Card className="max-w-2xl">
          <AiPanel onSubject={(s) => { setV((x) => ({ ...x, subject: s })); toast.success("Subject updated"); }}
            onInsert={(h) => {
              const c = collect();
              if (c.editor_type === "rich_text") { setView("edit"); setTimeout(() => rich.current?.insert(h), 50); }
              else { setV({ ...c, editor_type: "rich_text", html: h }); setEditorKey((k) => k + 1); setView("edit"); }
              toast.success("Inserted into the email");
            }} />
        </Card>
      )}
      <p className="text-xs text-slate-500">An unsubscribe link and your postal address are added automatically if the email does not already include <code>{"{{UnsubscribeUrl}}"}</code>.</p>
    </div>
  );
});
