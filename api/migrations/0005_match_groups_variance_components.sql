-- Tier 3 reconstructs WHY a gateway gross and a bank net differ. The
-- single total_variance_paise number can't carry that, so record the
-- breakdown (fee / tax / residual) alongside it.
alter table match_groups
  add column if not exists variance_components jsonb;
