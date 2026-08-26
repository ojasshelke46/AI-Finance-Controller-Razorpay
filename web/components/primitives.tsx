/**
 * The console's visual vocabulary. Small, deliberately unstyled-looking
 * pieces that every page composes from, so a status pill on the batches
 * table and one on a variance row are the same object rather than two
 * lookalikes that drift apart.
 */

import Link from "next/link";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

type Severity = "critical" | "warn" | "ok" | "info" | "neutral";

const SEVERITY_CLASS: Record<Severity, string> = {
  critical: "text-critical bg-critical-bg border-critical/25",
  warn: "text-warn bg-warn-bg border-warn/25",
  ok: "text-ok bg-ok-bg border-ok/25",
  info: "text-info bg-info-bg border-info/25",
  neutral: "text-muted-foreground bg-muted border-border",
};

/** Batch lifecycle -> severity. Terminal-good is quiet, failure is loud,
 *  in-flight is informational. Nothing else earns colour. */
export function batchSeverity(status: string): Severity {
  if (status === "failed") return "critical";
  if (status === "complete") return "ok";
  if (status === "pending") return "neutral";
  return "info";
}

/** Variance lifecycle -> severity. 'open' is the only state that wants
 *  an operator, so it is the only one that gets warm colour. */
export function varianceSeverity(status: string): Severity {
  if (status === "open") return "warn";
  if (status === "explained") return "info";
  if (status === "written_off") return "neutral";
  if (status === "accepted") return "ok";
  return "neutral";
}

export function Pill({
  children,
  severity = "neutral",
  className,
  title,
}: {
  children: ReactNode;
  severity?: Severity;
  className?: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-sm border px-1.5 py-0.5",
        "text-[10.5px] font-medium tracking-wide uppercase whitespace-nowrap",
        SEVERITY_CLASS[severity],
        className,
      )}
    >
      {children}
    </span>
  );
}

export function StatusDot({
  severity = "neutral",
  live = false,
  className,
}: {
  severity?: Severity;
  live?: boolean;
  className?: string;
}) {
  const color: Record<Severity, string> = {
    critical: "bg-critical",
    warn: "bg-warn",
    ok: "bg-ok",
    info: "bg-info",
    neutral: "bg-muted-foreground",
  };
  return (
    <span
      aria-hidden
      className={cn(
        "inline-block size-[7px] shrink-0 rounded-full",
        color[severity],
        live && "live-dot",
        className,
      )}
    />
  );
}

export function Panel({
  children,
  className,
  as: Tag = "section",
}: {
  children: ReactNode;
  className?: string;
  as?: "section" | "div" | "article";
}) {
  return (
    <Tag className={cn("border border-border bg-surface", className)}>{children}</Tag>
  );
}

export function PanelHeader({
  title,
  description,
  right,
}: {
  title: ReactNode;
  description?: ReactNode;
  right?: ReactNode;
}) {
  return (
    <header className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-border px-4 py-2.5">
      <div className="min-w-0">
        <h2 className="text-[13px] font-semibold tracking-tight">{title}</h2>
        {description ? (
          <p className="mt-0.5 text-[11.5px] text-muted-foreground">{description}</p>
        ) : null}
      </div>
      {right ? <div className="shrink-0">{right}</div> : null}
    </header>
  );
}

/**
 * A single headline figure. Label above, value below in mono — the value
 * is the thing being read, so it gets the size and the label gets out of
 * the way.
 */
export function Metric({
  label,
  value,
  hint,
  severity,
  size = "md",
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  severity?: Severity;
  size?: "md" | "lg";
}) {
  const tone =
    severity && severity !== "neutral"
      ? {
          critical: "text-critical",
          warn: "text-warn",
          ok: "text-ok",
          info: "text-info",
        }[severity]
      : "text-foreground";

  return (
    <div className="min-w-0">
      <div className="label">{label}</div>
      <div
        className={cn(
          "num mt-1 font-semibold tracking-tight tabular-nums",
          size === "lg" ? "text-[26px] leading-8" : "text-[17px] leading-6",
          tone,
        )}
      >
        {value}
      </div>
      {hint ? (
        <div className="mt-0.5 text-[11px] leading-4 text-muted-foreground">{hint}</div>
      ) : null}
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-14 text-center">
      <p className="text-[13px] font-medium">{title}</p>
      <p className="max-w-prose text-[12px] text-muted-foreground">{description}</p>
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}

export function ErrorState({
  title,
  detail,
  hint,
}: {
  title: string;
  detail: string;
  hint?: string;
}) {
  return (
    <Panel className="border-critical/30 bg-critical-bg/40">
      <div className="px-4 py-4">
        <p className="text-[13px] font-semibold text-critical">{title}</p>
        <p className="mt-1 text-[12px] text-foreground/80">{detail}</p>
        {hint ? <p className="mt-2 text-[11.5px] text-muted-foreground">{hint}</p> : null}
      </div>
    </Panel>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("skeleton", className)} />;
}

/** Table shell. Dense by default: 28px rows, hairline rules, sticky head. */
export function DataTable({
  head,
  children,
  className,
}: {
  head: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("w-full overflow-x-auto", className)}>
      <table className="w-full border-collapse text-[12.5px]">
        <thead className="sticky top-0 z-10 bg-surface-raised">
          <tr className="border-b border-border-strong">{head}</tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

export function Th({
  children,
  align = "left",
  className,
  scope = "col",
}: {
  children?: ReactNode;
  align?: "left" | "right" | "center";
  className?: string;
  scope?: "col" | "row";
}) {
  return (
    <th
      scope={scope}
      className={cn(
        "label px-3 py-2 font-medium whitespace-nowrap",
        align === "right" && "text-right",
        align === "center" && "text-center",
        className,
      )}
    >
      {children}
    </th>
  );
}

export function Td({
  children,
  align = "left",
  mono = false,
  className,
  title,
}: {
  children: ReactNode;
  align?: "left" | "right" | "center";
  mono?: boolean;
  className?: string;
  /** Hover detail for a cell that shows a shortened form of its value. */
  title?: string;
}) {
  return (
    <td
      title={title}
      className={cn(
        "px-3 py-1.5 align-middle",
        align === "right" && "text-right",
        align === "center" && "text-center",
        mono && "num",
        className,
      )}
    >
      {children}
    </td>
  );
}

export function CopyableId({ id, href }: { id: string; href?: string }) {
  const short = id.slice(0, 8);
  if (href) {
    return (
      <Link
        href={href}
        title={id}
        className="num text-[12px] text-accent underline-offset-2 hover:underline"
      >
        {short}
      </Link>
    );
  }
  return (
    <span title={id} className="num text-[12px] text-muted-foreground">
      {short}
    </span>
  );
}
