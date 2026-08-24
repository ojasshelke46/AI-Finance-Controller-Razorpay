import Link from "next/link";

import { AutoRefresh } from "@/components/auto-refresh";
import {
  CopyableId,
  ErrorState,
  Metric,
  Panel,
  PanelHeader,
  Pill,
  StatusDot,
  batchSeverity,
} from "@/components/primitives";
import { ApiError, getStatus } from "@/lib/api";
import { formatDateTime, formatSeconds, formatTime, humanise, relativeTime } from "@/lib/format";
import { formatCount, formatPaise, formatPaiseCompact, formatPercent, formatRatio } from "@/lib/money";

export const dynamic = "force-dynamic";

/**
 * The autonomy proof. Everything here answers one question: is the
 * system doing the work without anyone touching it? So the scheduler
 * state, the last completed run, and the next scheduled run sit at the
 * top — a screenshot of this page should settle the question on its own.
 */
export default async function StatusPage() {
  let status;
  try {
    status = await getStatus();
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Unknown error";
    return (
      <ErrorState
        title="Cannot reach the reconciliation service"
        detail={message}
        hint="Start it with: cd api && uvicorn main:app --port 8000"
      />
    );
  }

  const {
    scheduler_running,
    jobs,
    next_run_at,
    last_run,
    batches_created_today,
    batches_completed_today,
    latest_score,
    unexplained_paise,
    open_variance_count,
    recent_events,
  } = status;

  const lastRunOk = last_run?.action === "batch_complete";

  return (
    <div className="space-y-4">
      <AutoRefresh seconds={30} />

      {/* Autonomy banner ------------------------------------------------ */}
      <Panel className={scheduler_running ? "border-ok/30" : "border-critical/40"}>
        <div className="flex flex-col gap-4 px-4 py-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-start gap-3">
            <StatusDot
              severity={scheduler_running ? "ok" : "critical"}
              live={scheduler_running}
              className="mt-[7px]"
            />
            <div>
              <h1 className="text-[15px] font-semibold tracking-tight">
                {scheduler_running
                  ? "Scheduler running — no operator input required"
                  : "Scheduler stopped"}
              </h1>
              <p className="mt-0.5 max-w-prose text-[12px] text-muted-foreground">
                {scheduler_running
                  ? "Polling Razorpay for new activity, resuming stalled batches, retrying unexplained variances and writing a daily rollup, all on a fixed schedule."
                  : "Nothing is being processed automatically. Start the API to resume autonomous operation."}
              </p>
            </div>
          </div>

          <dl className="grid shrink-0 grid-cols-2 gap-x-8 gap-y-3 sm:grid-cols-3">
            <Metric
              label="Last run"
              value={last_run ? relativeTime(last_run.at) : "—"}
              hint={
                last_run ? (
                  <span className="inline-flex items-center gap-1.5">
                    <StatusDot severity={lastRunOk ? "ok" : "critical"} />
                    {lastRunOk ? "completed" : "failed"} in{" "}
                    {formatSeconds(last_run.elapsed_seconds)}
                  </span>
                ) : (
                  "no completed run yet"
                )
              }
            />
            <Metric
              label="Next run"
              value={next_run_at ? relativeTime(next_run_at) : "—"}
              hint={next_run_at ? formatTime(next_run_at) : "scheduler idle"}
            />
            <Metric
              label="Batches today"
              value={formatCount(batches_created_today)}
              hint={`${formatCount(batches_completed_today)} completed`}
            />
          </dl>
        </div>
      </Panel>

      {/* Headline figures ---------------------------------------------- */}
      <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
        <Panel>
          <PanelHeader
            title="Unexplained exposure"
            description="Open variances across every batch — the money a human still needs to decide on."
            right={
              <Pill severity={open_variance_count > 0 ? "warn" : "ok"}>
                {formatCount(open_variance_count)} open
              </Pill>
            }
          />
          <div className="px-4 py-4">
            <Metric
              label="Total unexplained value"
              value={formatPaise(unexplained_paise)}
              size="lg"
              severity={unexplained_paise > 0 ? "warn" : "ok"}
              hint={
                unexplained_paise > 0
                  ? `${formatPaiseCompact(unexplained_paise)} sitting in the exception queue`
                  : "Everything reconciled"
              }
            />
          </div>
        </Panel>

        <Panel>
          <PanelHeader
            title="Most recent scored run"
            description={
              latest_score?.batch_id
                ? `Batch ${latest_score.batch_id.slice(0, 8)} · ${formatDateTime(latest_score.run_at)}`
                : "No run has been scored yet"
            }
            right={
              latest_score?.batch_id ? (
                <Link
                  href={`/batches/${latest_score.batch_id}`}
                  className="text-[12px] text-accent underline-offset-2 hover:underline"
                >
                  Open run →
                </Link>
              ) : null
            }
          />
          <dl className="grid grid-cols-2 gap-x-6 gap-y-4 px-4 py-4 sm:grid-cols-4">
            <Metric label="Match rate" value={formatRatio(latest_score?.match_rate)} />
            <Metric label="Precision" value={formatRatio(latest_score?.precision)} />
            <Metric label="Recall" value={formatRatio(latest_score?.recall)} />
            <Metric
              label="Grounding"
              value={formatPercent(latest_score?.explanation_grounding_pct)}
              hint="explanations verified"
            />
          </dl>
        </Panel>
      </div>

      {/* Jobs + event stream ------------------------------------------- */}
      <div className="grid gap-4 lg:grid-cols-[minmax(0,340px)_minmax(0,1fr)]">
        <Panel>
          <PanelHeader title="Scheduled jobs" description="Cadence and next fire time" />
          {jobs.length === 0 ? (
            <p className="px-4 py-6 text-[12px] text-muted-foreground">
              No jobs registered. The scheduler is not running.
            </p>
          ) : (
            <ul className="divide-y divide-border">
              {jobs.map((job) => (
                <li key={job.id} className="flex items-baseline justify-between gap-3 px-4 py-2">
                  <span className="min-w-0 truncate text-[12.5px]">{job.name}</span>
                  <span className="num shrink-0 text-[11.5px] text-muted-foreground">
                    {job.next_run_at ? relativeTime(job.next_run_at) : "paused"}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <Panel>
          <PanelHeader
            title="Live activity"
            description="Newest audit events across all batches, written by the system as it works"
          />
          {recent_events.length === 0 ? (
            <p className="px-4 py-6 text-[12px] text-muted-foreground">
              Nothing recorded yet. Events appear here as soon as the scheduler picks up work.
            </p>
          ) : (
            <ul className="divide-y divide-border">
              {recent_events.map((event, index) => (
                <li
                  key={`${event.created_at}-${index}`}
                  // Fixed columns only from sm up. At 375px the
                  // 60px + 88px + content + id row overflows the
                  // viewport and pushes the whole page sideways, so on
                  // phones it wraps instead.
                  className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 px-4 py-1.5 sm:grid sm:grid-cols-[60px_88px_1fr_auto]"
                >
                  <span className="num text-[11.5px] text-muted-foreground">
                    {formatTime(event.created_at)}
                  </span>
                  <Pill severity={event.actor === "human" ? "info" : "neutral"}>
                    {event.actor}
                  </Pill>
                  <span className="min-w-0 truncate text-[12px]">
                    {humanise(event.action)}
                    <span className="ml-2 text-[11.5px] text-muted-foreground">
                      {event.step}
                    </span>
                  </span>
                  {event.batch_id ? (
                    <CopyableId id={event.batch_id} href={`/batches/${event.batch_id}`} />
                  ) : (
                    <span className="text-[11.5px] text-muted-foreground">—</span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </div>
  );
}
