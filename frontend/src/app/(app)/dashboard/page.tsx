"use client";

import { Plus } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { CampaignTable, DistributionCard, FiltersBar, KpiGrid, TrendsCard, defaultFilters } from "@/components/AnalyticsViews";
import { Button, PageHeader } from "@/components/ui";
import { useAuth } from "@/lib/auth";

export default function DashboardPage() {
  const { me, can } = useAuth();
  const [f, setF] = useState(defaultFilters(30));
  return (
    <>
      <PageHeader
        title={`Welcome back, ${me?.full_name.split(" ")[0] ?? ""}`}
        subtitle="Audience, delivery and engagement at a glance."
        actions={can("marketer") && <Link href="/campaigns/new"><Button variant="primary" icon={<Plus className="h-4 w-4" />}>New campaign</Button></Link>}
      />
      <FiltersBar f={f} setF={setF} />
      <KpiGrid f={f} />
      <div className="mt-5 grid gap-5 xl:grid-cols-3">
        <div className="xl:col-span-2"><TrendsCard f={f} /></div>
        <DistributionCard by="industry" title="Contacts by industry" />
      </div>
      <div className="mt-5"><CampaignTable f={f} limit={8} /></div>
    </>
  );
}
