import { createFileRoute } from "@tanstack/react-router";

import { loadMarketResult, loadRecommendationsResult } from "@/data/loader";
import { Dashboard } from "@/pages/dashboard";

export const Route = createFileRoute("/")({
  loader: async () => {
    const [recsResult, marketResult] = await Promise.all([
      loadRecommendationsResult(),
      loadMarketResult(),
    ]);
    return { recsResult, marketResult };
  },
  component: IndexComponent,
});

function IndexComponent() {
  const { recsResult, marketResult } = Route.useLoaderData();
  return <Dashboard initialRecsResult={recsResult} initialMarketResult={marketResult} />;
}
