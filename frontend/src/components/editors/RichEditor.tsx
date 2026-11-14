"use client";

import Image from "@tiptap/extension-image";
import Link from "@tiptap/extension-link";
import TextAlign from "@tiptap/extension-text-align";
import { EditorContent, useEditor, type Editor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import clsx from "clsx";
import { AlignCenter, AlignLeft, AlignRight, Bold, Heading1, Heading2, ImageIcon, Italic, Link2, List, ListOrdered, MousePointerClick, Redo2, Underline as UIcon, Undo2 } from "lucide-react";
import { forwardRef, useImperativeHandle, useRef } from "react";
import { toast } from "sonner";
import { api, errorMessage } from "@/lib/api";

export type RichHandle = { getHtml: () => string; insert: (text: string) => void };

/** Wrap TipTap's fragment in a simple, email-safe 600px layout. */
export function wrapEmail(inner: string, rtl: boolean) {
  const dir = rtl ? "rtl" : "ltr";
  const font = rtl ? "Tahoma,Arial,sans-serif" : "Arial,Helvetica,sans-serif";
  return `<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f6f8;padding:24px 0"><tr><td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" dir="${dir}" style="max-width:600px;width:100%;background:#ffffff;border-radius:8px"><tr>
<td class="bep-content" style="padding:28px 32px;font-family:${font};font-size:15px;line-height:1.6;color:#1f2937;text-align:${rtl ? "right" : "left"}">${inner}</td>
</tr></table></td></tr></table>`;
}

export function unwrapEmail(html: string | null): string {
  if (!html) return "";
  const m = /class="bep-content"[^>]*>([\s\S]*?)<\/td>\s*<\/tr>\s*<\/table>/i.exec(html);
  return m ? m[1] : html;
}

export const RichEditor = forwardRef<RichHandle, { html: string | null; rtl: boolean }>(function RichEditor({ html, rtl }, ref) {
  const fileRef = useRef<HTMLInputElement>(null);
  const editor = useEditor({
    immediatelyRender: false,
    extensions: [
      StarterKit.configure({ link: false }),
      Link.configure({ openOnClick: false, HTMLAttributes: { rel: "noopener noreferrer" } }),
      Image.configure({ HTMLAttributes: { style: "max-width:100%;height:auto" } }),
      TextAlign.configure({ types: ["heading", "paragraph"] }),
    ],
    content: unwrapEmail(html) || "<p>Dear {{FirstName|there}},</p><p></p>",
  });

  useImperativeHandle(ref, () => ({
    getHtml: () => wrapEmail(editor?.getHTML() || "", rtl),
    insert: (text: string) => editor?.chain().focus().insertContent(text).run(),
  }), [editor, rtl]);

  const upload = async (f: File) => {
    try {
      const fd = new FormData();
      fd.append("file", f);
      const r = await api.upload<{ url: string }>("/assets", fd);
      editor?.chain().focus().setImage({ src: r.url, alt: f.name }).run();
    } catch (e) { toast.error(errorMessage(e)); }
  };
  const link = () => {
    const url = window.prompt("Link URL (https://…)", editor?.getAttributes("link").href || "https://");
    if (url === null) return;
    if (url === "") editor?.chain().focus().unsetLink().run();
    else editor?.chain().focus().extendMarkRange("link").setLink({ href: url }).run();
  };
  const cta = () => {
    const label = window.prompt("Button text", "Learn more");
    const url = label && window.prompt("Button link (https://…)", "https://");
    if (!label || !url) return;
    editor?.chain().focus().insertContent(`<p style="text-align:center"><a href="${url}" style="background:#0e9f8f;color:#ffffff;padding:12px 24px;border-radius:6px;text-decoration:none;font-weight:bold;display:inline-block">${label}</a></p>`).run();
  };

  if (!editor) return null;
  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
      <Toolbar editor={editor} onImage={() => fileRef.current?.click()} onLink={link} onCta={cta} />
      <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/gif,image/webp" className="hidden" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
      <div className="bg-slate-50 p-6">
        <div dir={rtl ? "rtl" : "ltr"} className={clsx("mx-auto max-w-[600px] rounded-lg bg-white px-8 py-7 text-[15px] leading-relaxed shadow-xs", rtl && "text-right")}>
          <EditorContent editor={editor} />
        </div>
      </div>
    </div>
  );
});

function Toolbar({ editor, onImage, onLink, onCta }: { editor: Editor; onImage: () => void; onLink: () => void; onCta: () => void }) {
  const b = (active: boolean, onClick: () => void, icon: React.ReactNode, label: string) => (
    <button type="button" title={label} aria-label={label} onClick={onClick} className={clsx("rounded p-1.5", active ? "bg-brand-100 text-brand-800" : "text-slate-600 hover:bg-slate-100")}>{icon}</button>
  );
  const c = () => editor.chain().focus();
  return (
    <div className="flex flex-wrap items-center gap-0.5 border-b border-slate-200 px-2 py-1.5">
      {b(editor.isActive("bold"), () => c().toggleBold().run(), <Bold className="h-4 w-4" />, "Bold")}
      {b(editor.isActive("italic"), () => c().toggleItalic().run(), <Italic className="h-4 w-4" />, "Italic")}
      {b(editor.isActive("underline"), () => c().toggleUnderline().run(), <UIcon className="h-4 w-4" />, "Underline")}
      <span className="mx-1 h-5 w-px bg-slate-200" />
      {b(editor.isActive("heading", { level: 1 }), () => c().toggleHeading({ level: 1 }).run(), <Heading1 className="h-4 w-4" />, "Heading 1")}
      {b(editor.isActive("heading", { level: 2 }), () => c().toggleHeading({ level: 2 }).run(), <Heading2 className="h-4 w-4" />, "Heading 2")}
      {b(editor.isActive("bulletList"), () => c().toggleBulletList().run(), <List className="h-4 w-4" />, "Bullet list")}
      {b(editor.isActive("orderedList"), () => c().toggleOrderedList().run(), <ListOrdered className="h-4 w-4" />, "Numbered list")}
      <span className="mx-1 h-5 w-px bg-slate-200" />
      {b(editor.isActive({ textAlign: "left" }), () => c().setTextAlign("left").run(), <AlignLeft className="h-4 w-4" />, "Align left")}
      {b(editor.isActive({ textAlign: "center" }), () => c().setTextAlign("center").run(), <AlignCenter className="h-4 w-4" />, "Align centre")}
      {b(editor.isActive({ textAlign: "right" }), () => c().setTextAlign("right").run(), <AlignRight className="h-4 w-4" />, "Align right")}
      <span className="mx-1 h-5 w-px bg-slate-200" />
      {b(editor.isActive("link"), onLink, <Link2 className="h-4 w-4" />, "Link")}
      {b(false, onImage, <ImageIcon className="h-4 w-4" />, "Insert image")}
      {b(false, onCta, <MousePointerClick className="h-4 w-4" />, "Insert button")}
      <span className="ms-auto" />
      {b(false, () => c().undo().run(), <Undo2 className="h-4 w-4" />, "Undo")}
      {b(false, () => c().redo().run(), <Redo2 className="h-4 w-4" />, "Redo")}
    </div>
  );
}
