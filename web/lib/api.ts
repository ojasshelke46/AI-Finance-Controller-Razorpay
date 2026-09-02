/**
 * Typed client for the reconciliation API.
 *
 * Reads go through the FastAPI service rather than straight to Supabase
 * so there is one implementation of every derived figure (funnel counts,
 * traceability of cited amounts, open-variance totals). Two
 * implementations of "match rate" that disagree is a bug the console
 * would surface as a mystery.
 */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Server-side fetch. Never cached: this console exists to show what is
 *  true right now, and a stale autonomy dashboard is worse than none. */
export async function apiGet<T>(path: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      cache: "no-store",
      headers: { accept: "application/json" },
    });
  } catch (error) {
    throw new ApiError(
      `Cannot reach the reconciliation API at ${API_BASE}. Is it running?`,
    );
  }
  if (!response.ok) {
    throw new ApiError(`API returned ${response.status} for ${path}`, response.status);
  }
  return (await response.json()) as T;
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json", accept: "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    let detail = `API returned ${response.status}`;
    try {
      const payload = await response.json();
      if (payload?.detail) detail = String(payload.detail);
    } catch {
      /* response had no JSON body; the status is all we have */
    }
    throw new ApiError(detail, response.status);
  }
  return (await response.json()) as T;
}

/* ------------------------------------------------------------------ */
/* types                                                               */
/* ------------------------------------------------------------------ */

export type SchedulerJob = {
  id: string;
  name: string;
  next_run_at: string | null;
};

export type RunScore = {
  batch_id: string;
  run_at?: string;
  total_txns: number | null;
  matched_txns?: number | null;
  match_rate: number | null;
  precision: number | null;
  recall: number | null;
  f1: number | null;
  variance_explained_pct?: number | null;
  unexplained_paise?: number | null;
  wall_clock_seconds?: number | null;
  records_per_second?: number | null;
  explanation_grounding_pct: number | null;
  /** Only populated by /console/status, which joins the batch label in so
   *  the card can name the run it is quoting. */
  label?: string | null;
};

export type StatusResponse = {
  scheduler_running: boolean;
  jobs: SchedulerJob[];
  next_run_at: string | null;
  last_run: {
    batch_id: string;
    action: string;
    at: string;
    elapsed_seconds: number | null;
    stages_run: string[] | null;
  } | null;
  batches_created_today: number;
  batches_completed_today: number;
  latest_score: RunScore | null;
  unexplained_paise: number;
  open_variance_count: number;
  recent_events: AuditEvent[];
  server_time: string;
};

export type BatchSummary = {
  id: string;
  label: string | null;
  status: string;
  period_start: string | null;
  period_end: string | null;
  created_at: string;
  completed_at: string | null;
  error_text: string | null;
  txn_count: number;
  match_rate: number | null;
  precision: number | null;
  recall: number | null;
  f1: number | null;
  explanation_grounding_pct: number | null;
  open_variance_count: number;
  unexplained_paise: number;
};

export type FunnelStep = {
  label: string;
  kind: "total" | "tier" | "variance";
  tier?: number;
  txns: number;
  groups: number | null;
  strategy: string;
  residual_paise: number;
};

export type BatchDetail = {
  batch: BatchSummary & Record<string, unknown>;
  score: RunScore | null;
  funnel: FunnelStep[];
  totals: {
    txns: number;
    matched_txns: number;
    match_groups: number;
    variances: number;
    by_source: Record<string, number>;
  };
  variances_by_status: Record<string, { count: number; paise: number }>;
  variances_by_category: Record<string, { count: number; paise: number }>;
};

export type TxnRecord = {
  txn_id: string;
  source_kind: string;
  external_ref: string | null;
  amount_paise: number;
  fee_paise: number | null;
  tax_paise: number | null;
  net_paise: number | null;
  txn_date: string | null;
  value_date: string | null;
  description: string | null;
  counterparty: string | null;
  raw: Record<string, unknown> | null;
};

export type MatchGroup = {
  id: string;
  tier: number | null;
  strategy: string | null;
  confidence: number | null;
  member_count: number | null;
  total_variance_paise: number | null;
  variance_components: Record<string, unknown> | null;
};

export type Variance = {
  id: string;
  batch_id: string;
  match_group_id: string | null;
  txn_id: string | null;
  variance_paise: number;
  category: string | null;
  subcategory: string | null;
  confidence: number | null;
  explanation: string | null;
  suggested_action: string | null;
  status: string;
  created_at: string;
  records: TxnRecord[];
  match_group: MatchGroup | null;
  cited_figures: string[];
  untraceable_figures: string[];
  all_figures_traceable: boolean;
};

export type VarianceResponse = {
  variances: Variance[];
  categories: string[];
  total: number;
};

export type AuditEvent = {
  id?: string;
  batch_id: string | null;
  actor: string;
  step: string | null;
  action: string | null;
  detail?: Record<string, unknown> | null;
  created_at: string;
};

export type AuditResponse = {
  events: AuditEvent[];
  actors: string[];
  steps: string[];
  total: number;
};

export type QnaAttempt = {
  attempt: number;
  ungrounded_figures?: string[];
  latency_ms?: number;
  total_tokens?: number | null;
  error?: string;
};

export type QnaResponse = {
  batch_id: string;
  question: string;
  answer: string;
  verified: boolean;
  attempts: QnaAttempt[];
  context_chars: number;
};

/* ------------------------------------------------------------------ */
/* calls                                                               */
/* ------------------------------------------------------------------ */

export const getStatus = () => apiGet<StatusResponse>("/console/status");
export const getBatches = () => apiGet<{ batches: BatchSummary[] }>("/console/batches");
export const getBatch = (id: string) => apiGet<BatchDetail>(`/console/batches/${id}`);

export function getVariances(
  id: string,
  params: { category?: string; status?: string } = {},
) {
  const search = new URLSearchParams();
  if (params.category) search.set("category", params.category);
  if (params.status) search.set("status", params.status);
  const qs = search.toString();
  return apiGet<VarianceResponse>(`/console/batches/${id}/variances${qs ? `?${qs}` : ""}`);
}

export function getAudit(id: string, params: { actor?: string; step?: string } = {}) {
  const search = new URLSearchParams();
  if (params.actor) search.set("actor", params.actor);
  if (params.step) search.set("step", params.step);
  const qs = search.toString();
  return apiGet<AuditResponse>(`/console/batches/${id}/audit${qs ? `?${qs}` : ""}`);
}

export const actOnVariance = (
  varianceId: string,
  action: "accept" | "write_off" | "reopen",
  note?: string,
) => apiPost<{ variance_id: string; status: string }>(
  `/console/variances/${varianceId}/action`,
  { action, note },
);

export const askQuestion = (batchId: string, question: string) =>
  apiPost<QnaResponse>(`/qna/${batchId}`, { question });
