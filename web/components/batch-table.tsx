"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { DataTable, Pill, Td, Th, batchSeverity } from "@/components/primitives";
import type { BatchSummary } from "@/lib/api";
import { formatDateTime, relativeTime } from "@/lib/format";
import { useMounted } from "@/lib/use-mounted";
import { batchStatusLabel } from "@/lib/gloss";
import { formatCount, formatPaise, formatRatio } from "@/lib/money";
import { cn } from "@/lib/utils";

/** The scheduler treats a batch as stuck when it is not in a terminal
 *  state and nothing has been written about it for 30 minutes
 *  (api/runtime/scheduler.py, STUCK_AFTER_MINUTES). The list only knows
 *  when a batch was created, so this is the same threshold measured from
 *  the only timestamp available here — and the label says so. */
const STALLED_AFTER_MS = 30 * 60 * 1000;
const TERMINAL = new Set(["complete", "failed"]);

function isStalled(batch: BatchSummary, now: number): boolean {
  if (TERMINAL.has(batch.status)) return false;
  return now - new Date(batch.created_at).getTime() > STALLED_AFTER_MS;
}

type SortKey = "created" | "unexplained" | "open" | "records";

export function BatchTable({ batches }: { batches: BatchSummary[] }) {
  const [sortKey, setSortKey] = useState<SortKey>("created");
  const [ascending, setAscending] = useState(false);

  // Fixed at render so every row is judged against the same instant.
  const mounted = useMounted();
  // Date.now() differs between the server render and hydration a moment
  // later, and relativeTime's sub-45s bucket changes every second, so
  // nothing derived from it may be rendered before mount.
  const now = useMemo(() => Date.now(), []);

  const failed = batches.filter((b) => b.status === "failed");
  const stalled = batches.filter((b) => isStalled(b, now));
  const totalUnexplained = batches.reduce((sum, b) => sum + (b.unexplained_paise ?? 0), 0);
  const totalOpen = batches.reduce((sum, b) => sum + b.open_variance_count, 0);

  const sorted = useMemo(() => {
    const value = (batch: BatchSummary) => {
      switch (sortKey) {
        case "unexplained":
          return batch.unexplained_paise ?? 0;
        case "open":
          return batch.open_variance_count;
        case "records":
          return batch.txn_count;
        default:
          return new Date(batch.created_at).getTime();
      }
    };
    return [...batches].sort((a, b) => (ascending ? value(a) - value(b) : value(b) - value(a)));
  }, [batches, sortKey, ascending]);

  function toggleSort(key: SortKey) {
    if (key === sortKey) {
      setAscending((current) => !current);
    } else {
      setSortKey(key);
      setAscending(false);
    }
  }

  return (
    <>
      {/* What is wrong, before what is merely recent. */}
      <dl className="flex flex-wrap items-baseline gap-x-8 gap-y-2 border-b border-border px-4 py-2.5">
        <Summary
          label="Failed"
          value={formatCount(failed.length)}
          severity={failed.length > 0 ? "critical" : undefined}
          hint={failed.length > 0 ? "will not finish without help" : "none"}
        />
        <Summary
          label="Stalled"
          value={formatCount(stalled.length)}
          severity={stalled.length > 0 ? "warn" : undefined}
          hint={
            stalled.length > 0 ? "running over 30 minutes" : "none"
          }
        />
        <Summary
          label="Open variances"
          value={formatCount(totalOpen)}
          severity={totalOpen > 0 ? "warn" : undefined}
        />
        <Summary
          label="Unexplained value"
          value={formatPaise(totalUnexplained)}
          severity={totalUnexplained > 0 ? "warn" : undefined}
          hint="across every batch"
        />
      </dl>

      <DataTable
        head={
          <>
            <Th>Batch</Th>
            <Th>Status</Th>
            <Th>Period</Th>
            <Th align="right">
              <SortButton
                active={sortKey === "records"}
                ascending={ascending}
                onClick={() => toggleSort("records")}
              >
                Records
              </SortButton>
            </Th>
            <Th align="right">Match rate</Th>
            <Th align="right">Precision</Th>
            <Th align="right">
              <SortButton
                active={sortKey === "open"}
                ascending={ascending}
                onClick={() => toggleSort("open")}
              >
                Open
              </SortButton>
            </Th>
            <Th align="right">
              <SortButton
                active={sortKey === "unexplained"}
                ascending={ascending}
                onClick={() => toggleSort("unexplained")}
              >
                Unexplained
              </SortButton>
            </Th>
            <Th align="right">
              <SortButton
                active={sortKey === "created"}
                ascending={ascending}
                onClick={() => toggleSort("created")}
              >
                Created
              </SortButton>
            </Th>
          </>
        }
      >
        {sorted.map((batch) => {
          const stalledRow = isStalled(batch, now);
          const failedRow = batch.status === "failed";
          return (
            <tr
              key={batch.id}
              className={cn(
                "border-b border-border last:border-0",
                failedRow && "bg-critical-bg/50 hover:bg-critical-bg",
                stalledRow && "bg-warn-bg/50 hover:bg-warn-bg",
                !failedRow && !stalledRow && "hover:bg-muted/50",
              )}
            >
              <Td>
                <Link
                  href={`/batches/${batch.id}`}
                  className="group inline-flex flex-col focus-visible:outline-none"
                >
                  <span className="text-[12.5px] font-medium text-accent underline-offset-2 group-hover:underline">
                    {batch.label ?? "Unlabelled batch"}
                  </span>
                  <span className="num text-[11px] text-muted-foreground">
                    {batch.id.slice(0, 8)}
                  </span>
                </Link>
              </Td>
              <Td>
                <div className="flex flex-col items-start gap-0.5">
                  <Pill severity={stalledRow ? "warn" : batchSeverity(batch.status)}>
                    {stalledRow ? "Stalled" : batchStatusLabel(batch.status)}
                  </Pill>
                  {failedRow && batch.error_text ? (
                    <span
                      className="block max-w-[220px] truncate text-[11px] text-critical"
                      title={batch.error_text}
                    >
                      {batch.error_text}
                    </span>
                  ) : null}
                  {stalledRow ? (
                    <span className="block text-[11px] text-warn">
                      no finish after{" "}
                      {mounted ? relativeTime(batch.created_at, now).replace(" ago", "") : "—"}
                    </span>
                  ) : null}
                </div>
              </Td>
              <Td className="num text-[11.5px] whitespace-nowrap text-muted-foreground">
                {batch.period_start && batch.period_end
                  ? `${batch.period_start} → ${batch.period_end}`
                  : "—"}
              </Td>
              <Td align="right" mono>
                {formatCount(batch.txn_count)}
              </Td>
              <Td align="right" mono>
                {formatRatio(batch.match_rate)}
              </Td>
              <Td align="right" mono>
                {formatRatio(batch.precision)}
              </Td>
              <Td align="right" mono>
                {batch.open_variance_count > 0 ? (
                  <Link
                    href={`/batches/${batch.id}/variances?status=open`}
                    className="text-warn underline-offset-2 hover:underline"
                  >
                    {formatCount(batch.open_variance_count)}
                  </Link>
                ) : (
                  <span className="text-muted-foreground">0</span>
                )}
              </Td>
              <Td
                align="right"
                mono
                className={batch.unexplained_paise > 0 ? "text-warn" : undefined}
              >
                {formatPaise(batch.unexplained_paise)}
              </Td>
              <Td
                align="right"
                className="num text-[11.5px] whitespace-nowrap text-muted-foreground"
                title={mounted ? formatDateTime(batch.created_at) : undefined}
              >
                {mounted ? relativeTime(batch.created_at, now) : "—"}
              </Td>
            </tr>
          );
        })}
      </DataTable>
    </>
  );
}

function Summary({
  label,
  value,
  hint,
  severity,
}: {
  label: string;
  value: string;
  hint?: string;
  severity?: "warn" | "critical";
}) {
  return (
    <div className="flex items-baseline gap-2">
      <dt className="label">{label}</dt>
      <dd
        className={cn(
          "num text-[13px] font-medium",
          severity === "warn" && "text-warn",
          severity === "critical" && "text-critical",
        )}
      >
        {value}
      </dd>
      {hint ? <span className="text-[11px] text-muted-foreground">{hint}</span> : null}
    </div>
  );
}

function SortButton({
  children,
  active,
  ascending,
  onClick,
}: {
  children: React.ReactNode;
  active: boolean;
  ascending: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-sort={active ? (ascending ? "ascending" : "descending") : "none"}
      className={cn(
        "label inline-flex items-center gap-1 hover:text-foreground",
        active && "text-foreground",
      )}
    >
      {children}
      <span aria-hidden className="text-[9px]">
        {active ? (ascending ? "▲" : "▼") : "▾"}
      </span>
    </button>
  );
}
