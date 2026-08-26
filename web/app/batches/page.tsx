import { BatchTable } from "@/components/batch-table";
import { EmptyState, ErrorState, Panel, PanelHeader } from "@/components/primitives";
import { ApiError, getBatches } from "@/lib/api";
import { formatCount } from "@/lib/money";

export const dynamic = "force-dynamic";

export default async function BatchesPage() {
  let batches;
  try {
    ({ batches } = await getBatches());
  } catch (error) {
    return (
      <ErrorState
        title="Cannot load batches"
        detail={error instanceof ApiError ? error.message : "Unknown error"}
        hint="The list reloads when the reconciliation service is reachable again."
      />
    );
  }

  return (
    <Panel>
      <PanelHeader
        title="Batches"
        description="Every run, newest first. Failed and stalled runs are marked on the row."
        right={
          <span className="num text-[11.5px] text-muted-foreground">
            {formatCount(batches.length)} runs
          </span>
        }
      />

      {batches.length === 0 ? (
        <EmptyState
          title="No batches yet"
          description="The scheduler opens a batch as soon as it detects new Razorpay activity. Nothing has been picked up so far."
        />
      ) : (
        <BatchTable batches={batches} />
      )}
    </Panel>
  );
}
