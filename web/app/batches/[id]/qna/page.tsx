import { Panel, PanelHeader } from "@/components/primitives";
import { QnaConsole } from "@/components/qna-console";
import { getBatch } from "@/lib/api";
import { formatCount, formatPaise, formatRatio } from "@/lib/money";

export const dynamic = "force-dynamic";

export default async function QnaPage({ params }: PageProps<"/batches/[id]/qna">) {
  const { id } = await params;

  // The same figures the model is given, shown to the operator, so the
  // answer can be checked against its source rather than trusted.
  let facts: { label: string; value: string }[] = [];
  try {
    const detail = await getBatch(id);
    const openStat = detail.variances_by_status.open;
    facts = [
      { label: "Records ingested", value: formatCount(detail.totals.txns) },
      { label: "Records matched", value: formatCount(detail.totals.matched_txns) },
      { label: "Match rate", value: formatRatio(detail.score?.match_rate) },
      { label: "Precision", value: formatRatio(detail.score?.precision) },
      { label: "Recall", value: formatRatio(detail.score?.recall) },
      { label: "Open variances", value: formatCount(openStat?.count ?? 0) },
      { label: "Open value", value: formatPaise(openStat?.paise ?? 0) },
      { label: "Match groups", value: formatCount(detail.totals.match_groups) },
    ];
  } catch {
    /* The console still works without the fact panel; the answer itself
       carries its own verification. */
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,320px)]">
      <QnaConsole batchId={id} />

      <Panel className="h-fit">
        <PanelHeader
          title="Figures available"
          description="The answer can only be built from these. Anything else, and it is withheld."
        />
        <dl className="divide-y divide-border">
          {facts.length === 0 ? (
            <p className="px-4 py-4 text-[12px] text-muted-foreground">
              Could not load this batch&apos;s figures.
            </p>
          ) : (
            facts.map((fact) => (
              <div key={fact.label} className="flex items-baseline justify-between gap-3 px-4 py-2">
                <dt className="text-[12px] text-muted-foreground">{fact.label}</dt>
                <dd className="num text-[12px]">{fact.value}</dd>
              </div>
            ))
          )}
        </dl>
      </Panel>
    </div>
  );
}
