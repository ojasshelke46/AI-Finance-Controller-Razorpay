"use client";

import { usePathname } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";

/**
 * Orientation between console sections.
 *
 * Moving from the variance queue to the audit trail replaces the whole
 * screen at once, and at this density that reads as a flicker rather
 * than as a move. A short fade on arrival says "this is a different
 * section" and then gets out of the way.
 *
 * Two things it deliberately does not do: it never runs on first paint,
 * so nothing animates on page load, and it never moves anything — no
 * slide, no scale. A table of 150 rows arrives at once.
 */
export function SectionTransition({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const firstRender = useRef(true);
  const [arriving, setArriving] = useState(false);

  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    setArriving(true);
    const frame = requestAnimationFrame(() => setArriving(false));
    return () => cancelAnimationFrame(frame);
  }, [pathname]);

  return (
    <div
      data-arriving={arriving ? "" : undefined}
      className="opacity-100 transition-opacity duration-[var(--duration-orient)] ease-[var(--ease-out)] data-arriving:opacity-0 data-arriving:transition-none motion-reduce:transition-none motion-reduce:opacity-100"
    >
      {children}
    </div>
  );
}
