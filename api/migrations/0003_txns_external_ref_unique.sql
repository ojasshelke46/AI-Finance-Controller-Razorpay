-- Idempotency key for ingestion: re-running the same date range must not
-- create duplicate txns rows. Keyed on external_ref (Razorpay's own id)
-- scoped to the batch and source.
create unique index if not exists uq_txns_batch_source_ref
  on txns (batch_id, source_kind, external_ref)
  where external_ref is not null;
