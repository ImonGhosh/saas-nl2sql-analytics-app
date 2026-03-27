import { Suspense } from "react";
import McpCallbackClientPage from "./ClientPage";

export default function McpCallbackPage() {
  return (
    <Suspense
      fallback={
        <main className="min-h-screen bg-[radial-gradient(circle_at_top_left,_#e2e8f0_0%,_#f8fafc_35%,_#f1f5f9_100%)] text-slate-900">
          <section className="flex min-h-screen items-center justify-center px-6">
            <div className="w-full max-w-lg rounded-2xl border border-slate-200 bg-white/80 p-8 text-center shadow-sm backdrop-blur">
              <h1 className="text-2xl font-semibold text-slate-900">
                Supabase Authorization
              </h1>
              <p className="mt-4 text-sm font-semibold text-slate-700">
                Loading...
              </p>
            </div>
          </section>
        </main>
      }
    >
      <McpCallbackClientPage />
    </Suspense>
  );
}
