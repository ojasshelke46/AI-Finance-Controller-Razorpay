"use client";

import { useMemo, useOptimistic, useState, useTransition } from "react";

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
import { formatDate, humanise, sourceLabel } from "@/lib/format";
import { formatCount, formatPaise, formatRatio } from "@/lib/money";
import { cn } from "@/lib/utils";

/** Plain-English gloss for each suggested action. The enum value alone
 *  means nothing to someone who has not read the prompt that produced
 *  it, and this queue has to be readable cold. */
const ACTION_COPY: Record<string, string> = {
  auto_accept: "Safe to accept without review",
  book_to_fee_account: "Post to the payment-processing fee account",
  await_next_settlement: "Expected to clear in the next settlement",
  request_bank_advice: "Ask the bank for an advice note",
  flag_for_human: "Needs a person to decide",
  write_off: "Too small to chase — write it off",
};

type SortKey = "value" | "confidence";

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
      const delta =
        sortKey === "value"
          ? Math.abs(a.variance_paise) - Math.abs(b.variance_paise)
          : (a.confidence ?? -1) - (b.confidence ?? -1);
      return ascending ? delta : -delta;
    });
    return copy;
  }, [optimistic, sortKey, ascending]);

  const openCount = optimistic.filter((v) => v.status === "open").length;
  const totalValue = optimistic.reduce((sum, v) => sum + Math.abs(v.variance_paise), 0);

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
        description="Every discrepancy the matcher could not resolve on its own, largest first. Expand a row to see the underlying records and why the system reached its conclusion."
        right={
          <span className="num text-[11.5px] text-muted-foreground">
            {formatCount(optimistic.length)} shown · {formatCount(openCount)} open ·{" "}
            {formatPaise(totalValue)}
          </span>
        }
      />

      <Filters
        batchId={batchId}
        categories={categories}
        activeCategory={activeCategory}
        activeStatus={activeStatus}
      />

      {sorted.length === 0 ? (
        <EmptyState
          title="Nothing in the queue"
          description={
            activeCategory || activeStatus
              ? "No variance matches these filters. Clear them to see the whole queue."
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
            {humanise(status)}
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
              {humanise(category)}
            </FilterChip>
          ))}
        </FilterGroup>
      ) : null}
    </div>
  );
}

function FilterGroup({ label, children }: { label: string; children: React.ReactNode }) {
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
  children: React.ReactNode;
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
          <span className="text-[12px]">{humanise(variance.category)}</span>
          {variance.subcategory ? (
            <span className="block text-[11px] text-muted-foreground">
              {variance.subcategory}
            </span>
          ) : null}
        </Td>
        <Td className="max-w-[420px]">
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
        <Td className="whitespace-nowrap text-[12px]">
          {variance.suggested_action ? humanise(variance.suggested_action) : "—"}
        </Td>
        <Td>
          <Pill severity={varianceSeverity(variance.status)}>{humanise(variance.status)}</Pill>
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
  children: React.ReactNode;
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
  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,340px)]">
      <div className="space-y-4">
        <section>
          <h3 className="label mb-2">
            Records involved ({formatCount(variance.records.length)})
          </h3>
          {variance.records.length === 0 ? (
            <p className="text-[12px] text-muted-foreground">
              No underlying record is attached to this variance.
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
                    <RecordRow key={record.txn_id} record={record} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        {variance.match_group ? (
          <section>
            <h3 className="label mb-2">Matching history</h3>
            <p className="text-[12px]">
              Grouped by{" "}
              <span className="font-medium">tier {variance.match_group.tier}</span> using{" "}
              <span className="num">{variance.match_group.strategy}</span> at{" "}
              {formatRatio(variance.match_group.confidence, 0)} confidence, leaving a residual
              of{" "}
              <span className="num">
                {formatPaise(variance.match_group.total_variance_paise ?? 0)}
              </span>
              .
            </p>
            {variance.match_group.variance_components ? (
              <dl className="mt-2 flex flex-wrap gap-x-6 gap-y-1">
                {Object.entries(variance.match_group.variance_components).map(([key, value]) => (
                  <div key={key} className="flex items-baseline gap-2">
                    <dt className="text-[11px] text-muted-foreground">{humanise(key)}</dt>
                    <dd className="num text-[12px]">
                      {typeof value === "number" ? formatPaise(value) : String(value)}
                    </dd>
                  </div>
                ))}
              </dl>
            ) : null}
          </section>
        ) : null}
      </div>

      <div className="space-y-4">
        <section>
          <h3 className="label mb-2">Explanation</h3>
          {variance.explanation ? (
            <p className="text-[12.5px] leading-relaxed">{variance.explanation}</p>
          ) : (
            <p className="text-[12px] text-muted-foreground">
              No explanation was produced. The model declined to classify this case rather
              than guess.
            </p>
          )}

          <dl className="mt-3 space-y-1.5">
            <div className="flex items-baseline justify-between gap-3">
              <dt className="text-[11.5px] text-muted-foreground">Confidence</dt>
              <dd className="num text-[12px]">
                {variance.confidence === null ? "—" : formatRatio(variance.confidence, 0)}
              </dd>
            </div>
            <div className="flex items-baseline justify-between gap-3">
              <dt className="text-[11.5px] text-muted-foreground">Suggested action</dt>
              <dd className="text-right text-[12px]">
                {variance.suggested_action ? humanise(variance.suggested_action) : "—"}
              </dd>
            </div>
          </dl>
          {variance.suggested_action && ACTION_COPY[variance.suggested_action] ? (
            <p className="mt-1.5 text-[11.5px] text-muted-foreground">
              {ACTION_COPY[variance.suggested_action]}
            </p>
          ) : null}
        </section>

        <section>
          <h3 className="label mb-2">Cited amounts</h3>
          {variance.cited_figures.length === 0 ? (
            <p className="text-[11.5px] text-muted-foreground">
              The explanation cites no specific figure.
            </p>
          ) : (
            <>
              <ul className="flex flex-wrap gap-1.5">
                {variance.cited_figures.map((figure, index) => {
                  const traceable = !variance.untraceable_figures.includes(figure);
                  return (
                    <li key={`${figure}-${index}`}>
                      <Pill severity={traceable ? "ok" : "critical"}>
                        <span className="num normal-case">{figure}</span>
                      </Pill>
                    </li>
                  );
                })}
              </ul>
              <p className="mt-2 text-[11.5px] text-muted-foreground">
                {variance.all_figures_traceable
                  ? "Every figure in this explanation was found in the records above."
                  : "Highlighted figures could not be traced to the records above — treat this explanation with suspicion."}
              </p>
            </>
          )}
        </section>
      </div>
    </div>
  );
}

function RecordRow({ record }: { record: TxnRecord }) {
  return (
    <tr className="border-b border-border last:border-0">
      <Td>
        <span className="text-[11.5px]">{sourceLabel(record.source_kind)}</span>
      </Td>
      <Td mono className="text-[11.5px]">
        {record.external_ref ?? <span className="text-muted-foreground">none</span>}
      </Td>
      <Td align="right" mono>
        {formatPaise(record.amount_paise)}
      </Td>
      <Td align="right" mono className="text-muted-foreground">
        {record.fee_paise === null ? "—" : formatPaise(record.fee_paise)}
      </Td>
      <Td align="right" mono className="text-muted-foreground">
        {record.tax_paise === null ? "—" : formatPaise(record.tax_paise)}
      </Td>
      <Td align="right" mono>
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
