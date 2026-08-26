import { Panel, Skeleton } from "@/components/primitives";

/** Question form on the left, the batch's figures on the right. */
export default function QnaLoading() {
  return (
    <div
      className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,300px)]"
      aria-busy="true"
      aria-label="Loading this batch's figures"
    >
      <Panel>
        <div className="border-b border-border px-4 py-2.5">
          <Skeleton className="h-3.5 w-32" />
          <Skeleton className="mt-1.5 h-2.5 w-[30rem] max-w-full" />
        </div>
        <div className="border-b border-border px-4 py-3">
          <Skeleton className="h-2.5 w-16" />
          <div className="mt-1.5 flex gap-2">
            <Skeleton className="h-[34px] flex-1" />
            <Skeleton className="h-[34px] w-14" />
          </div>
          <div className="mt-2.5 flex gap-1.5">
            {[0, 1, 2].map((index) => (
              <Skeleton key={index} className="h-[22px] w-52" />
            ))}
          </div>
        </div>
        <p className="px-4 py-4 text-[11.5px] text-muted-foreground">
          Loading this batch&apos;s figures…
        </p>
      </Panel>

      <Panel className="h-fit">
        <div className="border-b border-border px-4 py-2.5">
          <Skeleton className="h-3.5 w-28" />
        </div>
        <div className="px-4">
          {Array.from({ length: 8 }, (_, index) => (
            <div
              key={index}
              className="flex h-[28px] items-center justify-between border-b border-border last:border-0"
            >
              <Skeleton className="h-2.5 w-24" />
              <Skeleton className="h-2.5 w-14" />
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}
