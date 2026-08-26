import { Panel, Skeleton } from "@/components/primitives";

/** The funnel's shape, held open while it loads: a rail, six rungs, and
 *  the figure column beside it. */
export default function BatchLoading() {
  return (
    <div
      className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,300px)]"
      aria-busy="true"
      aria-label="Loading this batch"
    >
      <Panel>
        <div className="border-b border-border px-4 py-2.5">
          <Skeleton className="h-3.5 w-40" />
          <Skeleton className="mt-1.5 h-2.5 w-[32rem] max-w-full" />
        </div>
        <ol className="relative px-4 py-3">
          <span aria-hidden className="absolute top-4 bottom-4 left-[19px] w-px bg-border" />
          {Array.from({ length: 6 }, (_, index) => (
            <li key={index} className="relative flex gap-3 py-1.5">
              <Skeleton className="mt-[5px] size-[7px] shrink-0 rounded-[1px]" />
              <div className="min-w-0 flex-1 space-y-1 px-1">
                <div className="flex justify-between">
                  <Skeleton className="h-3 w-32" />
                  <Skeleton className="h-3 w-16" />
                </div>
                <Skeleton className="h-1.5 w-full rounded-[2px]" />
                <Skeleton className="h-2.5 w-24" />
              </div>
            </li>
          ))}
        </ol>
        <div className="border-t border-border px-4 py-2">
          <Skeleton className="h-2.5 w-72 max-w-full" />
        </div>
      </Panel>

      <div className="space-y-4">
        {[2, 5, 3].map((rows, panel) => (
          <Panel key={panel}>
            <div className="border-b border-border px-4 py-2.5">
              <Skeleton className="h-3.5 w-28" />
            </div>
            <div className="px-4">
              {Array.from({ length: rows }, (_, index) => (
                <div
                  key={index}
                  className="flex h-[28px] items-center justify-between border-b border-border last:border-0"
                >
                  <Skeleton className="h-2.5 w-20" />
                  <Skeleton className="h-2.5 w-12" />
                </div>
              ))}
            </div>
          </Panel>
        ))}
        <p className="text-[11.5px] text-muted-foreground">Loading this run…</p>
      </div>
    </div>
  );
}
