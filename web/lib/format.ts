/** Time and text helpers shared across the console. */

const TIME = new Intl.DateTimeFormat("en-IN", {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

const DATE_TIME = new Intl.DateTimeFormat("en-IN", {
  day: "2-digit",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

const DATE = new Intl.DateTimeFormat("en-IN", {
  day: "2-digit",
  month: "short",
  year: "numeric",
});

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return TIME.format(new Date(iso));
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return DATE_TIME.format(new Date(iso));
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return DATE.format(new Date(iso));
}

/**
 * "4m ago" / "in 12m". Relative time is what an operator actually reads
 * on a live status page — "is this recent?" is the question, not "what
 * clock time was it".
 */
export function relativeTime(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  const deltaSeconds = Math.round((then - now) / 1000);
  const ahead = deltaSeconds > 0;
  const seconds = Math.abs(deltaSeconds);

  let body: string;
  if (seconds < 45) body = `${seconds}s`;
  else if (seconds < 3600) body = `${Math.round(seconds / 60)}m`;
  else if (seconds < 86400) body = `${Math.round(seconds / 3600)}h`;
  else body = `${Math.round(seconds / 86400)}d`;

  return ahead ? `in ${body}` : `${body} ago`;
}

export function formatSeconds(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (value < 60) return `${value.toFixed(1)}s`;
  const minutes = Math.floor(value / 60);
  const seconds = Math.round(value % 60);
  return `${minutes}m ${seconds}s`;
}

/** snake_case_identifier -> "Snake case identifier" */
export function humanise(value: string | null | undefined): string {
  if (!value) return "—";
  const spaced = value.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

export function sourceLabel(kind: string): string {
  const map: Record<string, string> = {
    razorpay: "Razorpay",
    bank: "Bank",
    ledger: "Ledger",
  };
  return map[kind] ?? humanise(kind);
}
