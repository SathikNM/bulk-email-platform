"use client";

import { Shell } from "@/components/Shell";
import { RequireAuth } from "@/lib/auth";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <RequireAuth>
      <Shell>{children}</Shell>
    </RequireAuth>
  );
}
