"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, errorMessage } from "./api";
import { useAuth } from "./auth";
import type { Option, Tag } from "./types";

/** Query keyed by workspace so switching workspace never shows stale tenant data. */
export function useWsQuery<T>(key: unknown[], fn: () => Promise<T>, opts: { enabled?: boolean; refetchInterval?: number | false } = {}) {
  const { workspaceId } = useAuth();
  return useQuery<T>({ queryKey: [workspaceId, ...key], queryFn: fn, enabled: !!workspaceId && opts.enabled !== false, refetchInterval: opts.refetchInterval });
}

export function useAction<TVars, TOut = unknown>(fn: (v: TVars) => Promise<TOut>, opts: { success?: string | ((o: TOut) => string); invalidate?: string[][]; onSuccess?: (o: TOut) => void } = {}) {
  const qc = useQueryClient();
  const { workspaceId } = useAuth();
  return useMutation<TOut, unknown, TVars>({
    mutationFn: fn,
    onSuccess: (o) => {
      if (opts.success) toast.success(typeof opts.success === "function" ? opts.success(o) : opts.success);
      opts.invalidate?.forEach((k) => qc.invalidateQueries({ queryKey: [workspaceId, ...k] }));
      opts.onSuccess?.(o);
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
}

export function useIndustries() {
  return useWsQuery(["industries"], () => api.get<{ id: string; name: string; company_count: number }[]>("/industries"));
}
export function useTags() {
  return useWsQuery(["tags"], () => api.get<(Tag & { company_count: number; contact_count: number })[]>("/tags"));
}
export function useCategories(scope?: "company" | "contact") {
  return useWsQuery(["categories", scope], () => api.get<{ id: string; name: string; scope: string; color: string | null; usage_count: number }[]>("/categories", scope ? { scope } : undefined));
}
export const toOptions = (rows?: { id: string; name: string }[]): Option[] => (rows || []).map((r) => ({ value: r.id, label: r.name }));
