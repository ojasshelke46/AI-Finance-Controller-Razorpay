/**
 * Money formatting. Input is ALWAYS integer paise — the API never sends
 * a float or a pre-formatted string, so the browser is the first place a
 * rupee figure exists, and it is built from digits rather than by
 * dividing.
 *
 * Indian digit grouping is last three, then pairs:
 *   482173000 paise -> 48,21,730.00   (not 4,821,730.00)
 * Getting this wrong is immediately visible to anyone who works with
 * Indian financial data, which is the entire audience for this tool.
 */

/** Groups a digit string the Indian way: last 3, then pairs. */
// Written as constructor calls, not 0n/100n literals: Next.js rewrites
// tsconfig on dev start and can reset the target below ES2020, which
// makes BigInt literals a compile error. This survives that.
const ZERO = BigInt(0);
const HUNDRED = BigInt(100);

export function groupIndian(digits: string): string {
  if (digits.length <= 3) return digits;
  const tail = digits.slice(-3);
  let head = digits.slice(0, -3);
  const parts: string[] = [];
  while (head.length > 2) {
    parts.unshift(head.slice(-2));
    head = head.slice(0, -2);
  }
  if (head) parts.unshift(head);
  return [...parts, tail].join(",");
}

export type MoneyOptions = {
  /** Prefix with ₹. Default true. */
  symbol?: boolean;
  /** Show the paise decimals. Default true. */
  decimals?: boolean;
  /** Render a leading + for positive values (for deltas). Default false. */
  signed?: boolean;
};

/**
 * Integer paise -> display string. Never constructs a float: the rupee
 * and paise halves come from integer division on a BigInt, so a value
 * past 2^53 paise still renders exactly.
 */
export function formatPaise(paise: number | bigint | null | undefined, options: MoneyOptions = {}): string {
  const { symbol = true, decimals = true, signed = false } = options;
  if (paise === null || paise === undefined) return "—";

  const value = typeof paise === "bigint" ? paise : BigInt(Math.trunc(Number(paise)));
  const negative = value < ZERO;
  const absolute = negative ? -value : value;

  const rupees = absolute / HUNDRED;
  const sub = absolute % HUNDRED;

  const grouped = groupIndian(rupees.toString());
  const body = decimals ? `${grouped}.${sub.toString().padStart(2, "0")}` : grouped;

  const sign = negative ? "−" : signed ? "+" : "";
  return `${sign}${symbol ? "₹" : ""}${body}`;
}

/**
 * Short form for headline figures: ₹1.12 Cr, ₹4.82 L, ₹9,786.00.
 * Crore and lakh are the units this audience actually reads in.
 */
export function formatPaiseCompact(paise: number | bigint | null | undefined): string {
  if (paise === null || paise === undefined) return "—";
  const value = typeof paise === "bigint" ? paise : BigInt(Math.trunc(Number(paise)));
  const negative = value < ZERO;
  const absolute = negative ? -value : value;
  const rupees = Number(absolute / HUNDRED);
  const sign = negative ? "−" : "";

  if (rupees >= 10_000_000) return `${sign}₹${(rupees / 10_000_000).toFixed(2)} Cr`;
  if (rupees >= 100_000) return `${sign}₹${(rupees / 100_000).toFixed(2)} L`;
  return formatPaise(paise);
}

/** 0.9748 -> "97.48%". Ratios are stored as decimals, shown as percent. */
export function formatRatio(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

/** 90.91 -> "90.91%". Already-percent values, kept separate so a ratio
 *  is never accidentally multiplied twice. */
export function formatPercent(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return "—";
  return `${Number(value).toFixed(digits)}%`;
}

export function formatCount(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("en-IN").format(value);
}
