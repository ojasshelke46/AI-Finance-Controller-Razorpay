import { ErrorState } from "@/components/primitives";
import { VarianceQueue } from "@/components/variance-queue";
import { ApiError, getBatch, getVariances } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function VariancesPage({
  params,
  searchParams,
}: PageProps<"/batches/[id]/variances">) {
  const { id } = await params;
  const query = await searchParams;

  const category = typeof query.category === "string" ? query.category : undefined;
  const status = typeof query.status === "string" ? query.status : undefined;

  let data;
  try {
    data = await getVariances(id, { category, status });
  } catch (error) {
    return (
      <ErrorState
        title="Cannot load the variance queue"
        detail={error instanceof ApiError ? error.message : "Unknown error"}
        hint="This batch's variances could not be read. The queue reloads when the service is reachable again."
      />
    );
  }

  // An empty queue is only good news if the run actually finished with
  // records in it, so the queue needs the batch's own state to say which
  // kind of empty this is. Failing to read it is not worth blocking the
  // queue over — the empty state just falls back to its neutral wording.
  let detail = null;
  try {
    detail = await getBatch(id);
  } catch {
    detail = null;
  }

  return (
    <VarianceQueue
      batchId={id}
      variances={data.variances}
      categories={data.categories}
      activeCategory={category}
      activeStatus={status}
      batchStatus={detail?.batch.status}
      failedStage={failedStageOf(detail?.batch.error_text)}
      totalTxns={detail?.totals.txns}
    />
  );
}

/** error_text is written as "stage <name>: <message>", so the stage name
 *  is recoverable without a separate column. Returns null for anything
 *  that does not match rather than guessing at a stage. */
function failedStageOf(errorText: string | null | undefined): string | null {
  if (!errorText) return null;
  const match = /^stage ([a-z0-9_]+):/i.exec(errorText.trim());
  return match ? match[1] : null;
}
