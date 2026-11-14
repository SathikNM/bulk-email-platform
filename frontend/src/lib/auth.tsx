"use client";

import { useQueryClient } from "@tanstack/react-query";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useState, useSyncExternalStore } from "react";
import { api, refreshToken, session } from "./api";
import { ROLE_RANK, type Me, type Role } from "./types";

type AuthCtx = {
  me: Me | null;
  ready: boolean;
  workspaceId: string | null;
  role: Role | null;
  can: (min: Role) => boolean;
  login: (email: string, password: string, otp?: string) => Promise<void>;
  logout: () => Promise<void>;
  switchWorkspace: (id: string) => void;
  reload: () => Promise<void>;
};

const Ctx = createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [ready, setReady] = useState(false);
  const qc = useQueryClient();
  const workspaceId = useSyncExternalStore(session.subscribe, () => session.workspace, () => null);

  const loadMe = useCallback(async () => {
    const m = await api.get<Me>("/auth/me");
    setMe(m);
    if (!session.workspace || !m.workspaces.some((w) => w.id === session.workspace)) {
      session.workspace = m.workspaces[0]?.id ?? null;
    }
  }, []);

  useEffect(() => {
    (async () => {
      if (await refreshToken()) {
        try {
          await loadMe();
        } catch {
          setMe(null);
        }
      }
      setReady(true);
    })();
  }, [loadMe]);

  const login = async (email: string, password: string, otp?: string) => {
    const r = await api.post<{ access_token: string }>("/auth/login", { email, password, ...(otp ? { otp } : {}) });
    session.token = r.access_token;
    await loadMe();
  };

  const logout = async () => {
    try {
      await api.post("/auth/logout");
    } finally {
      session.token = null;
      setMe(null);
      qc.clear();
    }
  };

  const switchWorkspace = (id: string) => {
    session.workspace = id;
    qc.clear();
  };

  const role = (me?.workspaces.find((w) => w.id === workspaceId)?.role as Role) ?? null;
  const can = (min: Role) => !!role && ROLE_RANK[role] >= ROLE_RANK[min];

  return (
    <Ctx.Provider value={{ me, ready, workspaceId, role, can, login, logout, switchWorkspace, reload: loadMe }}>
      {children}
    </Ctx.Provider>
  );
}

export function useAuth() {
  const c = useContext(Ctx);
  if (!c) throw new Error("useAuth outside AuthProvider");
  return c;
}

export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { me, ready } = useAuth();
  const router = useRouter();
  const path = usePathname();
  useEffect(() => {
    if (ready && !me) router.replace(`/login?next=${encodeURIComponent(path)}`);
  }, [ready, me, path, router]);
  if (!ready || !me) {
    return (
      <div className="flex h-screen items-center justify-center text-sm text-slate-500">
        <span className="h-5 w-5 animate-spin rounded-full border-2 border-slate-300 border-t-brand-600" />
      </div>
    );
  }
  return <>{children}</>;
}
