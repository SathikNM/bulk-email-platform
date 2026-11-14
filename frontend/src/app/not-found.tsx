import Link from "next/link";

export default function NotFound() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-3 text-center">
      <div className="text-5xl font-bold text-brand-700">404</div>
      <p className="text-sm text-slate-500">This page does not exist.</p>
      <Link href="/dashboard" className="text-sm font-medium text-brand-700 hover:underline">Back to dashboard</Link>
    </div>
  );
}
