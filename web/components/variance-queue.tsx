"use client";

import { useMemo, useOptimistic, useState, useTransition, type ReactNode } from "react";

import {
  DataTable,
  EmptyState,
  Panel,
  PanelHeader,
  Pill,
  Td,
  Th,
  varianceSeverity,
} from "@/components/primitives";
import { actOnVariance, type TxnRecord, type Variance } from "@/lib/api";
import { figureKey, markFigures, TRACED_MARK } from "@/lib/figures";
import { formatDate, humanise, sourceLabel } from "@/lib/format";
import {
  actionLabel,
  categoryLabel,
  strategyLabel,
  varianceStatusLabel,
} from "@/lib/gloss";
import { formatCount, formatPaise, formatRatio } from "@/lib/money";
import { cn } from "@/lib/utils";

type SortKey = "value" | "confidence";

/** Undecided work outranks decided work, whatever it is worth. Sorting
 *  purely by value let a settled ₹5,00,000 row sit above an open
 *  ₹4,00,000 one, which put the queue's own answer to "what next" below
 *  a row nobody has to look at again. */
const URGENCY: Record<string, number> = {
  open: 0,
  explained: 1,
  accepted: 2,
  written_off: 2,
};

function urgency(status: string): number {
  return URGENCY[status] ?? 1;
}

export function VarianceQueue({
  variances,
  categories,
  batchId,
  activeCategory,
  activeStatus,
}: {
  variances: Variance[];
  categories: string[];
  batchId: string;
  activeCategory?: string;
  activeStatus?: string;
}) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("value");
  const [ascending, setAscending] = useState(false);

  // Optimistic status so a decision lands instantly; the server write is
  // still authoritative and a failure rolls the row back with a message.
  const [optimistic, applyOptimistic] = useOptimistic(
    variances,
    (current: Variance[], update: { id: string; status: string }) =>
      current.map((v) => (v.id === update.id ? { ...v, status: update.status } : v)),
  );

  const sorted = useMemo(() => {
    const copy = [...optimistic];
    copy.sort((a, b) => {
      const byUrgency = urgency(a.status) - urgency(b.status);
      if (byUrgency !== 0) return byUrgency;
      const delta =
        sortKey === "value"
          ? Math.abs(a.variance_paise) - Math.abs(b.variance_paise)
          : (a.confidence ?? -1) - (b.confidence ?? -1);
      return ascending ? delta : -delta;
    });
    return copy;
  }, [optimistic, sortKey, ascending]);

  const undecided = optimistic.filter((v) => urgency(v.status) < 2);
  const openCount = optimistic.filter((v) => v.status === "open").length;
  const undecidedValue = undecided.reduce((sum, v) => sum + Math.abs(v.variance_paise), 0);
  const largestUndecided = undecided.reduce(
    (max, v) => Math.max(max, Math.abs(v.variance_paise)),
    0,
  );

  function toggleSort(key: SortKey) {
    if (key === sortKey) {
      setAscending((value) => !value);
    } else {
      setSortKey(key);
      setAscending(false);
    }
  }

  return (
    <Panel>
      <PanelHeader
        title="Variance queue"
        description="Every discrepancy the matcher could not settle on its own. Undecided first, then largest value. Expand a row for the records behind it and how the conclusion was reached."
      />

      {/* The queue's own headline: what is still undecided, and how big
          the worst of it is. Stated once here rather than left for the
          operator to find by reading down the value column. */}
      <dl className="flex flex-wrap items-baseline gap-x-8 gap-y-2 border-b border-border px-4 py-2.5">
        <Figure
          label="Still undecided"
          value={formatCount(undecided.length)}
          severity={openCount > 0 ? "warn" : undefined}
          hint={`of ${formatCount(optimistic.length)} shown`}
        />
        <Figure
          label="Undecided value"
          value={formatPaise(undecidedValue)}
          severity={undecidedValue > 0 ? "warn" : undefined}
        />
        <Figure
          label="Largest single"
          value={formatPaise(largestUndecided)}
          severity={largestUndecided > 0 ? "warn" : undefined}
          hint={undecided.length > 0 ? "top of the queue" : undefined}
        />
      </dl>

      <Filters
        batchId={batchId}
        categories={categories}
        activeCategory={activeCategory}
        activeStatus={activeStatus}
      />

      {sorted.length === 0 ? (
        <EmptyState
          title={
            activeCategory || activeStatus
              ? "Nothing matches these filters"
              : "Nothing in the queue"
          }
          description={
            activeCategory || activeStatus
              ? "No variance in this batch has that combination of status and category. Clear the filters to see the whole queue."
              : "Every record in this batch reconciled cleanly. There is nothing for an operator to decide."
          }
        />
      ) : (
        <DataTable
          head={
            <>
              <Th className="w-8" />
              <Th align="right">
                <SortButton
                  active={sortKey === "value"}
                  ascending={ascending}
                  onClick={() => toggleSort("value")}
                >
                  Value
                </SortButton>
              </Th>
              <Th>Category</Th>
              <Th>What the system found</Th>
              <Th align="right">
                <SortButton
                  active={sortKey === "confidence"}
                  ascending={ascending}
                  onClick={() => toggleSort("confidence")}
                >
                  Confidence
                </SortButton>
              </Th>
              <Th>Suggested action</Th>
              <Th>Status</Th>
              <Th align="right">Decide</Th>
            </>
          }
        >
          {sorted.map((variance) => (
            <VarianceRow
              key={variance.id}
              variance={variance}
              expanded={expanded === variance.id}
              onToggle={() =>
                setExpanded((current) => (current === variance.id ? null : variance.id))
              }
              applyOptimistic={applyOptimistic}
            />
          ))}
        </DataTable>
      )}
    </Panel>
  );
}

/** A label and a figure on one baseline. Used only in the queue's
 *  summary strip, where three of them sit in a row — never alone, and
 *  never inside a container of its own. */
function Figure({
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
  children: ReactNode;
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

function Filters({
  batchId,
  categories,
  activeCategory,
  activeStatus,
}: {
  batchId: string;
  categories: string[];
  activeCategory?: string;
  activeStatus?: string;
}) {
  const base = `/batches/${batchId}/variances`;
  const statuses = ["open", "explained", "accepted", "written_off"];

  const link = (params: { category?: string; status?: string }) => {
    const search = new URLSearchParams();
    if (params.category) search.set("category", params.category);
    if (params.status) search.set("status", params.status);
    const qs = search.toString();
    return qs ? `${base}?${qs}` : base;
  };

  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-b border-border px-4 py-2.5">
      <FilterGroup label="Status">
        <FilterChip href={link({ category: activeCategory })} active={!activeStatus}>
          All
        </FilterChip>
        {statuses.map((status) => (
          <FilterChip
            key={status}
            href={link({ category: activeCategory, status })}
            active={activeStatus === status}
          >
            {varianceStatusLabel(status)}
          </FilterChip>
        ))}
      </FilterGroup>

      {categories.length > 0 ? (
        <FilterGroup label="Category">
          <FilterChip href={link({ status: activeStatus })} active={!activeCategory}>
            All
          </FilterChip>
          {categories.map((category) => (
            <FilterChip
              key={category}
              href={link({ status: activeStatus, category })}
              active={activeCategory === category}
            >
              {categoryLabel(category)}
            </FilterChip>
          ))}
        </FilterGroup>
      ) : null}
    </div>
  );
}

function FilterGroup({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="label mr-0.5">{label}</span>
      {children}
    </div>
  );
}

function FilterChip({
  href,
  active,
  children,
}: {
  href: string;
  active: boolean;
  children: ReactNode;
}) {
  return (
    <a
      href={href}
      aria-current={active ? "true" : undefined}
      className={cn(
        "rounded-sm border px-2 py-[3px] text-[11.5px] transition-colors",
        active
          ? "border-accent/40 bg-accent/10 font-medium text-foreground"
          : "border-border text-muted-foreground hover:bg-muted hover:text-foreground",
      )}
    >
      {children}
    </a>
  );
}

function VarianceRow({
  variance,
  expanded,
  onToggle,
  applyOptimistic,
}: {
  variance: Variance;
  expanded: boolean;
  onToggle: () => void;
  applyOptimistic: (update: { id: string; status: string }) => void;
}) {
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);

  const decided = variance.status === "accepted" || variance.status === "written_off";
  const lowConfidence = (variance.confidence ?? 0) < 0.5;

  function decide(action: "accept" | "write_off") {
    setError(null);
    startTransition(async () => {
      applyOptimistic({
        id: variance.id,
        status: action === "accept" ? "accepted" : "written_off",
      });
      try {
        await actOnVariance(variance.id, action);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Could not save that decision");
      }
    });
  }

  return (
    <>
      <tr
        className={cn(
          "border-b border-border transition-colors",
          expanded ? "bg-muted/70" : "hover:bg-muted/50",
          pending && "opacity-60",
        )}
      >
        <Td>
          <button
            type="button"
            onClick={onToggle}
            aria-expanded={expanded}
            aria-controls={`variance-detail-${variance.id}`}
            className="flex size-6 items-center justify-center rounded-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <span aria-hidden className="text-[10px]">
              {expanded ? "▼" : "▶"}
            </span>
            <span className="sr-only">
              {expanded ? "Hide details for" : "Show details for"} variance of{" "}
              {formatPaise(variance.variance_paise)}
            </span>
          </button>
        </Td>
        <Td align="right" mono className="font-medium whitespace-nowrap">
          {formatPaise(variance.variance_paise)}
        </Td>
        <Td className="whitespace-nowrap">
          <span className="text-[12px]">{categoryLabel(variance.category)}</span>
          {variance.subcategory ? (
            <span className="block text-[11px] text-muted-foreground">
              {humanise(variance.subcategory)}
            </span>
          ) : null}
        </Td>
        <Td className="max-w-[380px]">
          <p className="truncate text-[12px]" title={variance.explanation ?? undefined}>
            {variance.explanation ?? (
              <span className="text-muted-foreground">Not yet explained</span>
            )}
          </p>
        </Td>
        <Td align="right" mono>
          <span className={lowConfidence ? "text-warn" : undefined}>
            {variance.confidence === null ? "—" : formatRatio(variance.confidence, 0)}
          </span>
        </Td>
        <Td className="max-w-[220px] text-[12px]">
          <span className="block truncate" title={actionLabel(variance.suggested_action)}>
            {actionLabel(variance.suggested_action)}
          </span>
        </Td>
        <Td>
          <Pill severity={varianceSeverity(variance.status)}>
            {varianceStatusLabel(variance.status)}
          </Pill>
        </Td>
        <Td align="right">
          {decided ? (
            <span className="text-[11.5px] text-muted-foreground">Decided</span>
          ) : (
            <div className="flex justify-end gap-1">
              <DecisionButton onClick={() => decide("accept")} disabled={pending}>
                Accept
              </DecisionButton>
              <DecisionButton onClick={() => decide("write_off")} disabled={pending} subtle>
                Write off
              </DecisionButton>
            </div>
          )}
        </Td>
      </tr>

      {error ? (
        <tr className="border-b border-border">
          <td colSpan={8} className="bg-critical-bg px-4 py-1.5 text-[11.5px] text-critical">
            {error}
          </td>
        </tr>
      ) : null}

      {expanded ? (
        <tr id={`variance-detail-${variance.id}`} className="border-b border-border-strong">
          <td colSpan={8} className="bg-surface-raised px-4 py-4">
            <VarianceDetail variance={variance} />
          </td>
        </tr>
      ) : null}
    </>
  );
}

function DecisionButton({
  children,
  onClick,
  disabled,
  subtle,
}: {
  children: ReactNode;
  onClick: () => void;
  disabled?: boolean;
  subtle?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "min-h-[28px] rounded-sm border px-2 py-1 text-[11.5px] whitespace-nowrap transition-colors",
        "disabled:cursor-not-allowed disabled:opacity-50",
        subtle
          ? "border-border text-muted-foreground hover:bg-muted hover:text-foreground"
          : "border-border-strong hover:bg-muted",
      )}
    >
      {children}
    </button>
  );
}

function VarianceDetail({ variance }: { variance: Variance }) {
  const citedKeys = useMemo(
    () => new Set(variance.cited_figures.map(figureKey)),
    [variance.cited_figures],
  );
  const untraceableKeys = useMemo(
    () => new Set(variance.untraceable_figures.map(figureKey)),
    [variance.untraceable_figures],
  );

  return (
    <div className="space-y-4">
      {/* Records first: the explanation below refers back to these, so
          they have to have been read already. */}
      <section>
        <h3 className="label mb-2">
          Records involved ({formatCount(variance.records.length)})
        </h3>
        {variance.records.length === 0 ? (
          <p className="text-[12px] text-muted-foreground">
            No underlying record is attached to this variance. Nothing in the explanation
            below can be checked against source data.
          </p>
        ) : (
          <div className="overflow-x-auto border border-border bg-surface">
            <table className="w-full border-collapse text-[12px]">
              <thead className="bg-muted">
                <tr className="border-b border-border">
                  <Th>Source</Th>
                  <Th>Reference</Th>
                  <Th align="right">Amount</Th>
                  <Th align="right">Fee</Th>
                  <Th align="right">Tax</Th>
                  <Th align="right">Net</Th>
                  <Th>Date</Th>
                  <Th>Description</Th>
                </tr>
              </thead>
              <tbody>
                {variance.records.map((record) => (
                  <RecordRow key={record.txn_id} record={record} cited={citedKeys} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,300px)]">
        <section>
          <h3 className="label mb-2">Explanation</h3>
          {variance.explanation ? (
            <>
              <p className="text-[12.5px] leading-relaxed">
                {markFigures(
                  variance.explanation,
                  variance.cited_figures,
                  variance.untraceable_figures,
                )}
              </p>

              {variance.cited_figures.length > 0 ? (
                <p
                  className={cn(
                    "mt-2.5 text-[11.5px]",
                    variance.all_figures_traceable ? "text-muted-foreground" : "text-critical",
                  )}
                >
                  {variance.all_figures_traceable
                    ? "Every marked figure was found in the records above."
                    : `${formatCount(variance.untraceable_figures.length)} marked figure${
                        variance.untraceable_figures.length === 1 ? "" : "s"
                      } could not be found in the records above — treat this explanation with suspicion.`}
                </p>
              ) : (
                <p className="mt-2.5 text-[11.5px] text-muted-foreground">
                  The explanation cites no specific figure, so there is nothing to trace.
                </p>
              )}

              {variance.untraceable_figures.length > 0 ? (
                <ul className="mt-2 flex flex-wrap gap-1.5">
                  {variance.untraceable_figures.map((figure, index) => (
                    <li key={`${figure}-${index}`}>
                      <Pill severity="critical">
                        <span className="num normal-case">{figure}</span>
                      </Pill>
                    </li>
                  ))}
                </ul>
              ) : null}
            </>
          ) : (
            <p className="text-[12px] text-muted-foreground">
              No explanation was produced. The model declined to classify this case rather
              than guess.
            </p>
          )}
        </section>

        <section className="space-y-3">
          <div>
            <h3 className="label mb-2">Assessment</h3>
            <dl className="space-y-1.5">
              <div className="flex items-baseline justify-between gap-3">
                <dt className="text-[11.5px] text-muted-foreground">Confidence</dt>
                <dd
                  className={cn(
                    "num text-[12px]",
                    (variance.confidence ?? 0) < 0.5 && "text-warn",
                  )}
                >
                  {variance.confidence === null ? "—" : formatRatio(variance.confidence, 0)}
                </dd>
              </div>
              <div className="flex items-baseline justify-between gap-3">
                <dt className="text-[11.5px] text-muted-foreground">Suggested action</dt>
                <dd className="max-w-[190px] text-right text-[12px]">
                  {actionLabel(variance.suggested_action)}
                </dd>
              </div>
            </dl>
            <p className="mt-2 text-[11px] text-muted-foreground">
              Confidence and the suggested action are the model&apos;s, not the
              matcher&apos;s. Neither is arithmetic.
            </p>
          </div>

          {variance.match_group ? (
            <div className="border-t border-border pt-3">
              <h3 className="label mb-2">Matching history</h3>
              <p className="text-[11.5px] leading-relaxed">
                Grouped at{" "}
                <span className="font-medium">tier {variance.match_group.tier}</span> by{" "}
                {strategyLabel(variance.match_group.strategy)}, at{" "}
                <span className="num">
                  {formatRatio(variance.match_group.confidence, 0)}
                </span>{" "}
                confidence, leaving{" "}
                <span className="num">
                  {formatPaise(variance.match_group.total_variance_paise ?? 0)}
                </span>{" "}
                unaccounted for.
              </p>
              {variance.match_group.variance_components ? (
                <dl className="mt-2 space-y-1">
                  {Object.entries(variance.match_group.variance_components).map(
                    ([key, value]) => (
                      <div key={key} className="flex items-baseline justify-between gap-3">
                        <dt className="text-[11px] text-muted-foreground">
                          {humanise(key)}
                        </dt>
                        <dd
                          className={cn(
                            "num text-[11.5px]",
                            typeof value === "number" &&
                              citedKeys.has(figureKey(formatPaise(value))) &&
                              TRACED_MARK,
                          )}
                        >
                          {typeof value === "number" ? formatPaise(value) : String(value)}
                        </dd>
                      </div>
                    ),
                  )}
                </dl>
              ) : null}
            </div>
          ) : null}
        </section>
      </div>

      {variance.cited_figures.length > 0 ? (
        <p className="border-t border-border pt-2.5 text-[11px] text-muted-foreground">
          In the explanation,{" "}
          <span className={cn("num", TRACED_MARK)}>
            a dotted underline
          </span>{" "}
          marks a figure found in the records above.{" "}
          <span className="num bg-critical-bg px-1 font-medium text-critical">
            A red figure
          </span>{" "}
          was not found in any of them.
          {untraceableKeys.size > 0
            ? " A figure the records cannot account for is the model's own, and nothing above supports it."
            : ""}
        </p>
      ) : null}
    </div>
  );
}

function RecordRow({ record, cited }: { record: TxnRecord; cited: Set<string> }) {
  /** A record amount the explanation quoted is marked the same way the
   *  explanation marks it, so the two can be matched by shape. */
  const traced = (value: number | null) =>
    value !== null && cited.has(figureKey(formatPaise(value)))
      ? TRACED_MARK
      : undefined;

  return (
    <tr className="border-b border-border last:border-0">
      <Td>
        <span className="text-[11.5px]">{sourceLabel(record.source_kind)}</span>
      </Td>
      <Td mono className="text-[11.5px]">
        {record.external_ref ?? <span className="text-muted-foreground">none</span>}
      </Td>
      <Td align="right" mono className={traced(record.amount_paise)}>
        {formatPaise(record.amount_paise)}
      </Td>
      <Td
        align="right"
        mono
        className={cn("text-muted-foreground", traced(record.fee_paise))}
      >
        {record.fee_paise === null ? "—" : formatPaise(record.fee_paise)}
      </Td>
      <Td
        align="right"
        mono
        className={cn("text-muted-foreground", traced(record.tax_paise))}
      >
        {record.tax_paise === null ? "—" : formatPaise(record.tax_paise)}
      </Td>
      <Td align="right" mono className={traced(record.net_paise)}>
        {record.net_paise === null ? "—" : formatPaise(record.net_paise)}
      </Td>
      <Td className="whitespace-nowrap text-[11.5px]">{formatDate(record.txn_date)}</Td>
      <Td className="max-w-[260px]">
        <span className="block truncate text-[11.5px]" title={record.description ?? undefined}>
          {record.description ?? "—"}
        </span>
      </Td>
    </tr>
  );
}
