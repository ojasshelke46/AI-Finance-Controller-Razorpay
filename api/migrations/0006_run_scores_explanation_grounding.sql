-- A second-pass critic grades each LLM explanation: does it follow from
-- the record, are the cited amounts really present, does the suggested
-- action fit the category. The pass rate across all three checks lands
-- here, alongside the matcher's precision/recall, so one run_scores row
-- carries both "did we match correctly" and "can we trust what we said
-- about what we could not match".
alter table run_scores
  add column if not exists explanation_grounding_pct numeric;
