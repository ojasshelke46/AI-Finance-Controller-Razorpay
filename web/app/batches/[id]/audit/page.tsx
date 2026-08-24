import { AuditTrail } from "@/components/audit-trail";
import { ErrorState } from "@/components/primitives";
import { ApiError, getAudit } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function AuditPage({ params, searchParams }: PageProps<"/batches/[id]/audit">) {
  const { id } = await params;
  const query = await searchParams;

  const actor = typeof query.actor === "string" ? query.actor : undefined;
  const step = typeof query.step === "string" ? query.step : undefined;

  let data;
  try {
    data = await getAudit(id, { actor, step });
  } catch (error) {
    return (
      <ErrorState
        title="Cannot load the audit trail"
        detail={error instanceof ApiError ? error.message : "Unknown error"}
      />
    );
  }

  return (
    <AuditTrail
      batchId={id}
      events={data.events}
      actors={data.actors}
      steps={data.steps}
      activeActor={actor}
      activeStep={step}
    />
  );
}
