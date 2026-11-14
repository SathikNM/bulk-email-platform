"use client";

import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Empty } from "./ui";

export const C = { brand: "#2f5a8c", accent: "#0e9f8f", amber: "#d97706", red: "#dc2626", violet: "#7c3aed", slate: "#94a3b8", sky: "#0284c7" };
const tick = { fontSize: 11, fill: "#64748b" };
const shortDate = (d: string) => new Date(d).toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
const tooltipStyle = { borderRadius: 8, border: "1px solid #e2e8f0", fontSize: 12 };

type Row = Record<string, number | string>;

export function TrendChart({ data, series, height = 280, percent }: { data: Row[]; series: { key: string; label: string; color: string }[]; height?: number; percent?: boolean }) {
  if (!data.length) return <Empty title="No data in this period" />;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 12, left: -8, bottom: 0 }}>
        <CartesianGrid stroke="#f1f5f9" vertical={false} />
        <XAxis dataKey="date" tickFormatter={shortDate} tick={tick} axisLine={false} tickLine={false} minTickGap={24} />
        <YAxis tick={tick} axisLine={false} tickLine={false} allowDecimals={false} unit={percent ? "%" : ""} />
        <Tooltip contentStyle={tooltipStyle} labelFormatter={(l) => new Date(String(l)).toLocaleDateString("en-GB", { dateStyle: "medium" })} />
        <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />
        {series.map((s) => <Line key={s.key} type="monotone" dataKey={s.key} name={s.label} stroke={s.color} strokeWidth={2} dot={false} />)}
      </LineChart>
    </ResponsiveContainer>
  );
}

export function GroupedBars({ data, xKey, series, height = 280, percent, horizontal }: { data: Row[]; xKey: string; series: { key: string; label: string; color: string }[]; height?: number; percent?: boolean; horizontal?: boolean }) {
  if (!data.length) return <Empty title="No data yet" />;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} layout={horizontal ? "vertical" : "horizontal"} margin={{ top: 8, right: 12, left: horizontal ? 24 : -8, bottom: 0 }}>
        <CartesianGrid stroke="#f1f5f9" vertical={!!horizontal} horizontal={!horizontal} />
        {horizontal ? (
          <>
            <XAxis type="number" tick={tick} axisLine={false} tickLine={false} unit={percent ? "%" : ""} allowDecimals={false} />
            <YAxis type="category" dataKey={xKey} tick={tick} axisLine={false} tickLine={false} width={110} />
          </>
        ) : (
          <>
            <XAxis dataKey={xKey} tick={tick} axisLine={false} tickLine={false} interval={0} tickFormatter={(v) => String(v).slice(0, 14)} />
            <YAxis tick={tick} axisLine={false} tickLine={false} unit={percent ? "%" : ""} allowDecimals={false} />
          </>
        )}
        <Tooltip contentStyle={tooltipStyle} cursor={{ fill: "#f8fafc" }} />
        {series.length > 1 && <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />}
        {series.map((s) => <Bar key={s.key} dataKey={s.key} name={s.label} fill={s.color} radius={horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0]} maxBarSize={36} />)}
      </BarChart>
    </ResponsiveContainer>
  );
}

export function GrowthChart({ data, height = 260 }: { data: Row[]; height?: number }) {
  if (!data.length) return <Empty title="No data in this period" />;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 8, right: 12, left: -8, bottom: 0 }}>
        <defs>
          <linearGradient id="g1" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={C.brand} stopOpacity={0.25} />
            <stop offset="100%" stopColor={C.brand} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="#f1f5f9" vertical={false} />
        <XAxis dataKey="date" tickFormatter={shortDate} tick={tick} axisLine={false} tickLine={false} minTickGap={24} />
        <YAxis tick={tick} axisLine={false} tickLine={false} allowDecimals={false} />
        <Tooltip contentStyle={tooltipStyle} labelFormatter={(l) => new Date(String(l)).toLocaleDateString("en-GB", { dateStyle: "medium" })} />
        <Area type="monotone" dataKey="total_contacts" name="Total contacts" stroke={C.brand} fill="url(#g1)" strokeWidth={2} />
        <Bar dataKey="contacts_added" name="Added" fill={C.accent} />
      </AreaChart>
    </ResponsiveContainer>
  );
}
