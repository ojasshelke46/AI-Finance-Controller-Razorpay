import Link from "next/link";

import { AutoRefresh } from "@/components/auto-refresh";
import { LiveFigure } from "@/components/live-figure";
import {
  CopyableId,
  ErrorState,
  Metric,
  Panel,
  PanelHeader,
  Pill,
  StatusDot,
} from "@/components/primitives";
import { ApiError, getStatus } from "@/lib/api";
import { formatSeconds, formatTime, relativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { actorLabel, eventLabel, eventTone, jobLabel, stepLabel } from "@/lib/gloss";
import { formatCount, formatPaise, formatPercent, formatRatio } from "@/lib/money";

export const dynamic = "force-dynamic";

/**
 * The autonomy proof. This page answers one question — is the system
 * doing the work without anyone touching it — and everything at the top
 * is evidence for that answer: when the scheduler itself last ticked,
 * the last batch that actually completed, the next one already
 * scheduled, and how many of the recent events a person caused.
 *
 * "Scheduler last active" and "Last batch completed" answer different
 * questions and can legitimately disagree by hours: the scheduler ticks
 * every ~15 minutes and most ticks find nothing new to do, which is a
 * successful tick, not evidence of stalling. A single "last run" figure
 * conflated the two and read as broken on any quiet day.
 *
 * Money lives below that line. It matters, but it is not what this page
 * is for, and when it took the largest figure on the screen it argued
 * the opposite of the page's own claim.
 */
export default async function StatusPage() {
  let status;
  try {
    status = await getStatus();
  } catch (error) {
    return (
      <ErrorState
        title="Cannot reach the reconciliation service"
        detail={error instanceof ApiError ? error.message : "Unknown error"}
        hint="This page retries every 30 seconds. If it stays unreachable, the service needs restarting."
      />
    );
  }

  const {
    scheduler_running,
    scheduler_last_active_at,
    jobs,
    next_run_at,
    last_run,
    batches_created_today,
    batches_completed_today,
    latest_score,
    unexplained_paise,
    open_variance_count,
    recent_events,
    server_time,
  } = status;

  const lastRunOk = last_run?.action === "batch_complete";
  const operatorEvents = recent_events.filter((event) => event.actor === "human").length;

  return (
    <div className="space-y-5">
      {/* Autonomy ------------------------------------------------------- */}
      <section aria-labelledby="autonomy" className="border-b border-border-strong pb-5">
        <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-2">
          <div className="flex items-start gap-2.5">
            <StatusDot
              severity={scheduler_running ? "ok" : "critical"}
              className="mt-[7px]"
            />
            <div>
              <h1 id="autonomy" className="text-[15px] font-semibold tracking-tight">
                {scheduler_running
                  ? "Running unattended"
                  : "Stopped — nothing is being processed"}
              </h1>
              <p className="mt-0.5 max-w-prose text-[12px] text-muted-foreground">
                {scheduler_running
                  ? "Polling Razorpay, resuming stalled batches, retrying unexplained variances and writing a daily rollup, all on a fixed schedule."
                  : "No work is being picked up. Restart the reconciliation service to resume."}
              </p>
            </div>
          </div>
          <AutoRefresh seconds={30} asOf={server_time} />
        </div>

        <dl className="mt-4 grid grid-cols-2 gap-x-8 gap-y-4 sm:grid-cols-5">
          {/* Answers "is this actually alive right now", independent of
           *  whether there was anything to do. The scheduler ticks every
           *  ~15 minutes and most ticks find nothing new — "Polled
           *  Razorpay, nothing new" is a successful tick, not an idle
           *  system. Without this, "Last batch completed" (which only
           *  moves when real work happens, and is honestly hours old on
           *  a quiet day) was the only recency figure on the page, and
           *  read as the automation having stopped. */}
          <Metric
            label="Scheduler last active"
            size="lg"
            value={
              <LiveFigure value={scheduler_last_active_at ?? "none"}>
                {scheduler_last_active_at ? relativeTime(scheduler_last_active_at) : "—"}
              </LiveFigure>
            }
            severity={!scheduler_running ? "critical" : undefined}
            hint={
              scheduler_last_active_at ? (
                <>
                  ticks every 15m ·{" "}
                  <span className="num">{formatTime(scheduler_last_active_at)}</span>
                </>
              ) : (
                "no tick recorded yet"
              )
            }
          />
          <Metric
            label="Last batch completed"
            size="lg"
            value={
              <LiveFigure value={last_run?.at ?? "none"}>
                {last_run ? relativeTime(last_run.at) : "—"}
              </LiveFigure>
            }
            severity={last_run && !lastRunOk ? "critical" : undefined}
            hint={
              last_run ? (
                <>
                  {eventLabel(last_run.action)} · {formatSeconds(last_run.elapsed_seconds)} ·{" "}
                  <span className="num">{formatTime(last_run.at)}</span>
                </>
              ) : (
                "no run has finished yet"
              )
            }
          />
          <Metric
            label="Next run due"
            size="lg"
            value={
              <LiveFigure value={next_run_at ?? "none"}>
                {next_run_at ? relativeTime(next_run_at) : "—"}
              </LiveFigure>
            }
            hint={
              next_run_at ? (
                <span className="num">{formatTime(next_run_at)}</span>
              ) : (
                "nothing scheduled"
              )
            }
          />
          <Metric
            label="Runs today"
            value={
              <LiveFigure value={String(batches_created_today)}>
                {formatCount(batches_created_today)}
              </LiveFigure>
            }
            hint={`${formatCount(batches_completed_today)} finished`}
          />
          <Metric
            label="Operator actions"
            value={
              <LiveFigure value={String(operatorEvents)}>
                {formatCount(operatorEvents)}
              </LiveFigure>
            }
            severity={operatorEvents === 0 ? "ok" : "info"}
            hint={
              operatorEvents === 0
                ? `none in the last ${formatCount(recent_events.length)} events`
                : `of the last ${formatCount(recent_events.length)} events`
            }
          />
        </dl>
      </section>

      {/* Where the work stands ------------------------------------------ */}
      <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <section aria-labelledby="exposure">
          <h2 id="exposure" className="label mb-2.5">
            Waiting on a person
          </h2>
          <dl className="grid grid-cols-2 gap-x-8 gap-y-3">
            <Metric
              label="Unexplained value"
              value={
                <LiveFigure value={String(unexplained_paise)}>
                  {formatPaise(unexplained_paise)}
                </LiveFigure>
              }
              severity={unexplained_paise > 0 ? "warn" : "ok"}
              hint="across every batch"
            />
            <Metric
              label="Open variances"
              value={
                <LiveFigure value={String(open_variance_count)}>
                  {formatCount(open_variance_count)}
                </LiveFigure>
              }
              severity={open_variance_count > 0 ? "warn" : "ok"}
              hint={
                open_variance_count > 0 ? (
                  <Link
                    href="/batches"
                    className="text-accent underline-offset-2 hover:underline"
                  >
                    Find them in the batch list
                  </Link>
                ) : (
                  "nothing to decide"
                )
              }
            />
          </dl>
        </section>

        <section aria-labelledby="scored">
          <h2 id="scored" className="label mb-2.5 flex items-baseline justify-between gap-3">
            Most recent scored run
            {latest_score?.batch_id ? (
              <Link
                href={`/batches/${latest_score.batch_id}`}
                className="text-[11.5px] tracking-normal text-accent normal-case underline-offset-2 hover:underline"
              >
                Open batch <span className="num">{latest_score.batch_id.slice(0, 8)}</span>
              </Link>
            ) : null}
          </h2>
          {latest_score ? (
            <>
              {/* Name the batch these figures came from. A bare uuid gives
               *  a reader no way to tell which run is being quoted. */}
              {latest_score.label ? (
                <p className="mb-2.5 text-[12px] text-muted-foreground">
                  {latest_score.label}
                </p>
              ) : null}
              <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
                <Metric label="Match rate" value={formatRatio(latest_score.match_rate)} />
                <Metric label="Precision" value={formatRatio(latest_score.precision)} />
                <Metric label="Recall" value={formatRatio(latest_score.recall)} />
                <Metric
                  label="Grounding"
                  value={formatPercent(latest_score.explanation_grounding_pct)}
                  hint="figures traced"
                />
              </dl>
            </>
          ) : (
            <p className="text-[12px] text-muted-foreground">
              No scored reconciliation run yet. Chaos tests and single-source auto-poll
              batches are left out of this figure, so it appears once a batch finishes
              with more than one source and ground truth available.
            </p>
          )}
        </section>
      </div>

      {/* Evidence ------------------------------------------------------- */}
      <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,340px)_minmax(0,1fr)]">
        <Panel>
          <PanelHeader title="Scheduled jobs" description="What runs, and when it runs next" />
          {jobs.length === 0 ? (
            <p className="px-4 py-6 text-[12px] text-muted-foreground">
              No jobs are registered. The scheduler is not running.
            </p>
          ) : (
            <ul className="divide-y divide-border">
              {jobs.map((job) => (
                <li
                  key={job.id}
                  className="flex items-baseline justify-between gap-3 px-4 py-1.5"
                >
                  <span className="min-w-0 truncate text-[12.5px]">
                    {jobLabel(job.id, job.name)}
                  </span>
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
            title="Recent activity"
            description="The newest events across every batch, written by the system as it works"
            right={
              <span className="num text-[11.5px] text-muted-foreground">
                {formatCount(recent_events.length)} events
              </span>
            }
          />
          {recent_events.length === 0 ? (
            <p className="px-4 py-6 text-[12px] text-muted-foreground">
              Nothing recorded yet. Events appear here as soon as the scheduler picks up
              work.
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
                  className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 px-4 py-1.5 sm:grid sm:grid-cols-[60px_84px_1fr_auto]"
                >
                  <time
                    dateTime={event.created_at}
                    className="num text-[11.5px] text-muted-foreground"
                  >
                    {formatTime(event.created_at)}
                  </time>
                  <Pill severity={event.actor === "human" ? "info" : "neutral"}>
                    {actorLabel(event.actor)}
                  </Pill>
                  <span className={cn("min-w-0 truncate text-[12px]", eventTone(event.action))}>
                    {eventLabel(event.action)}
                    <span className="ml-2 text-[11.5px] text-muted-foreground">
                      {stepLabel(event.step)}
                    </span>
                  </span>
                  {event.batch_id ? (
                    <CopyableId id={event.batch_id} href={`/batches/${event.batch_id}`} />
                  ) : (
                    <span className="num text-[11.5px] text-muted-foreground">—</span>
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
