"use client";

import "grapesjs/dist/css/grapes.min.css";
import type { Editor } from "grapesjs";
import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import { toast } from "sonner";
import { api, errorMessage } from "@/lib/api";

export type GrapesHandle = { getContent: () => { html: string; design: Record<string, unknown> } | null };

const STARTER = `
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f6f8;padding:24px 0;font-family:Arial,Helvetica,sans-serif">
  <tr><td align="center">
    <table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:8px;overflow:hidden">
      <tr><td style="background:#1f3a5f;padding:24px;color:#ffffff;font-size:22px;font-weight:bold">Your company</td></tr>
      <tr><td style="padding:28px 32px;color:#1f2937;font-size:15px;line-height:1.6">
        <p>Dear {{FirstName|there}},</p>
        <p>Write your message here. Drag blocks from the right panel to add images, buttons and columns.</p>
        <p style="text-align:center;margin:28px 0"><a href="https://example.com" style="background:#0e9f8f;color:#ffffff;padding:12px 24px;border-radius:6px;text-decoration:none;font-weight:bold">Learn more</a></p>
        <p>Kind regards,<br/>The team</p>
      </td></tr>
    </table>
  </td></tr>
</table>`;

export const GrapesEditor = forwardRef<GrapesHandle, { html: string | null; design: Record<string, unknown> | null; rtl: boolean }>(
  function GrapesEditor({ html, design, rtl }, ref) {
    const el = useRef<HTMLDivElement>(null);
    const ed = useRef<Editor | null>(null);

    useImperativeHandle(ref, () => ({
      getContent: () => {
        const e = ed.current;
        if (!e) return null;
        let out: string;
        try {
          out = e.runCommand("gjs-get-inlined-html") as string;
        } catch {
          out = `${e.getHtml()}<style>${e.getCss()}</style>`;
        }
        return { html: out, design: e.getProjectData() as Record<string, unknown> };
      },
    }));

    useEffect(() => {
      let disposed = false;
      (async () => {
        const grapesjs = (await import("grapesjs")).default;
        const newsletter = (await import("grapesjs-preset-newsletter")).default;
        if (disposed || !el.current) return;
        const editor = grapesjs.init({
          container: el.current,
          height: "640px",
          storageManager: false,
          fromElement: false,
          plugins: [newsletter],
          pluginsOpts: { [newsletter as unknown as string]: {} },
          assetManager: { upload: false, embedAsBase64: false },
          canvas: { styles: [] },
          ...(design && Object.keys(design).length ? { projectData: design } : { components: html || STARTER }),
        });
        editor.on("load", () => {
          const body = editor.Canvas.getBody();
          if (body) body.setAttribute("dir", rtl ? "rtl" : "ltr");
        });
        editor.on("asset:upload:start", () => undefined);
        // Upload images to our API (stored in object storage, served publicly for email clients)
        const am = editor.AssetManager;
        (am.config as unknown as { uploadFile: (e: DragEvent | Event) => void }).uploadFile = async (e: DragEvent | Event) => {
          const files = ((e as DragEvent).dataTransfer?.files || (e.target as HTMLInputElement)?.files) as FileList;
          for (const f of Array.from(files || [])) {
            try {
              const fd = new FormData();
              fd.append("file", f);
              const r = await api.upload<{ url: string }>("/assets", fd);
              am.add({ src: r.url, type: "image" });
            } catch (err) {
              toast.error(errorMessage(err));
            }
          }
        };
        ed.current = editor;
      })();
      return () => {
        disposed = true;
        ed.current?.destroy();
        ed.current = null;
      };
    }, []);

    useEffect(() => {
      const body = ed.current?.Canvas.getBody();
      if (body) body.setAttribute("dir", rtl ? "rtl" : "ltr");
    }, [rtl]);

    return <div className="overflow-hidden rounded-xl border border-slate-200"><div ref={el} /></div>;
  },
);
