-- 0003's unique index was too strict: txns must be able to legitimately
-- hold true duplicate rows (e.g. a bank statement line posted twice by a
-- data-quality bug, or synthetic corpus test cases for that scenario).
-- Ingestion idempotency moves to the application layer instead
-- (ingest/razorpay.py: check existing external_refs before inserting).
drop index if exists uq_txns_batch_source_ref;
