"use client";

import { useState } from "react";

import { EmptyState, Panel, PanelHeader, Pill } from "@/components/primitives";
import type { AuditEvent } from "@/lib/api";
import { formatDateTime, formatTime, humanise } from "@/lib/format";
import { formatCount } from "@/lib/money";
import { cn } from "@/lib/utils";

/** Actor -> severity. A human touching the ledger is the notable event
 *  in an otherwise autonomous trail, so that is what gets marked. */
function actorSeverity(actor: string) {
  if (actor === "human") return "info" as const;
  return "neutral" as const;
}

function actionSeverity(action: string | null) {
  if (!action) return "neutral" as const;
  if (action.includes("failed") || action.includes("crashed")) return "critical" as const;
  if (action.includes("complete")) return "ok" as const;
  if (action.includes("skipped")) return "warn" as const;
  return "neutral" as const;
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

  return (
    <Panel>
      <PanelHeader
        title="Audit trail"
        description="Every event this run wrote, in order. This is the machine-readable record the pipeline itself reads back to decide what still needs doing."
        right={
          <span className="num text-[11.5px] text-muted-foreground">
            {formatCount(events.length)} events
          </span>
        }
      />

      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-b border-border px-4 py-2.5">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="label mr-0.5">Actor</span>
          <Chip href={link({ step: activeStep })} active={!activeActor}>
            All
          </Chip>
          {actors.map((actor) => (
            <Chip
              key={actor}
              href={link({ step: activeStep, actor })}
              active={activeActor === actor}
            >
              {actor}
            </Chip>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="label mr-0.5">Step</span>
          <Chip href={link({ actor: activeActor })} active={!activeStep}>
            All
          </Chip>
          {steps.map((step) => (
            <Chip
              key={step}
              href={link({ actor: activeActor, step })}
              active={activeStep === step}
            >
              {step}
            </Chip>
          ))}
        </div>
      </div>

      {events.length === 0 ? (
        <EmptyState
          title="No events match"
          description="Nothing was recorded for this combination of actor and step. Clear the filters to see the whole trail."
        />
      ) : (
        <ol className="divide-y divide-border">
          {events.map((event, index) => {
            const id = event.id ?? `${event.created_at}-${index}`;
            const open = openId === id;
            const hasDetail = event.detail && Object.keys(event.detail).length > 0;

            return (
              <li key={id}>
                <div
                  className={cn(
                    // Same reason as the status page event list: the
                    // fixed track widths only apply once there is room
                    // for them.
                    "flex flex-wrap items-baseline gap-x-3 gap-y-0.5 px-4 py-1.5 transition-colors",
                    "sm:grid sm:grid-cols-[auto_74px_110px_1fr]",
                    open && "bg-muted/70",
                  )}
                >
                  <button
                    type="button"
                    onClick={() => setOpenId(open ? null : id)}
                    disabled={!hasDetail}
                    aria-expanded={open}
                    className="flex size-6 items-center justify-center self-center rounded-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-30"
                  >
                    <span aria-hidden className="text-[10px]">
                      {hasDetail ? (open ? "▼" : "▶") : "·"}
                    </span>
                    <span className="sr-only">
                      {open ? "Hide" : "Show"} detail for {event.action}
                    </span>
                  </button>

                  <time
                    dateTime={event.created_at}
                    title={formatDateTime(event.created_at)}
                    className="num text-[11.5px] text-muted-foreground"
                  >
                    {formatTime(event.created_at)}
                  </time>

                  <Pill severity={actorSeverity(event.actor)}>{event.actor}</Pill>

                  <div className="flex min-w-0 flex-wrap items-baseline gap-x-2">
                    <span className="text-[12.5px] font-medium">
                      {humanise(event.action)}
                    </span>
                    <span className="num text-[11px] text-muted-foreground">{event.step}</span>
                    {actionSeverity(event.action) !== "neutral" ? (
                      <Pill severity={actionSeverity(event.action)}>
                        {actionSeverity(event.action)}
                      </Pill>
                    ) : null}
                    {!open && hasDetail ? (
                      <span className="min-w-0 truncate text-[11px] text-muted-foreground">
                        {summarise(event.detail!)}
                      </span>
                    ) : null}
                  </div>
                </div>

                {open && hasDetail ? (
                  <div className="border-t border-border bg-surface-raised px-4 py-3">
                    <pre className="num overflow-x-auto text-[11.5px] leading-relaxed whitespace-pre-wrap">
                      {JSON.stringify(event.detail, null, 2)}
                    </pre>
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

/** A one-line preview of the detail payload so the collapsed row still
 *  carries information rather than just a chevron. */
function summarise(detail: Record<string, unknown>): string {
  const parts: string[] = [];
  for (const [key, value] of Object.entries(detail)) {
    if (value === null || value === undefined) continue;
    if (typeof value === "object") continue;
    parts.push(`${key}=${String(value).slice(0, 40)}`);
    if (parts.length >= 4) break;
  }
  return parts.join("  ");
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
