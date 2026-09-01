-- Throughput, as its own column rather than something a reader has to
-- divide out of two others. total_txns / wall_clock_seconds.
--
-- Stored rather than computed on read because wall_clock_seconds is
-- itself derived from the batch's audit_log span, and that span keeps
-- growing if the batch is ever resumed or re-scored later — so a figure
-- computed at read time would silently drift away from the throughput
-- the run actually achieved. This column pins what was true when the
-- run was scored.
alter table run_scores
  add column if not exists records_per_second numeric;
