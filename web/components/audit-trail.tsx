"use client";

import { useState } from "react";

import { EmptyState, Panel, PanelHeader } from "@/components/primitives";
import type { AuditEvent } from "@/lib/api";
import { formatDate, formatTime, humanise } from "@/lib/format";
import { actorLabel, eventLabel, stepLabel } from "@/lib/gloss";
import { formatCount } from "@/lib/money";
import { cn } from "@/lib/utils";

/**
 * The trail is evidence, so it is built as a log: one line per event,
 * fixed columns, monospace timestamps, and a date rule where the day
 * changes. Nothing is styled to draw attention on its own — a failure
 * shows in the wording and its tint, and a line an operator wrote is
 * marked in the margin, because in an otherwise autonomous record that
 * is the notable event.
 */
function toneFor(action: string | null): string | undefined {
  if (!action) return undefined;
  if (action.includes("failed") || action.includes("crashed")) return "text-critical";
  if (action.includes("skipped")) return "text-warn";
  return undefined;
}

export function AuditTrail({
  batchId,
  events,
  actors,
  steps,
  activeActor,
  activeStep,
}: {
  batchId: string;
  events: AuditEvent[];
  actors: string[];
  steps: string[];
  activeActor?: string;
  activeStep?: string;
}) {
  const [openId, setOpenId] = useState<string | null>(null);

  const base = `/batches/${batchId}/audit`;
  const link = (params: { actor?: string; step?: string }) => {
    const search = new URLSearchParams();
    if (params.actor) search.set("actor", params.actor);
    if (params.step) search.set("step", params.step);
    const qs = search.toString();
    return qs ? `${base}?${qs}` : base;
  };

  const operatorEvents = events.filter((event) => event.actor === "human").length;
  const failures = events.filter(
    (event) => event.action?.includes("failed") || event.action?.includes("crashed"),
  ).length;

  return (
    <Panel>
      <PanelHeader
        title="Audit trail"
        description="Every event this run wrote, oldest first. This is the record the pipeline itself reads back to decide what still needs doing."
      />

      <dl className="flex flex-wrap items-baseline gap-x-8 gap-y-2 border-b border-border px-4 py-2.5">
        <Count label="Events" value={formatCount(events.length)} />
        <Count
          label="Failures"
          value={formatCount(failures)}
          tone={failures > 0 ? "text-critical" : undefined}
        />
        <Count
          label="Written by an operator"
          value={formatCount(operatorEvents)}
          tone={operatorEvents > 0 ? "text-info" : undefined}
          hint={operatorEvents === 0 ? "every line is the system's" : undefined}
        />
      </dl>

      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-b border-border px-4 py-2.5">
        <FilterGroup label="Actor">
          <Chip href={link({ step: activeStep })} active={!activeActor}>
            All
          </Chip>
          {actors.map((actor) => (
            <Chip
              key={actor}
              href={link({ step: activeStep, actor })}
              active={activeActor === actor}
            >
              {actorLabel(actor)}
            </Chip>
          ))}
        </FilterGroup>
        <FilterGroup label="Step">
          <Chip href={link({ actor: activeActor })} active={!activeStep}>
            All
          </Chip>
          {steps.map((step) => (
            <Chip
              key={step}
              href={link({ actor: activeActor, step })}
              active={activeStep === step}
            >
              {stepLabel(step)}
            </Chip>
          ))}
        </FilterGroup>
      </div>

      {events.length === 0 ? (
        <EmptyState
          title={activeActor || activeStep ? "Nothing matches these filters" : "Nothing recorded"}
          description={
            activeActor || activeStep
              ? "No event in this run has that combination of actor and step. Clear the filters to see the whole trail."
              : "This batch has written no events yet. Lines appear here as each stage runs."
          }
        />
      ) : (
        <ol>
          {events.map((event, index) => {
            const id = event.id ?? `${event.created_at}-${index}`;
            const open = openId === id;
            const hasDetail = event.detail && Object.keys(event.detail).length > 0;
            const previous = events[index - 1];
            const newDay =
              index === 0 ||
              formatDate(previous?.created_at) !== formatDate(event.created_at);
            const byOperator = event.actor === "human";
            const tone = toneFor(event.action);

            return (
              <li key={id}>
                {newDay ? (
                  <p className="num border-y border-border bg-surface-raised px-4 py-1 text-[11px] text-muted-foreground first:border-t-0">
                    {formatDate(event.created_at)}
                  </p>
                ) : null}

                <div
                  className={cn(
                    // Fixed tracks only once there is room for them; at
                    // 375px the columns would push the page sideways.
                    "flex flex-wrap items-baseline gap-x-3 gap-y-0.5 border-b border-border px-4 py-1.5",
                    "sm:grid sm:grid-cols-[auto_58px_76px_92px_1fr]",
                    byOperator && "border-l border-l-info",
                    open ? "bg-muted/70" : "hover:bg-muted/40",
                  )}
                >
                  <button
                    type="button"
                    onClick={() => setOpenId(open ? null : id)}
                    disabled={!hasDetail}
                    aria-expanded={open}
                    className="flex size-5 items-center justify-center self-center rounded-sm text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-25"
                  >
                    <span aria-hidden className="text-[10px]">
                      {hasDetail ? (open ? "▼" : "▶") : "·"}
                    </span>
                    <span className="sr-only">
                      {open ? "Hide" : "Show"} recorded detail for {eventLabel(event.action)}
                    </span>
                  </button>

                  <time
                    dateTime={event.created_at}
                    className="num text-[11.5px] text-muted-foreground"
                  >
                    {formatTime(event.created_at)}
                  </time>

                  <span
                    className={cn(
                      "truncate text-[11.5px]",
                      byOperator ? "text-info" : "text-muted-foreground",
                    )}
                  >
                    {actorLabel(event.actor)}
                  </span>

                  <span className="truncate text-[11.5px] text-muted-foreground">
                    {stepLabel(event.step)}
                  </span>

                  <div className="flex min-w-0 flex-wrap items-baseline gap-x-2">
                    <span className={cn("text-[12.5px]", tone)}>
                      {eventLabel(event.action)}
                    </span>
                    {!open && hasDetail ? (
                      <span className="num min-w-0 truncate text-[11px] text-muted-foreground">
                        {summarise(event.detail!)}
                      </span>
                    ) : null}
                  </div>
                </div>

                {open && hasDetail ? (
                  <div className="border-b border-border bg-surface-raised px-4 py-2.5 sm:pl-[38px]">
                    <dl className="grid gap-x-6 gap-y-1 sm:grid-cols-2">
                      {Object.entries(event.detail!).map(([key, value]) => (
                        <div
                          key={key}
                          className="flex items-baseline justify-between gap-3 border-b border-border/60 py-0.5 last:border-0"
                        >
                          <dt className="text-[11px] text-muted-foreground">
                            {humanise(key)}
                          </dt>
                          <dd className="num min-w-0 truncate text-right text-[11.5px]">
                            {formatValue(value)}
                          </dd>
                        </div>
                      ))}
                    </dl>
                  </div>
                ) : null}
              </li>
            );
          })}
        </ol>
      )}
    </Panel>
  );
}

function Count({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: string;
}) {
  return (
    <div className="flex items-baseline gap-2">
      <dt className="label">{label}</dt>
      <dd className={cn("num text-[13px] font-medium", tone)}>{value}</dd>
      {hint ? <span className="text-[11px] text-muted-foreground">{hint}</span> : null}
    </div>
  );
}

/** Objects and arrays are shown as their shape rather than as a wall of
 *  JSON; a scalar is shown as itself. */
function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (Array.isArray(value)) {
    return value.length === 0 ? "none" : value.map((item) => String(item)).join(", ");
  }
  if (typeof value === "object") {
    const keys = Object.keys(value as Record<string, unknown>);
    return keys.length === 0 ? "none" : `${keys.length} fields`;
  }
  if (typeof value === "boolean") return value ? "yes" : "no";
  return String(value);
}

/** A one-line preview so a collapsed line still carries information
 *  rather than only a chevron. Keys are glossed for the same reason
 *  every other enum is. */
function summarise(detail: Record<string, unknown>): string {
  const parts: string[] = [];
  for (const [key, value] of Object.entries(detail)) {
    if (value === null || value === undefined) continue;
    if (typeof value === "object") continue;
    parts.push(`${humanise(key).toLowerCase()} ${String(value).slice(0, 32)}`);
    if (parts.length >= 3) break;
  }
  return parts.join(" · ");
}

function FilterGroup({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="label mr-0.5">{label}</span>
      {children}
    </div>
  );
}

function Chip({
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
        "rounded-sm border px-2 py-[3px] text-[11.5px]",
        active
          ? "border-accent/40 bg-accent/10 font-medium text-foreground"
          : "border-border text-muted-foreground hover:bg-muted hover:text-foreground",
      )}
    >
      {children}
    </a>
  );
}
