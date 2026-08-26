import { Panel, Skeleton } from "@/components/primitives";

/** Log shape: a date rule, then fixed-width lines at 28px. */
export default function AuditLoading() {
  return (
    <Panel>
      <div className="border-b border-border px-4 py-2.5">
        <Skeleton className="h-3.5 w-24" />
        <Skeleton className="mt-1.5 h-2.5 w-[30rem] max-w-full" />
      </div>
      <div className="flex gap-8 border-b border-border px-4 py-2.5">
        {[0, 1, 2].map((index) => (
          <div key={index} className="flex items-baseline gap-2">
            <Skeleton className="h-2.5 w-20" />
            <Skeleton className="h-3 w-10" />
          </div>
        ))}
      </div>
      <div className="border-b border-border bg-surface-raised px-4 py-1">
        <Skeleton className="h-2.5 w-24" />
      </div>
      <div className="px-4">
        {Array.from({ length: 14 }, (_, index) => (
          <div key={index} className="flex h-[28px] items-center gap-3 border-b border-border">
            <Skeleton className="h-2.5 w-12" />
            <Skeleton className="h-2.5 w-14" />
            <Skeleton className="h-2.5 w-16" />
            <Skeleton className="h-2.5 flex-1" />
          </div>
        ))}
      </div>
      <p className="px-4 py-2.5 text-[11.5px] text-muted-foreground">Reading the trail…</p>
    </Panel>
  );
}
