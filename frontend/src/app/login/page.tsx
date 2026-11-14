"use client";

import { Send } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { Alert, Button, Field } from "@/components/ui";
import { errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";

function LoginForm() {
  const { login, me, ready } = useAuth();
  const router = useRouter();
  const next = useSearchParams().get("next") || "/dashboard";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (ready && me) router.replace(next.startsWith("/") ? next : "/dashboard");
  }, [ready, me]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      await login(email, password);
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen">
      <div className="hidden flex-1 flex-col justify-between bg-brand-800 p-12 text-white lg:flex">
        <div className="flex items-center gap-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent-500"><Send className="h-4 w-4" /></div>
          <span className="font-semibold">Bulk Email Platform</span>
        </div>
        <div>
          <h1 className="max-w-md text-3xl font-semibold leading-tight">Targeted, compliant email campaigns for every client portfolio.</h1>
          <p className="mt-4 max-w-md text-brand-200">Company and contact database, audience segmentation, email studio, delivery tracking and analytics in one workspace.</p>
        </div>
        <div className="text-xs text-brand-300">Consent-first sending · Suppression lists enforced on every send</div>
      </div>
      <div className="flex flex-1 items-center justify-center p-6">
        <form onSubmit={submit} className="w-full max-w-sm space-y-4">
          <div>
            <h2 className="text-xl font-semibold">Sign in</h2>
            <p className="mt-1 text-sm text-slate-500">Use your workspace account.</p>
          </div>
          {err && <Alert tone="red">{err}</Alert>}
          <Field label="Email"><input className="input" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
          <Field label="Password"><input className="input" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
          <Button variant="primary" className="w-full" type="submit" loading={busy}>Sign in</Button>
        </form>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return <Suspense><LoginForm /></Suspense>;
}
