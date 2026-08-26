/**
 * Figure tracing, shared by the variance queue and the Q&A console.
 *
 * Both surfaces answer the same question — did this number come out of
 * the records, or did the model produce it — so they mark figures the
 * same way and use one implementation of "is this the same amount".
 */

import type { ReactNode } from "react";

import { cn } from "./utils";

/** Comparable form: digits, sign and decimal point only, so
 *  "₹1,42,900.00" and "1,42,900.00" are recognised as one amount. */
export function figureKey(value: string): string {
  return value.replace(/[^\d.-]/g, "");
}

export const TRACED_MARK =
  "underline decoration-ok decoration-dotted underline-offset-[3px]";

/**
 * Splits text so every cited figure renders as a mark rather than as
 * prose: a dotted underline when it was found in the source records, a
 * critical fill when it was not. The operator should not have to hold
 * two lists in their head and compare them by eye.
 */
export function markFigures(
  text: string,
  cited: string[],
  untraceable: string[] = [],
): ReactNode[] {
  if (cited.length === 0) return [text];

  const untraceableKeys = new Set(untraceable.map(figureKey));
  // Longest first: "₹1,42,900.00" must win over the "900.00" inside it.
  const ordered = [...cited].sort((a, b) => b.length - a.length);
  const pattern = new RegExp(
    `(${ordered.map((f) => f.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`,
    "g",
  );

  return text.split(pattern).map((part, index) => {
    if (index % 2 === 0) return part;
    const traceable = !untraceableKeys.has(figureKey(part));
    return (
      <mark
        key={index}
        title={
          traceable
            ? "Traced to the source records"
            : "Not found in any source record — this figure is not verified"
        }
        className={cn(
          "num bg-transparent",
          traceable
            ? `text-foreground ${TRACED_MARK}`
            : "bg-critical-bg font-medium text-critical",
        )}
      >
        {part}
      </mark>
    );
  });
}
