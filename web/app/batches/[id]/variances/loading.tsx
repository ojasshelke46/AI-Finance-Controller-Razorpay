import { Panel, Skeleton } from "@/components/primitives";

/**
 * The queue's own shape: summary strip, filter row, then rows at the
 * 28px the real table uses, so nothing moves when the data lands.
 */
export default function VariancesLoading() {
  return (
    <Panel>
      <div className="border-b border-border px-4 py-2.5">
        <Skeleton className="h-3.5 w-32" />
        <Skeleton className="mt-1.5 h-2.5 w-[38rem] max-w-full" />
      </div>

      <div className="flex gap-8 border-b border-border px-4 py-2.5">
        {[0, 1, 2].map((index) => (
          <div key={index} className="flex items-baseline gap-2">
            <Skeleton className="h-2.5 w-20" />
            <Skeleton className="h-3 w-24" />
          </div>
        ))}
      </div>

      <div className="flex gap-1.5 border-b border-border px-4 py-2.5">
        {[0, 1, 2, 3, 4].map((index) => (
          <Skeleton key={index} className="h-[22px] w-20" />
        ))}
      </div>

      <div className="px-4">
        {Array.from({ length: 12 }, (_, index) => (
          <div key={index} className="flex h-[28px] items-center gap-4 border-b border-border">
            <Skeleton className="h-3 w-24" />
            <Skeleton className="h-3 w-28" />
            <Skeleton className="h-3 flex-1" />
            <Skeleton className="h-3 w-12" />
          </div>
        ))}
      </div>

      <p className="px-4 py-2.5 text-[11.5px] text-muted-foreground">
        Loading the variance queue…
      </p>
    </Panel>
  );
}
