import Link from "next/link";

import {
  ErrorState,
  Metric,
  Panel,
  PanelHeader,
  Pill,
  varianceSeverity,
} from "@/components/primitives";
import { ApiError, getBatch, type FunnelStep } from "@/lib/api";
import { formatSeconds, humanise, sourceLabel } from "@/lib/format";
import { formatCount, formatPaise, formatPercent, formatRatio } from "@/lib/money";

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
        hint={status === 404 ? "Pick a batch from the batches list." : undefined}
      />
    );
  }

  const { score, funnel, totals, variances_by_status, variances_by_category, batch } = detail;
  const totalRecords = funnel[0]?.txns ?? 0;

  return (
    <div className="space-y-4">
      {batch.error_text ? (
        <ErrorState
          title="This run failed"
          detail={batch.error_text}
          hint="The scheduler's resume job will retry it, skipping every stage that already completed."
        />
      ) : null}

      {/* Scores --------------------------------------------------------- */}
      <Panel>
        <PanelHeader
          title="Run quality"
          description={
            score
              ? "Pair-level scoring against ground truth. Precision is prioritised: a false match silently corrupts a ledger, an unmatched row only waits in a queue."
              : "This run has not been scored yet."
          }
          right={
            score?.wall_clock_seconds ? (
              <span className="num text-[11.5px] text-muted-foreground">
                {formatSeconds(score.wall_clock_seconds)} wall clock
              </span>
            ) : null
          }
        />
        <dl className="grid grid-cols-2 gap-x-6 gap-y-4 px-4 py-4 sm:grid-cols-3 lg:grid-cols-6">
          <Metric label="Precision" value={formatRatio(score?.precision)} size="lg" />
          <Metric label="Recall" value={formatRatio(score?.recall)} size="lg" />
          <Metric label="F1" value={formatRatio(score?.f1)} size="lg" />
          <Metric
            label="Grounding"
            value={formatPercent(score?.explanation_grounding_pct)}
            hint="explanations that passed audit"
          />
          <Metric label="Match rate" value={formatRatio(score?.match_rate)} />
          <Metric
            label="Unexplained"
            value={formatPaise(score?.unexplained_paise ?? 0)}
            severity={(score?.unexplained_paise ?? 0) > 0 ? "warn" : "ok"}
          />
        </dl>
      </Panel>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,340px)]">
        {/* Funnel ------------------------------------------------------ */}
        <Panel>
          <PanelHeader
            title="Tier contribution"
            description="Every record enters at the top. Each tier claims what it can prove, and whatever no tier could claim falls through to the variance queue."
          />
          <div className="space-y-1 px-4 py-4">
            {funnel.map((step) => (
              <FunnelRow key={step.label} step={step} total={totalRecords} batchId={id} />
            ))}
          </div>
          <div className="border-t border-border px-4 py-2.5">
            <p className="text-[11.5px] text-muted-foreground">
              {formatCount(totals.matched_txns)} of {formatCount(totals.txns)} records matched
              into {formatCount(totals.match_groups)} groups ·{" "}
              {formatCount(totals.txns - totals.matched_txns)} unmatched
            </p>
          </div>
        </Panel>

        {/* Composition ------------------------------------------------- */}
        <div className="space-y-4">
          <Panel>
            <PanelHeader title="Records by source" />
            <ul className="divide-y divide-border">
              {Object.entries(totals.by_source).map(([kind, count]) => (
                <li key={kind} className="flex items-baseline justify-between px-4 py-2">
                  <span className="text-[12.5px]">{sourceLabel(kind)}</span>
                  <span className="num text-[12.5px]">{formatCount(count)}</span>
                </li>
              ))}
              {Object.keys(totals.by_source).length === 0 ? (
                <li className="px-4 py-3 text-[12px] text-muted-foreground">
                  No records ingested.
                </li>
              ) : null}
            </ul>
          </Panel>

          <Panel>
            <PanelHeader
              title="Variance queue"
              description="By status, then by category"
              right={
                <Link
                  href={`/batches/${id}/variances`}
                  className="text-[12px] text-accent underline-offset-2 hover:underline"
                >
                  Open queue →
                </Link>
              }
            />
            <ul className="divide-y divide-border">
              {Object.entries(variances_by_status).map(([status, stat]) => (
                <li key={status} className="flex items-center justify-between gap-2 px-4 py-2">
                  <Pill severity={varianceSeverity(status)}>{humanise(status)}</Pill>
                  <span className="num text-right text-[12px]">
                    {formatCount(stat.count)}
                    <span className="ml-2 text-muted-foreground">
                      {formatPaise(stat.paise)}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
            {Object.keys(variances_by_category).length > 0 ? (
              <ul className="divide-y divide-border border-t border-border">
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
                        {humanise(category)}
                      </Link>
                      <span className="num shrink-0 text-[11.5px]">
                        {formatCount(stat.count)} · {formatPaise(stat.paise)}
                      </span>
                    </li>
                  ))}
              </ul>
            ) : null}
          </Panel>
        </div>
      </div>
    </div>
  );
}

/**
 * One rung of the funnel. The bar is proportional to the share of total
 * records the step accounts for, so the shape of the run is legible
 * without reading a single number — and the numbers are there when you
 * do read.
 */
function FunnelRow({
  step,
  total,
  batchId,
}: {
  step: FunnelStep;
  total: number;
  batchId: string;
}) {
  const share = total > 0 ? step.txns / total : 0;
  const isTotal = step.kind === "total";
  const isVariance = step.kind === "variance";

  const bar = isTotal
    ? "bg-border-strong"
    : isVariance
      ? "bg-warn"
      : "bg-accent";

  const content = (
    <>
      <div className="flex items-baseline justify-between gap-3">
        <span
          className={
            isTotal
              ? "text-[12.5px] font-medium"
              : isVariance
                ? "text-[12.5px] font-medium text-warn"
                : "text-[12.5px]"
          }
        >
          {step.label}
          <span className="ml-2 text-[11px] text-muted-foreground">{step.strategy}</span>
        </span>
        <span className="num shrink-0 text-[12.5px] tabular-nums">
          {formatCount(step.txns)}
          <span className="ml-2 text-[11px] text-muted-foreground">
            {(share * 100).toFixed(1)}%
          </span>
        </span>
      </div>
      <div className="mt-1 h-1.5 w-full overflow-hidden rounded-[2px] bg-muted">
        <div
          className={`h-full ${bar}`}
          style={{ width: `${Math.max(share * 100, step.txns > 0 ? 0.6 : 0)}%` }}
        />
      </div>
      <div className="mt-1 flex items-baseline justify-between gap-3 text-[11px] text-muted-foreground">
        <span>
          {step.groups !== null ? `${formatCount(step.groups)} groups` : " "}
        </span>
        {step.residual_paise !== 0 ? (
          <span className="num">residual {formatPaise(step.residual_paise)}</span>
        ) : null}
      </div>
    </>
  );

  if (isVariance) {
    return (
      <Link
        href={`/batches/${batchId}/variances`}
        className="block rounded-sm px-1 py-1.5 transition-colors hover:bg-muted/70"
      >
        {content}
      </Link>
    );
  }

  return <div className="px-1 py-1.5">{content}</div>;
}
