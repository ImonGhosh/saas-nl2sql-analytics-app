import { Suspense } from "react";
import LandingPage from "@/components/LandingPage";

export default function Home() {
  return (
    <Suspense
      fallback={
        <main className="min-h-screen bg-[#0b1220] text-[#E5ECF5]">
          <div className="mx-auto flex min-h-screen max-w-6xl items-center justify-center px-6">
            <div className="w-full max-w-lg rounded-2xl border border-[#1e2a3f] bg-[#0f1a2b] p-8 text-center shadow-lg">
              <h1 className="text-2xl font-semibold">Loading...</h1>
              <p className="mt-3 text-sm text-[#9fb1ca]">
                Preparing the workspace
              </p>
            </div>
          </div>
        </main>
      }
    >
      <LandingPage />
    </Suspense>
  );
}
