-- Reconciliation engine core tables. RLS intentionally disabled (single-user tool).

create table if not exists raw_bank_records (
  id uuid primary key default gen_random_uuid(),
  batch_id uuid not null,
  txn_ref text,
  amount numeric,
  txn_date date,
  description text,
  raw_json jsonb,
  created_at timestamptz not null default now()
);

create table if not exists raw_gateway_records (
  id uuid primary key default gen_random_uuid(),
  batch_id uuid not null,
  txn_ref text,
  amount numeric,
  fee numeric,
  net_amount numeric,
  settled_date date,
  status text,
  raw_json jsonb,
  created_at timestamptz not null default now()
);

create table if not exists raw_ledger_records (
  id uuid primary key default gen_random_uuid(),
  batch_id uuid not null,
  txn_ref text,
  amount numeric,
  entry_date date,
  category text,
  raw_json jsonb,
  created_at timestamptz not null default now()
);

create table if not exists matches (
  id uuid primary key default gen_random_uuid(),
  batch_id uuid not null,
  bank_record_id uuid references raw_bank_records(id),
  gateway_record_id uuid references raw_gateway_records(id),
  ledger_record_id uuid references raw_ledger_records(id),
  match_type text,
  confidence numeric,
  matched_at timestamptz not null default now()
);

create table if not exists exceptions (
  id uuid primary key default gen_random_uuid(),
  batch_id uuid not null,
  record_source text,
  record_id uuid,
  reason_code text,
  reason_text text,
  resolved boolean not null default false,
  created_at timestamptz not null default now()
);

create table if not exists batch_summary (
  id uuid primary key default gen_random_uuid(),
  batch_id uuid not null,
  total_records integer,
  matched_count integer,
  exception_count integer,
  total_value numeric,
  matched_value numeric,
  created_at timestamptz not null default now()
);

create table if not exists audit_log (
  id uuid primary key default gen_random_uuid(),
  batch_id uuid,
  step text,
  action text,
  detail_json jsonb,
  created_at timestamptz not null default now()
);

alter table raw_bank_records disable row level security;
alter table raw_gateway_records disable row level security;
alter table raw_ledger_records disable row level security;
alter table matches disable row level security;
alter table exceptions disable row level security;
alter table batch_summary disable row level security;
alter table audit_log disable row level security;
