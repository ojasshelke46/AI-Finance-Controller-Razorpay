import { Panel, Skeleton } from "@/components/primitives";

/** Batch list shape: summary strip, then dense rows at 28px. */
export default function BatchesLoading() {
  return (
    <Panel>
      <div className="border-b border-border px-4 py-2.5">
        <Skeleton className="h-3.5 w-24" />
        <Skeleton className="mt-1.5 h-2.5 w-80 max-w-full" />
      </div>
      <div className="flex gap-8 border-b border-border px-4 py-2.5">
        {[0, 1, 2, 3].map((index) => (
          <div key={index} className="flex items-baseline gap-2">
            <Skeleton className="h-2.5 w-16" />
            <Skeleton className="h-3 w-20" />
          </div>
        ))}
      </div>
      <div className="px-4">
        {Array.from({ length: 10 }, (_, index) => (
          <div key={index} className="flex h-[28px] items-center gap-4 border-b border-border">
            <Skeleton className="h-3 w-32" />
            <Skeleton className="h-3 w-20" />
            <Skeleton className="h-3 flex-1" />
            <Skeleton className="h-3 w-16" />
          </div>
        ))}
      </div>
      <p className="px-4 py-2.5 text-[11.5px] text-muted-foreground">Loading batches…</p>
    </Panel>
  );
}
