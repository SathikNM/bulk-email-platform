"use client";

import { RefreshCw } from "lucide-react";
import { useState } from "react";
import {
  CampaignTable,
  DeliveryCard,
  DistributionCard,
  FiltersBar,
  GrowthCard,
  KpiGrid,
  RatesCard,
  TrendsCard,
  defaultFilters,
} from "@/components/AnalyticsViews";
import { Button, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { useAction } from "@/lib/hooks";

export default function AnalyticsPage() {
  const [f, setF] = useState(defaultFilters(30));
  const refresh = useAction(() => api.post("/analytics/refresh"), { success: "Statistics refreshed", invalidate: [["analytics"]] });
  return (
    <>
      <PageHeader title="Analytics" subtitle="Campaign performance, delivery and audience insights." actions={<Button icon={<RefreshCw className="h-4 w-4" />} loading={refresh.isPending} onClick={() => refresh.mutate(undefined)}>Refresh stats</Button>} />
      <FiltersBar f={f} setF={setF} />
      <KpiGrid f={f} />
      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <TrendsCard f={f} />
        <RatesCard f={f} />
        <DeliveryCard f={f} />
        <GrowthCard f={f} />
        <DistributionCard by="industry" title="Industry-wise contact distribution" />
        <DistributionCard by="country" title="Country-wise contact distribution" />
      </div>
      <div className="mt-5"><CampaignTable f={f} /></div>
    </>
  );
}
