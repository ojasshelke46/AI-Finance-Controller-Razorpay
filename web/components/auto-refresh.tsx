"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

/**
 * Re-fetches the server component on an interval so the status page is
 * genuinely live rather than a snapshot of whenever it was opened.
 *
 * Two deliberate choices: it pauses while the tab is hidden (a
 * background tab polling an API for hours is rude), and it shows a
 * countdown so the operator can tell the difference between "nothing is
 * happening" and "this page is stale".
 */
export function AutoRefresh({ seconds = 30 }: { seconds?: number }) {
  const router = useRouter();
  const [remaining, setRemaining] = useState(seconds);
  const [paused, setPaused] = useState(false);

  useEffect(() => {
    const onVisibility = () => setPaused(document.hidden);
    onVisibility();
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);

  useEffect(() => {
    if (paused) return;
    const tick = setInterval(() => {
      setRemaining((value) => {
        if (value <= 1) {
          router.refresh();
          return seconds;
        }
        return value - 1;
      });
    }, 1000);
    return () => clearInterval(tick);
  }, [paused, router, seconds]);

  return (
    <div className="flex items-center justify-end gap-2 text-[11px] text-muted-foreground">
      <span aria-live="off">
        {paused ? "Paused while tab is hidden" : `Refreshing in ${remaining}s`}
      </span>
      <button
        type="button"
        onClick={() => {
          router.refresh();
          setRemaining(seconds);
        }}
        className="rounded-sm border border-border px-2 py-1 text-[11px] transition-colors hover:bg-muted"
      >
        Refresh now
      </button>
    </div>
  );
}
