"use client";

import clsx from "clsx";
import {
  BarChart3,
  Building2,
  ChevronDown,
  FileText,
  Filter,
  History,
  Inbox,
  LayoutDashboard,
  LogOut,
  Mail,
  Menu,
  Send,
  Settings,
  Tags,
  Users,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useWsQuery } from "@/lib/hooks";

export const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/companies", label: "Companies", icon: Building2 },
  { href: "/contacts", label: "Contacts", icon: Users },
  { href: "/taxonomy", label: "Categories & Tags", icon: Tags },
  { href: "/segments", label: "Audience Segments", icon: Filter },
  { href: "/templates", label: "Email Templates", icon: FileText },
  { href: "/campaigns/new", label: "Create Campaign", icon: Send },
  { href: "/campaigns", label: "Campaign History", icon: History, exact: true },
  { href: "/inbox", label: "Inbox", icon: Inbox },
  { href: "/analytics", label: "Analytics", icon: BarChart3 },
  { href: "/sending-accounts", label: "Sending Accounts", icon: Mail },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const unread = useWsQuery(["mailbox-summary"], () => api.get<{ unread: number }>("/mailbox/summary"), { refetchInterval: 30000 }).data?.unread ?? 0;
  const { me, workspaceId, switchWorkspace, logout, role } = useAuth();
  const [open, setOpen] = useState(false);
  const [menu, setMenu] = useState(false);
  const ws = me?.workspaces.find((w) => w.id === workspaceId);
  const isActive = (href: string, exact?: boolean) =>
    exact ? path === href || (/^\/campaigns\/[0-9a-f-]{36}/.test(path) && href === "/campaigns") : path === href || path.startsWith(href + "/");

  const nav = (
    <nav className="flex flex-1 flex-col gap-0.5 px-3 py-4">
      {NAV.map(({ href, label, icon: Icon, exact }) => (
        <Link key={href} href={href} onClick={() => setOpen(false)} className={clsx("group flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors", isActive(href, exact) ? "bg-white/10 text-white" : "text-brand-100 hover:bg-white/5 hover:text-white")}>
          <Icon className={clsx("h-4 w-4", isActive(href, exact) ? "text-white" : "text-brand-300 group-hover:text-white")} />
          {label}
          {href === "/inbox" && unread > 0 && <span className="ms-auto rounded-full bg-accent-500 px-2 py-0.5 text-[11px] font-semibold text-white">{unread}</span>}
        </Link>
      ))}
    </nav>
  );

  return (
    <div className="flex min-h-screen">
      <aside className="fixed inset-y-0 start-0 z-40 hidden w-64 flex-col bg-brand-800 lg:flex">
        <div className="flex h-16 items-center gap-2 px-6">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-500 text-white"><Send className="h-4 w-4" /></div>
          <div>
            <div className="text-sm font-semibold text-white">Bulk Email</div>
            <div className="text-[11px] text-brand-300">Marketing Platform</div>
          </div>
        </div>
        {nav}
        <div className="border-t border-white/10 px-6 py-3 text-[11px] text-brand-300">v1.0 · {role ? role[0].toUpperCase() + role.slice(1) : ""}</div>
      </aside>
      {open && (
        <div className="fixed inset-0 z-50 bg-slate-900/50 lg:hidden" onClick={() => setOpen(false)}>
          <aside className="flex h-full w-64 flex-col bg-brand-800" onClick={(e) => e.stopPropagation()}>
            <div className="flex h-16 items-center justify-between px-6 text-white">
              <span className="font-semibold">Bulk Email</span>
              <button onClick={() => setOpen(false)} aria-label="Close menu"><X className="h-5 w-5" /></button>
            </div>
            {nav}
          </aside>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col lg:ps-64">
        <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-slate-200 bg-white/90 px-4 backdrop-blur sm:px-6">
          <button className="lg:hidden" onClick={() => setOpen(true)} aria-label="Open menu"><Menu className="h-5 w-5 text-slate-600" /></button>
          {me && me.workspaces.length > 1 ? (
            <select className="input w-auto py-1.5 font-medium" value={workspaceId ?? ""} onChange={(e) => switchWorkspace(e.target.value)} aria-label="Workspace">
              {me.workspaces.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
            </select>
          ) : (
            <span className="text-sm font-semibold text-slate-800">{ws?.name}</span>
          )}
          <div className="ms-auto relative">
            <button onClick={() => setMenu(!menu)} className="flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-slate-100">
              <span className="flex h-8 w-8 items-center justify-center rounded-full bg-brand-100 text-xs font-semibold text-brand-800">
                {me?.full_name.split(" ").map((p) => p[0]).slice(0, 2).join("")}
              </span>
              <span className="hidden text-start sm:block">
                <span className="block text-sm font-medium text-slate-800">{me?.full_name}</span>
                <span className="block text-xs text-slate-500">{me?.email}</span>
              </span>
              <ChevronDown className="h-4 w-4 text-slate-400" />
            </button>
            {menu && (
              <div className="absolute end-0 mt-1 w-48 rounded-lg border border-slate-200 bg-white py-1 shadow-lg" onMouseLeave={() => setMenu(false)}>
                <Link href="/settings?tab=account" className="block px-3 py-2 text-sm hover:bg-slate-50" onClick={() => setMenu(false)}>Account</Link>
                <button onClick={logout} className="flex w-full items-center gap-2 px-3 py-2 text-start text-sm text-red-600 hover:bg-red-50"><LogOut className="h-4 w-4" /> Sign out</button>
              </div>
            )}
          </div>
        </header>
        <main className="mx-auto w-full max-w-[1400px] flex-1 px-4 py-6 sm:px-6">{children}</main>
      </div>
    </div>
  );
}
