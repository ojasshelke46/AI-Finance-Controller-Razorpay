/**
 * Backend enum -> English.
 *
 * Every enum the API can send has an entry here. An operator reading
 * `book_to_fee_account` or `poll_no_activity` cold has to guess; that is
 * the guessing this file removes. `humanise` is the fallback, not the
 * mechanism: it only tidies underscores, so an unglossed value still
 * reads as a machine value and is visibly a gap to be filled.
 *
 * The vocabulary is taken from the API itself:
 *   categories + actions  api/explain/variance_explainer.py
 *   actors + steps        api/runtime/{pipeline,scheduler}.py
 *   strategies            api/matching/tier*.py
 */

import { humanise } from "./format";

/* ------------------------------------------------------------------ */
/* variance categories                                                 */
/* ------------------------------------------------------------------ */

const CATEGORY: Record<string, string> = {
  gateway_fee: "Gateway fee",
  gst_on_fee: "GST on gateway fee",
  refund_offset: "Refund offset",
  chargeback: "Chargeback",
  timing_difference: "Timing difference",
  duplicate_entry: "Duplicate entry",
  missing_source_record: "Missing source record",
  fx_or_rounding: "FX or rounding",
  partial_settlement: "Partial settlement",
  unexplained: "Unexplained",
};

export function categoryLabel(value: string | null | undefined): string {
  if (!value) return "—";
  return CATEGORY[value] ?? humanise(value);
}

/* ------------------------------------------------------------------ */
/* suggested actions                                                   */
/* ------------------------------------------------------------------ */

/**
 * Two forms. The sentence is what an operator reads to decide, and it is
 * what the queue shows; the short form exists only where a column is too
 * narrow for the sentence and the sentence is available on the same row.
 */
const ACTION: Record<string, { short: string; sentence: string }> = {
  auto_accept: {
    short: "Accept",
    sentence: "Safe to accept without review",
  },
  book_to_fee_account: {
    short: "Post to fee account",
    sentence: "Post to the payment-processing fee account",
  },
  await_next_settlement: {
    short: "Wait for settlement",
    sentence: "Expected to clear in the next settlement",
  },
  request_bank_advice: {
    short: "Ask the bank",
    sentence: "Ask the bank for an advice note",
  },
  flag_for_human: {
    short: "Needs a person",
    sentence: "Needs a person to decide",
  },
  write_off: {
    short: "Write off",
    sentence: "Too small to chase — write it off",
  },
};

export function actionLabel(value: string | null | undefined): string {
  if (!value) return "—";
  return ACTION[value]?.sentence ?? humanise(value);
}

export function actionShortLabel(value: string | null | undefined): string {
  if (!value) return "—";
  return ACTION[value]?.short ?? humanise(value);
}

/* ------------------------------------------------------------------ */
/* audit trail: actor, step, action                                    */
/* ------------------------------------------------------------------ */

const ACTOR: Record<string, string> = {
  scheduler: "Scheduler",
  matcher: "Matcher",
  explainer: "Explainer",
  scorer: "Scorer",
  human: "Operator",
};

export function actorLabel(value: string | null | undefined): string {
  if (!value) return "—";
  return ACTOR[value] ?? humanise(value);
}

const STEP: Record<string, string> = {
  pipeline: "Pipeline",
  ingest_files: "File ingest",
  variance_explainer: "Explainer",
  explanation_audit: "Explanation audit",
  variance_queue: "Variance queue",
  console: "Console",
  rollup: "Daily rollup",
};

export function stepLabel(value: string | null | undefined): string {
  if (!value) return "—";
  return STEP[value] ?? humanise(value);
}

/**
 * Audit actions, written as what happened rather than as the event name.
 * Past tense throughout, because the trail is a record of things that
 * already happened.
 */
const ACTION_EVENT: Record<string, string> = {
  // pipeline
  batch_started: "Batch started",
  stage_enter: "Stage started",
  stage_exit: "Stage finished",
  stage_skipped: "Stage skipped — already done",
  stage_failed: "Stage failed",
  batch_failed: "Batch failed",
  batch_complete: "Batch completed",
  // scheduler
  scheduler_started: "Scheduler started",
  scheduler_stopping: "Scheduler stopping",
  poll_detected_activity: "Found new Razorpay activity",
  poll_no_activity: "Polled Razorpay — nothing new",
  poll_failed: "Could not reach Razorpay",
  poll_pipeline_finished: "Pipeline finished after polling",
  resuming_stuck_batch: "Resuming a stalled batch",
  resume_finished: "Stalled batch resumed",
  resume_nothing_stuck: "Checked for stalled batches — none",
  retry_unexplained_start: "Retrying unexplained variances",
  retry_unexplained_finished: "Retry finished",
  retry_unexplained_failed: "Retry failed",
  retry_nothing_unexplained: "Checked for unexplained variances — none",
  job_crashed: "Scheduled job crashed",
  daily_rollup: "Wrote the daily rollup",
};

export function eventLabel(value: string | null | undefined): string {
  if (!value) return "—";
  return ACTION_EVENT[value] ?? humanise(value);
}

/* ------------------------------------------------------------------ */
/* matching strategies                                                 */
/* ------------------------------------------------------------------ */

const STRATEGY: Record<string, string> = {
  exact_ref_amount_date: "Exact reference, amount and date",
  normalised_ref_windowed: "Normalised reference, within a date window",
  fee_reconstructed: "Fee and tax reconstructed",
  refund_linked: "Refund linked to its original payment",
  aggregate_settlement: "Many payments against one settlement",
};

export function strategyLabel(value: string | null | undefined): string {
  if (!value) return "—";
  // The funnel's first and last rows carry prose, not an enum.
  if (value.includes(" ")) return value;
  return STRATEGY[value] ?? humanise(value);
}

/* ------------------------------------------------------------------ */
/* scheduler jobs                                                      */
/* ------------------------------------------------------------------ */

const JOB: Record<string, string> = {
  poll_razorpay_activity: "Poll Razorpay for new activity",
  resume_stuck_batches: "Resume stalled batches",
  retry_unexplained_variances: "Retry unexplained variances",
  daily_rollup: "Write the daily rollup",
};

export function jobLabel(id: string, fallback: string): string {
  return JOB[id] ?? fallback ?? humanise(id);
}
