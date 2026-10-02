// Thin client for the service's /public and /staff APIs (proxied under /api).

export type Listing = {
  listing_id: string;
  property_type: string;
  location: string;
  price: number;
  currency: string;
  bedrooms: number | null;
  bathrooms: number | null;
  delivery_status: "ready" | "under_construction" | "off_plan";
  amenities: string[];
  description: string | null;
  verified_days_ago: number;
};

export type ListingsResponse = {
  listings: Listing[];
  freshness_days: number;
  locations: string[];
  property_types: string[];
};

export type Filters = {
  location?: string;
  property_type?: string;
  bedrooms?: number;
  budget_max?: number;
};

export type FieldError = { field: string; message: string };

export type InquiryInput = Filters & {
  submission_id: string;
  name: string;
  email?: string;
  phone?: string;
  timeline?: string;
  purchase_stage?: string;
  message?: string;
  website?: string;
};

export type InquiryResult =
  | { ok: true; reference: string }
  | { ok: false; errors: FieldError[]; message?: string };

function query(filters: Filters): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== "") params.set(key, String(value));
  }
  const text = params.toString();
  return text ? `?${text}` : "";
}

export async function getListings(filters: Filters, signal?: AbortSignal): Promise<ListingsResponse> {
  const response = await fetch(`/api/public/listings${query(filters)}`, { signal });
  if (!response.ok) throw new Error(`Listings unavailable (${response.status})`);
  return response.json();
}

export async function sendInquiry(input: InquiryInput): Promise<InquiryResult> {
  let response: Response;
  try {
    response = await fetch("/api/public/inquiries", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
  } catch {
    return { ok: false, errors: [], message: "No connection. Check your internet and send again." };
  }
  const body = await response.json().catch(() => ({}));
  if (response.status === 202) return { ok: true, reference: body.reference };
  if (response.status === 422 && Array.isArray(body.errors)) return { ok: false, errors: body.errors };
  const message =
    typeof body.detail === "string" ? body.detail : "We couldn't send your inquiry right now. Try again in a minute.";
  return { ok: false, errors: [], message };
}

// --- staff ------------------------------------------------------------------------------------

const TOKEN_KEY = "propflow.staffToken";

export class AuthError extends Error {}

export const staffToken = {
  get: (): string | null => {
    try { return sessionStorage.getItem(TOKEN_KEY); } catch { return null; }
  },
  set: (token: string) => {
    try { sessionStorage.setItem(TOKEN_KEY, token); } catch { /* private mode: keep in memory only */ }
  },
  clear: () => {
    try { sessionStorage.removeItem(TOKEN_KEY); } catch { /* ignore */ }
  },
};

export async function staffFetch<T>(path: string, init: RequestInit = {}, token = staffToken.get()): Promise<T> {
  const response = await fetch(`/api/staff${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token ?? ""}`, ...init.headers },
  });
  if (response.status === 401) throw new AuthError("Your staff token was not accepted.");
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${response.status})`);
  return body as T;
}

export type Ratio = { numerator: number; denominator: number; rate: number | null };

export type Overview = {
  window: { start: string; end: string; timezone: string };
  intake: {
    received_by_source: Record<string, number>;
    received: number;
    outcomes: Record<string, number>;
    rejected_invalid: number;
    intake_success_rate: Ratio;
    crm_actions: Record<string, number>;
    closed_without_lead: number;
  };
  qualification: { priority_distribution: Record<string, number>; qualified_rate: Ratio; ai_outcomes: Record<string, number> };
  crm_sync: { success_rate: Ratio; failed: number };
  first_response_minutes: { count: number; average: number | null; median: number | null };
  matching: { outcomes: Record<string, number>; matched_rate: Ratio };
  followups: {
    sequences_started_by_outcome: Record<string, number>;
    reminders_sent: number;
    customer_replies: number;
    overdue_propflow_activities: number | null;
  };
  handoffs: {
    created: number;
    still_open: number;
    overdue_open_now: number;
    by_reason: Record<string, number>;
    reminded: number;
    escalated_to_manager: number;
  };
  failures: { dead_letters_by_status: Record<string, number>; open_dead_letters_now: number };
  workload: Record<string, { assigned_in_window: number; open_leads: number }>;
  odoo: string;
};

export type Handoff = {
  id: string;
  lead_id: number | null;
  customer: string | null;
  reasons: string[];
  priority: string | null;
  owner: string | null;
  due_at: string;
  due_text: string;
  overdue: boolean;
  reminded: boolean;
  escalated: boolean;
  lead_url: string | null;
};

export type DeadLetter = {
  id: string;
  workflow: string;
  error: string;
  correlation_id: string | null;
  attempts: number;
  created_at: string;
  last_node: string | null;
  replayable: boolean;
};

export type RecentLead = {
  received_at: string;
  source: string;
  kind: "inquiry" | "reply";
  status: string;
  crm_action: string | null;
  odoo_lead_id: number | null;
  name: string | null;
  error: string | null;
  priority: string | null;
  score: number | null;
  handed_off: boolean;
  lead_url: string | null;
};
