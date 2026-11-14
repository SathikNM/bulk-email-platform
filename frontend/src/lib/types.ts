export type Page<T> = { items: T[]; total: number; page: number; page_size: number };
export type Role = "owner" | "admin" | "marketer" | "analyst" | "viewer";
export const ROLE_RANK: Record<Role, number> = { viewer: 0, analyst: 1, marketer: 2, admin: 3, owner: 4 };

export type Me = {
  id: string;
  email: string;
  full_name: string;
  is_superadmin: boolean;
  totp_enabled?: boolean;
  workspaces: { id: string; name: string; slug: string; role: Role; default_locale: string }[];
};

export type Tag = { id: string; name: string; color?: string | null };
export type Option = { value: string; label: string };

export type Company = {
  id: string;
  code: string;
  name: string;
  name_ar?: string | null;
  industry_id: string | null;
  industry: string | null;
  business_type: string | null;
  country_code: string | null;
  city: string | null;
  website: string | null;
  domain: string | null;
  company_size: string | null;
  annual_revenue: string | null;
  status: string;
  data_source: string | null;
  notes: string | null;
  tags: Tag[];
  categories: { id: string; name: string }[];
  contact_count: number;
  created_at: string;
  updated_at: string;
  contacts?: Contact[];
  campaigns?: { id: string; name: string; status: string; sent: number }[];
};

export type Contact = {
  id: string;
  code: string;
  company_id: string;
  company_name: string | null;
  first_name: string | null;
  last_name: string | null;
  full_name: string | null;
  name_ar?: string | null;
  company_name_ar?: string | null;
  job_title: string | null;
  department: string | null;
  email: string;
  phone: string | null;
  country_code: string | null;
  city: string | null;
  category_id: string | null;
  category: string | null;
  subscription_status: string;
  consent_source: string | null;
  consent_date: string | null;
  email_verification_status: string;
  notes: string | null;
  tags: Tag[];
  is_role_account: boolean;
  created_at: string;
  consents?: Consent[];
  suppressed?: string | null;
};

export type Consent = {
  id: string;
  lawful_basis: string;
  source: string;
  evidence: string | null;
  granted_at: string;
  withdrawn_at: string | null;
};

export type Rule = { field: string; operator: string; value?: unknown };
export type RuleGroup = { op: "and" | "or"; rules: (Rule | RuleGroup)[] };
export type Segment = {
  id: string;
  name: string;
  description: string | null;
  rules: RuleGroup;
  cached_count: number | null;
  cached_eligible_count: number | null;
  count_refreshed_at: string | null;
  campaign_count?: number;
  updated_at: string;
  counts?: SegmentCounts;
};
export type SegmentCounts = {
  total: number;
  eligible: number;
  excluded: Record<string, number>;
  by_subscription_status: Record<string, number>;
};
export type FieldDef = {
  field: string;
  label: string;
  kind: "text" | "ref" | "ref_m2m" | "enum" | "date";
  operators: string[];
  options: Option[] | null;
  async_options: boolean;
};

export type Template = {
  id: string;
  name: string;
  subject: string | null;
  preheader: string | null;
  editor_type: "rich_text" | "drag_drop" | "html";
  design_json: Record<string, unknown> | null;
  html: string | null;
  text_body: string | null;
  direction: "ltr" | "rtl";
  locale: string;
  is_draft: boolean;
  updated_at: string;
};

export type Rendered = {
  subject: string;
  html: string;
  text: string;
  variables_used: string[];
  unknown_variables: string[];
  warnings: string[];
};

export type CampaignStats = {
  recipients: number;
  queued: number;
  sent: number;
  delivered: number;
  bounced: number;
  failed: number;
  skipped: number;
  complained: number;
  unique_opens: number;
  unique_clicks: number;
  unsubscribes: number;
  open_rate: number;
  click_rate: number;
  click_to_open_rate?: number;
  bounce_rate: number;
  unsubscribe_rate: number;
  delivery_rate: number;
  progress: number;
};

export type Campaign = {
  id: string;
  name: string;
  status: string;
  segment_id: string | null;
  segment_name: string | null;
  manual_contact_ids: string[];
  manual_contact_count: number;
  template_id: string | null;
  template_name: string | null;
  subject: string | null;
  preheader: string | null;
  content_html: string | null;
  direction: "ltr" | "rtl" | null;
  sending_account_id: string | null;
  sending_account: string | null;
  scheduled_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  approved_at: string | null;
  is_approved: boolean;
  total_recipients: number;
  last_error: string | null;
  created_at: string;
  stats: CampaignStats;
};

export type Validation = {
  ok: boolean;
  errors: string[];
  warnings: string[];
  audience: {
    total_matched: number;
    eligible: number;
    excluded: Record<string, number>;
    duplicates_removed: number;
    missing_merge_fields: Record<string, number>;
  };
  sending_account: { id: string; from: string; verified: boolean } | null;
};

export type SendingAccount = {
  id: string;
  name: string;
  provider: "ses" | "smtp" | "direct";
  from_email: string;
  from_name: string | null;
  reply_to: string | null;
  domain: string;
  region: string | null;
  configuration_set: string | null;
  max_per_second: number;
  max_per_day: number;
  verification_status: "pending" | "verified" | "failed";
  dns_records: { type: string; name: string; value: string; purpose: string }[] | null;
  is_default: boolean;
  credentials_set: boolean;
  credentials_hint: Record<string, string>;
  warmup_limit_today?: number;
  warmup_active?: boolean;
};
