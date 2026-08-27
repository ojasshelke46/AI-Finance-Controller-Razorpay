"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * Marks a figure that changed underneath the operator.
 *
 * The status page re-reads itself every 30 seconds. Without this, a
 * number moves in total silence and an operator who was looking at the
 * old one has no way to know. The mark is a grey tint that decays: it
 * says "this moved", and nothing else. It is deliberately not a severity
 * colour, because whether a figure changed is not a severity.
 *
 * Built as a transition rather than a keyframe so that a value changing
 * twice in quick succession retargets from wherever it is, instead of
 * restarting from full tint.
 */
export function LiveFigure({
  value,
  children,
  className,
}: {
  /** Comparison key. When it differs from the last render, the mark runs. */
  value: string;
  children: ReactNode;
  className?: string;
}) {
  const previous = useRef<string | null>(null);
  const [marked, setMarked] = useState(false);
  const frame = useRef<number | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    // First render is not a change; the figure was always this value.
    if (previous.current === null) {
      previous.current = value;
      return;
    }
    if (previous.current === value) return;
    previous.current = value;

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    setMarked(true);

    if (reduced) {
      // No decay to watch: hold the tint long enough to be noticed, then
      // drop it in one step.
      timer.current = setTimeout(() => setMarked(false), 1200);
    } else {
      // Paint the tint, then release it on the next frame so the
      // transition has somewhere to travel from.
      frame.current = requestAnimationFrame(() =>
        requestAnimationFrame(() => setMarked(false)),
      );
    }

    return () => {
      if (frame.current) cancelAnimationFrame(frame.current);
      if (timer.current) clearTimeout(timer.current);
    };
  }, [value]);

  return (
    <span
      data-changed={marked ? "" : undefined}
      className={cn(
        "-mx-1 rounded-sm px-1",
        // Settling back to transparent is the animation; arriving at the
        // tint is instant, so the change is never missed.
        "bg-transparent transition-colors duration-[var(--duration-expand)] ease-[var(--ease-out)]",
        "data-changed:bg-muted data-changed:transition-none",
        "motion-reduce:transition-none",
        className,
      )}
    >
      {children}
    </span>
  );
}
