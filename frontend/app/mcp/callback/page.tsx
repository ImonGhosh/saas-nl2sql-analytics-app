"use client";

import { useAuth } from "@clerk/nextjs";
import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

const backendUrl =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://127.0.0.1:8000";

export default function McpCallbackPage() {
  const { getToken, isLoaded } = useAuth();
  const searchParams = useSearchParams();
  const router = useRouter();
  const [status, setStatus] = useState("Authorizing...");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!isLoaded) return;

    const finalizeAuth = async () => {
      const queryCode = searchParams.get("code");
      const queryState = searchParams.get("state");
      const queryError = searchParams.get("error");
      const queryErrorDesc = searchParams.get("error_description");

      if (queryError) {
        setError(
          queryErrorDesc
            ? `${queryError}: ${queryErrorDesc}`
            : `OAuth error: ${queryError}`
        );
        return;
      }

      let code = queryCode;
      let state = queryState;

      if ((!code || !state) && typeof window !== "undefined") {
        const hashParams = new URLSearchParams(window.location.hash.slice(1));
        const hashError = hashParams.get("error");
        const hashErrorDesc = hashParams.get("error_description");
        if (hashError) {
          setError(
            hashErrorDesc
              ? `${hashError}: ${hashErrorDesc}`
              : `OAuth error: ${hashError}`
          );
          return;
        }
        code = code ?? hashParams.get("code");
        state = state ?? hashParams.get("state");
      }

      if (!code || !state) {
        setError(
          "Missing OAuth code or state. Verify the redirect URI matches exactly."
        );
        return;
      }

      const token = await getToken();
      if (!token) {
        setError("Authentication required.");
        return;
      }

      try {
        setStatus("Authorized");
        setStatus("Extracting metadata...");

        const response = await fetch(`${backendUrl}/mcp/auth/callback`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({ code, state }),
        });

        const text = await response.text();
        if (!response.ok) {
          throw new Error(text || `Request failed (${response.status})`);
        }

        setStatus("Ready");
        window.setTimeout(() => {
          router.replace("/?mcp=ready");
        }, 800);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Authorization failed.");
      }
    };

    void finalizeAuth();
  }, [getToken, isLoaded, router, searchParams]);

  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top_left,_#e2e8f0_0%,_#f8fafc_35%,_#f1f5f9_100%)] text-slate-900">
      <section className="flex min-h-screen items-center justify-center px-6">
        <div className="w-full max-w-lg rounded-2xl border border-slate-200 bg-white/80 p-8 text-center shadow-sm backdrop-blur">
          <h1 className="text-2xl font-semibold text-slate-900">
            Supabase Authorization
          </h1>
          {error ? (
            <p className="mt-4 text-sm font-semibold text-red-600">{error}</p>
          ) : (
            <p className="mt-4 text-sm font-semibold text-slate-700">{status}</p>
          )}
        </div>
      </section>
    </main>
  );
}
