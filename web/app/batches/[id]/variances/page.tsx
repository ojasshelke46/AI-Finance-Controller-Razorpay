import { ErrorState } from "@/components/primitives";
import { VarianceQueue } from "@/components/variance-queue";
import { ApiError, getVariances } from "@/lib/api";

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

  return (
    <VarianceQueue
      batchId={id}
      variances={data.variances}
      categories={data.categories}
      activeCategory={category}
      activeStatus={status}
    />
  );
}
