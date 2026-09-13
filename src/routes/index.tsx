import { createFileRoute } from "@tanstack/react-router";

import { loadMarket, loadRecommendations } from "@/data/loader";
import { Dashboard } from "@/pages/Dashboard";

export const Route = createFileRoute("/")({
  loader: async () => {
    const [recommendations, marketPayload] = await Promise.all([
      loadRecommendations(),
      loadMarket(),
    ]);
    return { recommendations, marketPayload };
  },
  component: IndexComponent,
});

function IndexComponent() {
  const { recommendations, marketPayload } = Route.useLoaderData();
  return <Dashboard initialData={recommendations} initialMarketPayload={marketPayload} />;
}
