-- Reconciliation engine v2 schema. Single-operator tool, RLS disabled.
-- Money is always integer paise. Never use float for money anywhere in this codebase.

-- audit_log from 0001_init had a different shape (batch_id not null, no actor,
-- detail_json not detail). Redefine it to match this spec.
drop table if exists audit_log;

create table if not exists sources (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  kind text not null check (kind in ('razorpay', 'bank', 'ledger')),
  created_at timestamptz not null default now()
);

create table if not exists batches (
  id uuid primary key default gen_random_uuid(),
  label text,
  period_start date,
  period_end date,
  status text not null default 'pending'
    check (status in ('pending','ingesting','matching','explaining','scored','complete','failed')),
  created_at timestamptz not null default now(),
  completed_at timestamptz,
  error_text text
);

create table if not exists txns (
  id uuid primary key default gen_random_uuid(),
  batch_id uuid not null references batches(id),
  source_kind text not null check (source_kind in ('razorpay', 'bank', 'ledger')),
  external_ref text,
  amount_paise bigint not null,
  fee_paise bigint,
  tax_paise bigint,
  net_paise bigint,
  txn_date date,
  value_date date,
  description text,
  counterparty text,
  raw jsonb,
  truth_group text,
  is_noise boolean not null default false
);

create index if not exists idx_txns_batch_source on txns (batch_id, source_kind);
create index if not exists idx_txns_batch_amount on txns (batch_id, amount_paise);
create index if not exists idx_txns_batch_date on txns (batch_id, txn_date);

create table if not exists match_groups (
  id uuid primary key default gen_random_uuid(),
  batch_id uuid not null references batches(id),
  tier int,
  strategy text,
  confidence numeric,
  member_count int,
  total_variance_paise bigint,
  created_at timestamptz not null default now()
);

create table if not exists match_members (
  id uuid primary key default gen_random_uuid(),
  match_group_id uuid not null references match_groups(id),
  txn_id uuid not null references txns(id),
  role text not null check (role in ('primary', 'counterpart'))
);

create table if not exists variances (
  id uuid primary key default gen_random_uuid(),
  batch_id uuid not null references batches(id),
  match_group_id uuid references match_groups(id),
  txn_id uuid references txns(id),
  variance_paise bigint,
  category text,
  subcategory text,
  confidence numeric,
  explanation text,
  suggested_action text,
  model_raw jsonb,
  status text not null default 'open'
    check (status in ('open','explained','accepted','written_off')),
  created_at timestamptz not null default now()
);

create table if not exists run_scores (
  id uuid primary key default gen_random_uuid(),
  batch_id uuid not null references batches(id),
  run_at timestamptz not null default now(),
  total_txns int,
  matched_txns int,
  match_rate numeric,
  true_positives int,
  false_positives int,
  false_negatives int,
  precision numeric,
  recall numeric,
  f1 numeric,
  variance_explained_pct numeric,
  unexplained_paise bigint,
  wall_clock_seconds numeric,
  llm_calls int,
  llm_cost_estimate numeric
);

create table if not exists audit_log (
  id uuid primary key default gen_random_uuid(),
  batch_id uuid references batches(id),
  actor text not null check (actor in ('scheduler','matcher','explainer','scorer','human')),
  step text,
  action text,
  detail jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_audit_log_batch_created on audit_log (batch_id, created_at);

create table if not exists run_state (
  id uuid primary key default gen_random_uuid(),
  key text not null unique,
  value jsonb,
  updated_at timestamptz not null default now()
);

alter table sources disable row level security;
alter table batches disable row level security;
alter table txns disable row level security;
alter table match_groups disable row level security;
alter table match_members disable row level security;
alter table variances disable row level security;
alter table run_scores disable row level security;
alter table audit_log disable row level security;
alter table run_state disable row level security;
