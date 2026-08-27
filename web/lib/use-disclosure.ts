"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * One-at-a-time disclosure that survives its own exit.
 *
 * A row's detail has to stay in the DOM while it collapses, or the
 * collapse never renders. This keeps the mounted id and the open id
 * apart: opening mounts closed and flips open on the next frame so the
 * transition has two values to move between; closing flips shut first
 * and unmounts when the transition is done.
 *
 * Under prefers-reduced-motion both steps happen immediately, so the
 * detail appears and disappears with no size change at all.
 */
export function useDisclosure(durationMs: number) {
  const [mountedId, setMountedId] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const frame = useRef<number | null>(null);

  const clear = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    if (frame.current) cancelAnimationFrame(frame.current);
    timer.current = null;
    frame.current = null;
  }, []);

  useEffect(() => clear, [clear]);

  const toggle = useCallback(
    (id: string) => {
      const reduced =
        typeof window !== "undefined" &&
        window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      clear();

      if (openId === id) {
        setOpenId(null);
        if (reduced) {
          setMountedId(null);
        } else {
          timer.current = setTimeout(() => setMountedId(null), durationMs);
        }
        return;
      }

      setMountedId(id);
      if (reduced) {
        setOpenId(id);
      } else {
        // Mount closed, open on the next frame: a transition needs a
        // value to start from.
        frame.current = requestAnimationFrame(() => setOpenId(id));
      }
    },
    [clear, durationMs, openId],
  );

  return { mountedId, openId, toggle };
}
