-- Enable row level security on every table in the public schema.
--
-- 0001 and 0002 disabled RLS deliberately, with the reasoning "single-user
-- tool". That is defensible for something running on one laptop against a
-- private database. It stops being defensible the moment the console is
-- deployed anywhere public, because Supabase's anon key is a PUBLIC
-- credential by design: NEXT_PUBLIC_ variables are compiled into the
-- browser bundle, so anyone who loads the page can read the key out of the
-- JavaScript and then talk to PostgREST directly.
--
-- With RLS off that is not a read-only leak. Verified against this project
-- before writing this migration, using the real anon key:
--   * select on txns   -> returned live financial records
--   * select on audit_log -> returned the audit trail
--   * insert into audit_log -> succeeded
--   * delete             -> HTTP 204, succeeded
-- Anyone with the deployed URL could have emptied the database.
--
-- NO POLICIES ARE CREATED HERE, and that is the intended end state, not an
-- omission. RLS with zero policies denies everything to `anon` and
-- `authenticated`. Nothing in this system needs those roles:
--
--   * the FastAPI backend connects with SUPABASE_SERVICE_KEY, and
--     service_role bypasses RLS entirely, so every pipeline stage,
--     scheduler job and console endpoint keeps working untouched
--   * the Next.js console never queries Supabase from the browser. It
--     reads exclusively through the backend (web/lib/api.ts).
--     web/lib/supabaseClient.ts exists but nothing imports it.
--
-- So the correct posture is: the browser gets nothing directly, the server
-- gets everything, and adding a policy later is a deliberate act rather
-- than the default. If a table ever genuinely needs public read, add a
-- narrow policy for exactly that table and say why.

alter table raw_bank_records    enable row level security;
alter table raw_gateway_records enable row level security;
alter table raw_ledger_records  enable row level security;
alter table sources             enable row level security;
alter table matches             enable row level security;
alter table exceptions          enable row level security;
alter table batch_summary       enable row level security;
alter table batches             enable row level security;
alter table txns                enable row level security;
alter table match_groups        enable row level security;
alter table match_members       enable row level security;
alter table variances           enable row level security;
alter table audit_log           enable row level security;
alter table run_state           enable row level security;
alter table run_scores          enable row level security;

-- public.rls_auto_enable() is an event-trigger function that turns RLS on
-- for newly created tables. Supabase's linter flags it as callable over
-- /rest/v1/rpc by anon and authenticated. An event-trigger function errors
-- if invoked outside an event trigger, so this is hardening rather than an
-- open door — but neither role has any reason to hold EXECUTE on it.
--
-- Revoking from PUBLIC is the part that actually does the work. The
-- function's ACL was `{=X/postgres,...}`, and a leading `=X` is a grant to
-- PUBLIC, which anon and authenticated inherit — so revoking from those
-- two roles by name was a no-op and left both still able to execute.
-- Verified after applying: has_function_privilege is now false for anon
-- and authenticated, and still true for service_role.
revoke execute on function public.rls_auto_enable() from public;
revoke execute on function public.rls_auto_enable() from anon, authenticated;
