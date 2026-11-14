export const fmtNum = (n: number | null | undefined) => (n ?? 0).toLocaleString("en-US");
export const fmtPct = (n: number | null | undefined) => `${(n ?? 0).toFixed(1)}%`;

export function fmtDate(s: string | null | undefined, withTime = false) {
  if (!s) return "—";
  const d = new Date(s);
  return withTime
    ? d.toLocaleString("en-GB", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

export const titleCase = (s: string | null | undefined) =>
  (s || "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

export const fullName = (c: { first_name?: string | null; last_name?: string | null }) =>
  [c.first_name, c.last_name].filter(Boolean).join(" ") || "—";

export function toLocalInput(d: Date) {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export const COUNTRIES: [string, string][] = [
  ["SA", "Saudi Arabia"], ["AE", "United Arab Emirates"], ["QA", "Qatar"], ["KW", "Kuwait"], ["BH", "Bahrain"],
  ["OM", "Oman"], ["EG", "Egypt"], ["JO", "Jordan"], ["LB", "Lebanon"], ["IQ", "Iraq"], ["MA", "Morocco"],
  ["GB", "United Kingdom"], ["US", "United States"], ["IN", "India"], ["PK", "Pakistan"], ["LK", "Sri Lanka"],
  ["DE", "Germany"], ["FR", "France"], ["TR", "Türkiye"], ["SG", "Singapore"], ["MY", "Malaysia"],
  ["CN", "China"], ["CA", "Canada"], ["AU", "Australia"], ["ZA", "South Africa"], ["NL", "Netherlands"],
];
export const COMPANY_SIZES = ["1-10", "11-50", "51-200", "201-500", "501-1000", "1001-5000", "5000+"];
export const COMPANY_STATUSES = ["active", "prospect", "customer", "inactive"];
export const SUB_STATUSES = ["subscribed", "pending", "unsubscribed", "bounced", "complained"];
export const VERIFY_STATUSES = ["unverified", "valid", "risky", "invalid"];
