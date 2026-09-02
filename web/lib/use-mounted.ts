"use client";

import { useEffect, useState } from "react";

/**
 * False during the server render and the first client render, true from
 * the effect onwards.
 *
 * Every string this console derives from a clock is unsafe to render
 * before mount, for two independent reasons:
 *
 *   - Timezone. lib/format.ts builds its Intl formatters without an
 *     explicit timeZone, so they use the runtime's own. The server is
 *     UTC and the operator's browser is not — the same ISO string
 *     renders "08:43:07" on Vercel and "14:13:07" in Asia/Kolkata.
 *     This one fires on every single load outside UTC, which is why it
 *     was invisible in CI and obvious to anyone actually using the app.
 *   - Elapsed time. relativeTime() defaults `now` to Date.now(), so a
 *     value in the sub-45s bucket ("12s ago") changes between the
 *     server render and hydration a moment later.
 *
 * Either produces different text on the two renders, which is React
 * error #418. That is not only console noise: React can give up
 * hydrating the mismatched subtree, leaving the controls inside it
 * mounted-looking but dead — on the status page that subtree contains
 * the "Refresh now" button.
 *
 * The fix is to make the first client render byte-identical to the
 * server's: both emit a placeholder, and the real value is swapped in
 * once only the browser is rendering.
 */
export function useMounted(): boolean {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  return mounted;
}
