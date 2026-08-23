"use client";

import { useEffect, useState } from "react";

type Health = {
  status: string;
  supabase_url_configured: boolean;
  supabase_anon_key_configured: boolean;
};

type ApiHealth = {
  status: string;
  supabase_url_configured: boolean;
  supabase_service_key_configured: boolean;
  byteplus_api_key_configured: boolean;
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export default function HealthPage() {
  const [web, setWeb] = useState<Health | null>(null);
  const [api, setApi] = useState<ApiHealth | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/health")
      .then((r) => r.json())
      .then(setWeb)
      .catch((e) => setWeb({ status: `error: ${e}`, supabase_url_configured: false, supabase_anon_key_configured: false }));

    fetch(`${API_BASE}/health`)
      .then((r) => r.json())
      .then(setApi)
      .catch((e) => setApiError(String(e)));
  }, []);

  return (
    <main className="mx-auto max-w-lg p-8 space-y-6">
      <h1 className="text-2xl font-semibold">Health Check</h1>

      <section>
        <h2 className="font-medium mb-2">Web (Next.js)</h2>
        <pre className="rounded bg-muted p-4 text-sm">{JSON.stringify(web, null, 2)}</pre>
      </section>

      <section>
        <h2 className="font-medium mb-2">API (FastAPI)</h2>
        {apiError ? (
          <p className="text-sm text-red-500">Could not reach API at {API_BASE}: {apiError}</p>
        ) : (
          <pre className="rounded bg-muted p-4 text-sm">{JSON.stringify(api, null, 2)}</pre>
        )}
      </section>
    </main>
  );
}
