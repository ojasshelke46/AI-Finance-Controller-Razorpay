import Link from "next/link";

import { ErrorState, Metric, Panel, PanelHeader, Pill, varianceSeverity } from "@/components/primitives";
import { ApiError, getBatch, type FunnelStep } from "@/lib/api";
import { formatSeconds, sourceLabel } from "@/lib/format";
import { categoryLabel, strategyLabel, varianceStatusLabel } from "@/lib/gloss";
import { formatCount, formatPaise, formatPercent, formatRatio } from "@/lib/money";
import { cn } from "@/lib/utils";

export const dynamic = "force-dynamic";

export default async function BatchOverviewPage({ params }: PageProps<"/batches/[id]">) {
  const { id } = await params;

  let detail;
  try {
    detail = await getBatch(id);
  } catch (error) {
    const status = error instanceof ApiError ? error.status : undefined;
    return (
      <ErrorState
        title={status === 404 ? "Batch not found" : "Cannot load this batch"}
        detail={
          status === 404
            ? `No batch exists with id ${id}.`
            : error instanceof ApiError
              ? error.message
              : "Unknown error"
        }
        hint={status === 404 ? "Pick a batch from the batch list." : undefined}
      />
    );
  }

  const { score, funnel, totals, variances_by_status, variances_by_category, batch } = detail;
  const totalRecords = funnel[0]?.txns ?? 0;
  const unmatched = totals.txns - totals.matched_txns;

  return (
    <div className="space-y-4">
      {batch.error_text ? (
        <ErrorState
          title="This run failed"
          detail={batch.error_text}
          hint="The scheduler's resume job will retry it, skipping every stage that already completed."
        />
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,300px)]">
        {/* The funnel ---------------------------------------------------- */}
        <Panel>
          <PanelHeader
            title="Where the records went"
            description="Every record enters at the top. Each tier claims what it can prove, and the filled bar carries forward what earlier tiers already took — so the tail is what is still unclaimed."
            right={
              score?.wall_clock_seconds ? (
                <span className="num text-[11.5px] text-muted-foreground">
                  {formatSeconds(score.wall_clock_seconds)} wall clock
                </span>
              ) : null
            }
          />

          {funnel.length === 0 ? (
            <p className="px-4 py-6 text-[12px] text-muted-foreground">
              This batch has no records yet, so there is no funnel to draw.
            </p>
          ) : (
            <Funnel funnel={funnel} total={totalRecords} batchId={id} />
          )}

          <p className="border-t border-border px-4 py-2 text-[11.5px] text-muted-foreground">
            <span className="num">{formatCount(totals.matched_txns)}</span> of{" "}
            <span className="num">{formatCount(totals.txns)}</span> records matched into{" "}
            <span className="num">{formatCount(totals.match_groups)}</span> groups ·{" "}
            <span className="num">{formatCount(unmatched)}</span> unmatched
          </p>
        </Panel>

        {/* Alongside: what the operator owes, then how the run scored ---- */}
        <div className="space-y-4">
          <Panel>
            <PanelHeader
              title="Waiting on a person"
              right={
                <Link
                  href={`/batches/${id}/variances`}
                  className="text-[11.5px] text-accent underline-offset-2 hover:underline"
                >
                  Open the queue →
                </Link>
              }
            />
            <dl className="grid grid-cols-2 gap-x-6 gap-y-3 px-4 py-3">
              <Metric
                label="Unexplained"
                value={formatPaise(score?.unexplained_paise ?? 0)}
                severity={(score?.unexplained_paise ?? 0) > 0 ? "warn" : "ok"}
              />
              <Metric
                label="Open variances"
                value={formatCount(variances_by_status.open?.count ?? 0)}
                severity={(variances_by_status.open?.count ?? 0) > 0 ? "warn" : "ok"}
              />
            </dl>
            <ul className="divide-y divide-border border-t border-border">
              {Object.entries(variances_by_status).map(([status, stat]) => (
                <li
                  key={status}
                  className="flex items-center justify-between gap-2 px-4 py-1.5"
                >
                  <Pill severity={varianceSeverity(status)}>
                    {varianceStatusLabel(status)}
                  </Pill>
                  <span className="num text-right text-[12px]">
                    {formatCount(stat.count)}
                    <span className="ml-2 text-muted-foreground">
                      {formatPaise(stat.paise)}
                    </span>
                  </span>
                </li>
              ))}
              {Object.keys(variances_by_status).length === 0 ? (
                <li className="px-4 py-2 text-[12px] text-muted-foreground">
                  No variance was raised for this batch.
                </li>
              ) : null}
            </ul>
          </Panel>

          <Panel>
            <PanelHeader
              title="Run quality"
              description={
                score
                  ? "Scored pair by pair against ground truth. Precision is prioritised: a false match corrupts a ledger silently, an unmatched row only waits."
                  : "This run has not been scored yet."
              }
            />
            {score ? (
              <dl className="divide-y divide-border">
                <ScoreRow label="Precision" value={formatRatio(score.precision)} />
                <ScoreRow label="Recall" value={formatRatio(score.recall)} />
                <ScoreRow label="F1" value={formatRatio(score.f1)} />
                <ScoreRow label="Match rate" value={formatRatio(score.match_rate)} />
                <ScoreRow
                  label="Figures traced"
                  value={formatPercent(score.explanation_grounding_pct)}
                  hint="explanations whose every figure was found in the records"
                />
              </dl>
            ) : (
              <p className="px-4 py-4 text-[12px] text-muted-foreground">
                Scores appear once the run finishes and ground truth is available for the
                period.
              </p>
            )}
          </Panel>

          <Panel>
            <PanelHeader title="Records by source" />
            <ul className="divide-y divide-border">
              {Object.entries(totals.by_source).map(([kind, count]) => (
                <li
                  key={kind}
                  className="flex items-baseline justify-between px-4 py-1.5"
                >
                  <span className="text-[12.5px]">{sourceLabel(kind)}</span>
                  <span className="num text-[12.5px]">{formatCount(count)}</span>
                </li>
              ))}
              {Object.keys(totals.by_source).length === 0 ? (
                <li className="px-4 py-2 text-[12px] text-muted-foreground">
                  No records were ingested for this batch.
                </li>
              ) : null}
            </ul>
          </Panel>

          {Object.keys(variances_by_category).length > 0 ? (
            <Panel>
              <PanelHeader title="Variance by category" description="Largest value first" />
              <ul className="divide-y divide-border">
                {Object.entries(variances_by_category)
                  .sort((a, b) => b[1].paise - a[1].paise)
                  .map(([category, stat]) => (
                    <li
                      key={category}
                      className="flex items-baseline justify-between gap-2 px-4 py-1.5"
                    >
                      <Link
                        href={`/batches/${id}/variances?category=${encodeURIComponent(category)}`}
                        className="truncate text-[12px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
                      >
                        {categoryLabel(category)}
                      </Link>
                      <span className="num shrink-0 text-[11.5px]">
                        {formatCount(stat.count)} · {formatPaise(stat.paise)}
                      </span>
                    </li>
                  ))}
              </ul>
            </Panel>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function ScoreRow({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="px-4 py-1.5">
      <div className="flex items-baseline justify-between gap-3">
        <dt className="text-[12px] text-muted-foreground">{label}</dt>
        <dd className="num text-[12.5px] font-medium">{value}</dd>
      </div>
      {hint ? <p className="mt-0.5 text-[11px] text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

/**
 * One narrowing, not four bars.
 *
 * Every row shares the same full-width track, and each row's bar starts
 * where the tiers above it stopped: the spent portion stays as a quiet
 * rule, the tier's own claim is the solid block, and the empty tail is
 * what is still unclaimed at that point in the run. Read down the
 * column, the solid mass marches right and the tail shrinks to whatever
 * fell through to the queue.
 *
 * Grey carries the structure. The only colour is warn, on the residue
 * that a person still has to deal with.
 */
function Funnel({
  funnel,
  total,
  batchId,
}: {
  funnel: FunnelStep[];
  total: number;
  batchId: string;
}) {
  let claimed = 0;

  return (
    <ol className="relative px-4 py-3">
      {/* The rail. One line through every rung, so the steps read as a
          single descent rather than as stacked rows. */}
      <span
        aria-hidden
        className="absolute top-4 bottom-4 left-[19px] w-px bg-border"
      />
      {funnel.map((step) => {
        const before = total > 0 ? claimed / total : 0;
        const share = total > 0 ? step.txns / total : 0;
        if (step.kind === "tier") claimed += step.txns;
        return (
          <FunnelRung
            key={step.label}
            step={step}
            before={before}
            share={share}
            batchId={batchId}
          />
        );
      })}
    </ol>
  );
}

function FunnelRung({
  step,
  before,
  share,
  batchId,
}: {
  step: FunnelStep;
  before: number;
  share: number;
  batchId: string;
}) {
  const isTotal = step.kind === "total";
  const isVariance = step.kind === "variance";

  const body = (
    <>
      <div className="flex items-baseline justify-between gap-3">
        <span className={cn("text-[12.5px]", (isTotal || isVariance) && "font-medium", isVariance && "text-warn")}>
          {step.label}
          <span className="ml-2 text-[11px] text-muted-foreground">
            {strategyLabel(step.strategy)}
          </span>
        </span>
        <span className="num shrink-0 text-[12.5px]">
          {formatCount(step.txns)}
          <span className="ml-2 text-[11px] text-muted-foreground">
            {(share * 100).toFixed(1)}%
          </span>
        </span>
      </div>

      <div className="mt-1 flex h-1.5 w-full overflow-hidden rounded-[2px] bg-muted">
        {/* what earlier tiers already took */}
        <div className="h-full bg-border" style={{ width: `${before * 100}%` }} />
        {/* what this step claims */}
        <div
          className={cn("h-full", isVariance ? "bg-warn" : "bg-border-strong")}
          style={{ width: `${Math.max(share * 100, step.txns > 0 ? 0.6 : 0)}%` }}
        />
      </div>

      <div className="mt-1 flex items-baseline justify-between gap-3 text-[11px] text-muted-foreground">
        <span>{step.groups !== null ? `${formatCount(step.groups)} groups` : ""}</span>
        {step.residual_paise !== 0 ? (
          <span className="num">residual {formatPaise(step.residual_paise)}</span>
        ) : null}
      </div>
    </>
  );

  return (
    <li className="relative flex gap-3 py-1.5">
      <span
        aria-hidden
        className={cn(
          "relative z-10 mt-[5px] size-[7px] shrink-0 rounded-[1px] ring-2 ring-surface",
          isVariance ? "bg-warn" : "bg-border-strong",
        )}
      />
      {isVariance ? (
        <Link
          href={`/batches/${batchId}/variances`}
          className="block min-w-0 flex-1 rounded-sm px-1 hover:bg-muted/70"
        >
          {body}
        </Link>
      ) : (
        <div className="min-w-0 flex-1 px-1">{body}</div>
      )}
    </li>
  );
}
