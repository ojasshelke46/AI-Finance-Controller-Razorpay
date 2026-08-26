"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { formatTime } from "@/lib/format";

/**
 * Re-fetches the server component on an interval so the status page is
 * genuinely live rather than a snapshot of whenever it was opened.
 *
 * Two deliberate choices: it pauses while the tab is hidden (a
 * background tab polling an API for hours is rude), and it shows both
 * the time the figures were read and the countdown, so the operator can
 * tell the difference between "nothing is happening" and "this page is
 * stale".
 */
export function AutoRefresh({
  seconds = 30,
  asOf,
}: {
  seconds?: number;
  asOf?: string | null;
}) {
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
    <div className="flex shrink-0 items-baseline gap-3 text-[11px] text-muted-foreground">
      {asOf ? (
        <span>
          Read at <time dateTime={asOf} className="num">{formatTime(asOf)}</time>
        </span>
      ) : null}
      <span aria-live="off">
        {paused ? "paused, tab hidden" : <>refreshing in <span className="num">{remaining}s</span></>}
      </span>
      <button
        type="button"
        onClick={() => {
          router.refresh();
          setRemaining(seconds);
        }}
        className="rounded-sm border border-border px-2 py-[3px] text-[11px] transition-colors hover:bg-muted"
      >
        Refresh now
      </button>
    </div>
  );
}
