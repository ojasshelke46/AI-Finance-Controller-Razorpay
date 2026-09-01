"use client";

import { useCallback, useEffect, useRef, useState } from "react";
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
 *
 * The countdown is derived from a DEADLINE rather than decremented, and
 * router.refresh() is called from the interval callback rather than
 * from inside a setState updater. Both matter:
 *
 *   - A state updater must be pure. React may re-run it during render,
 *     and calling router.refresh() there updates the Router while this
 *     component is rendering ("Cannot update a component while
 *     rendering a different component").
 *   - Browsers throttle timers in inactive tabs, so a decrementing
 *     counter drifts: it would claim "refreshing in 12s" long after
 *     that much time had actually passed. Reading the clock each tick
 *     cannot drift, which is the honest thing for a display whose whole
 *     job is telling an operator how stale the figures are.
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
  const deadlineRef = useRef<number>(Date.now() + seconds * 1000);

  const restart = useCallback(() => {
    deadlineRef.current = Date.now() + seconds * 1000;
    setRemaining(seconds);
  }, [seconds]);

  useEffect(() => {
    const onVisibility = () => setPaused(document.hidden);
    onVisibility();
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);

  useEffect(() => {
    if (paused) return;
    // Resuming from a hidden tab starts a fresh window rather than
    // firing immediately for however long the tab was away.
    deadlineRef.current = Date.now() + seconds * 1000;
    setRemaining(seconds);

    const tick = setInterval(() => {
      const left = Math.ceil((deadlineRef.current - Date.now()) / 1000);
      if (left > 0) {
        setRemaining(left);
        return;
      }
      deadlineRef.current = Date.now() + seconds * 1000;
      setRemaining(seconds);
      router.refresh();
    }, 250);
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
          restart();
          router.refresh();
        }}
        className="rounded-sm border border-border px-2 py-[3px] text-[11px] hover:bg-muted"
      >
        Refresh now
      </button>
    </div>
  );
}
