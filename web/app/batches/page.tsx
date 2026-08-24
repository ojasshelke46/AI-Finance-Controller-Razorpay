import Link from "next/link";

import {
  DataTable,
  EmptyState,
  ErrorState,
  Panel,
  PanelHeader,
  Pill,
  Td,
  Th,
  batchSeverity,
} from "@/components/primitives";
import { ApiError, getBatches } from "@/lib/api";
import { formatDateTime, humanise } from "@/lib/format";
import { formatCount, formatPaise, formatRatio } from "@/lib/money";

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
        hint="Start the API with: cd api && uvicorn main:app --port 8000"
      />
    );
  }

  const totalUnexplained = batches.reduce((sum, b) => sum + (b.unexplained_paise ?? 0), 0);

  return (
    <Panel>
      <PanelHeader
        title="Batches"
        description={`${formatCount(batches.length)} runs · ${formatPaise(totalUnexplained)} unexplained in total`}
      />

      {batches.length === 0 ? (
        <EmptyState
          title="No batches yet"
          description="The scheduler opens a batch as soon as it detects new Razorpay activity. Nothing has been picked up so far."
        />
      ) : (
        <DataTable
          head={
            <>
              <Th>Batch</Th>
              <Th>Status</Th>
              <Th>Period</Th>
              <Th align="right">Records</Th>
              <Th align="right">Match rate</Th>
              <Th align="right">Precision</Th>
              <Th align="right">Open</Th>
              <Th align="right">Unexplained</Th>
              <Th align="right">Created</Th>
            </>
          }
        >
          {batches.map((batch) => (
            <tr
              key={batch.id}
              className="border-b border-border transition-colors last:border-0 hover:bg-muted/60"
            >
              <Td>
                <Link
                  href={`/batches/${batch.id}`}
                  className="group inline-flex flex-col focus-visible:outline-none"
                >
                  <span className="text-[12.5px] font-medium text-accent underline-offset-2 group-hover:underline">
                    {batch.label ?? "Unlabelled batch"}
                  </span>
                  <span className="num text-[11px] text-muted-foreground">
                    {batch.id.slice(0, 8)}
                  </span>
                </Link>
              </Td>
              <Td>
                <Pill severity={batchSeverity(batch.status)} title={batch.error_text ?? undefined}>
                  {humanise(batch.status)}
                </Pill>
              </Td>
              <Td className="text-[11.5px] text-muted-foreground">
                {batch.period_start && batch.period_end
                  ? `${batch.period_start} → ${batch.period_end}`
                  : "—"}
              </Td>
              <Td align="right" mono>
                {formatCount(batch.txn_count)}
              </Td>
              <Td align="right" mono>
                {formatRatio(batch.match_rate)}
              </Td>
              <Td align="right" mono>
                {formatRatio(batch.precision)}
              </Td>
              <Td align="right" mono>
                {batch.open_variance_count > 0 ? (
                  <Link
                    href={`/batches/${batch.id}/variances?status=open`}
                    className="text-warn underline-offset-2 hover:underline"
                  >
                    {formatCount(batch.open_variance_count)}
                  </Link>
                ) : (
                  <span className="text-muted-foreground">0</span>
                )}
              </Td>
              <Td align="right" mono className={batch.unexplained_paise > 0 ? "text-warn" : ""}>
                {formatPaise(batch.unexplained_paise)}
              </Td>
              <Td align="right" className="num text-[11.5px] whitespace-nowrap text-muted-foreground">
                {formatDateTime(batch.created_at)}
              </Td>
            </tr>
          ))}
        </DataTable>
      )}
    </Panel>
  );
}
