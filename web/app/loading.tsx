import { Skeleton } from "@/components/primitives";

/**
 * Matches the shape of the status page rather than spinning: the
 * masthead line, the four autonomy figures, then the two figure groups.
 * An operator glancing at a loading page should already see where the
 * numbers are going to land.
 */
export default function StatusLoading() {
  return (
    <div className="space-y-5" aria-busy="true" aria-label="Loading the run status">
      <section className="border-b border-border-strong pb-5">
        <div className="flex items-start gap-2.5">
          <Skeleton className="mt-[7px] size-[7px] rounded-full" />
          <div className="space-y-1.5">
            <Skeleton className="h-4 w-52" />
            <Skeleton className="h-3 w-96 max-w-full" />
          </div>
        </div>
        <dl className="mt-4 grid grid-cols-2 gap-x-8 gap-y-4 sm:grid-cols-4">
          {[0, 1, 2, 3].map((index) => (
            <div key={index} className="space-y-1.5">
              <Skeleton className="h-2.5 w-24" />
              <Skeleton className={index < 2 ? "h-7 w-28" : "h-5 w-16"} />
              <Skeleton className="h-2.5 w-32" />
            </div>
          ))}
        </dl>
      </section>

      <div className="grid gap-5 lg:grid-cols-2">
        {[0, 1].map((group) => (
          <section key={group} className="space-y-2.5">
            <Skeleton className="h-2.5 w-32" />
            <div className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
              {[0, 1, 2, 3].slice(0, group === 0 ? 2 : 4).map((index) => (
                <div key={index} className="space-y-1.5">
                  <Skeleton className="h-2.5 w-20" />
                  <Skeleton className="h-5 w-24" />
                </div>
              ))}
            </div>
          </section>
        ))}
      </div>

      <p className="text-[11.5px] text-muted-foreground">Reading the current run state…</p>
    </div>
  );
}
