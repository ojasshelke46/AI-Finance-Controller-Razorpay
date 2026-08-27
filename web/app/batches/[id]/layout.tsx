import Link from "next/link";

import { BatchTabs } from "@/components/batch-tabs";
import { Pill, batchSeverity } from "@/components/primitives";
import { getBatch } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { batchStatusLabel } from "@/lib/gloss";
import { formatCount } from "@/lib/money";

export const dynamic = "force-dynamic";

export default async function BatchLayout({
  children,
  params,
}: LayoutProps<"/batches/[id]">) {
  const { id } = await params;

  let heading: {
    label: string;
    status: string;
    created: string | null;
    txns: number;
  } | null = null;

  try {
    const detail = await getBatch(id);
    heading = {
      label: detail.batch.label ?? "Unlabelled batch",
      status: detail.batch.status,
      created: detail.batch.created_at,
      txns: detail.totals.txns,
    };
  } catch {
    /* The child page renders the real error; the shell stays usable so
       the operator can still navigate away rather than hitting a dead
       end. It states what it does not know instead of standing in a
       zero: an unread batch has no record count, and saying "0 records"
       would be a figure this console never actually read. */
  }

  return (
    <div className="space-y-4">
      <div className="min-w-0">
        <Link
          href="/batches"
          className="text-[11.5px] text-muted-foreground underline-offset-2 hover:underline"
        >
          ← All batches
        </Link>
        <h1 className="mt-1 flex flex-wrap items-center gap-2 text-[15px] font-semibold tracking-tight">
          {heading?.label ?? "Batch"}
          {heading ? (
            <Pill severity={batchSeverity(heading.status)}>
              {batchStatusLabel(heading.status)}
            </Pill>
          ) : null}
        </h1>
        <p className="mt-0.5 text-[11.5px] text-muted-foreground">
          <span className="num">{id}</span>
          {heading ? (
            <>
              {" · "}
              <span className="num">{formatCount(heading.txns)}</span> records · created{" "}
              <span className="num">{formatDateTime(heading.created)}</span>
            </>
          ) : (
            " · details could not be read"
          )}
        </p>
      </div>

      <BatchTabs id={id} />

      {children}
    </div>
  );
}
