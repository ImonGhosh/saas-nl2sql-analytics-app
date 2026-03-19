"use client";

import {
  SignInButton,
  SignedIn,
  SignedOut,
  UserButton,
  useAuth,
} from "@clerk/nextjs";
import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import type { VisualizationSpec } from "vega-embed";
import ChartLibrary, { type LibraryChart } from "./ChartLibrary";
import SqlChatbot from "./SqlChatbot";
import AnalyticsAgent from "./AnalyticsAgent";

const backendUrl =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://127.0.0.1:8000";
const clerkJwtTemplate =
  process.env.NEXT_PUBLIC_CLERK_JWT_TEMPLATE ?? "backend";

export default function LandingPage() {
  const { getToken, isSignedIn, isLoaded } = useAuth();
  const searchParams = useSearchParams();
  const [activeTab, setActiveTab] = useState<"sql" | "analytics">("sql");
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [projectRef, setProjectRef] = useState("");
  const [connectStatus, setConnectStatus] = useState("");
  const [connectError, setConnectError] = useState("");
  const [isConnecting, setIsConnecting] = useState(false);
  const [isConnected, setIsConnected] = useState(false);
  const [isStatusLoading, setIsStatusLoading] = useState(true);
  const [libraryCharts, setLibraryCharts] = useState<LibraryChart[]>([]);

  const parseLibraryItem = (item: {
    summary?: string;
    chart_spec?: VisualizationSpec;
    data?: Record<string, unknown>[];
    sql?: string;
    saved_at?: string;
  }): LibraryChart | null => {
    if (!item.chart_spec || typeof item.chart_spec !== "object") {
      return null;
    }
    const data = Array.isArray(item.data) ? item.data : [];
    return {
      spec: item.chart_spec,
      data,
      summary: typeof item.summary === "string" ? item.summary : undefined,
      sql: typeof item.sql === "string" ? item.sql : undefined,
      savedAt: typeof item.saved_at === "string" ? item.saved_at : "",
    };
  };

  const closeModal = () => {
    setIsModalOpen(false);
    setConnectError("");
    setConnectStatus("");
    setProjectRef("");
  };

  useEffect(() => {
    const status = searchParams.get("mcp");
    if (status !== "ready") return;

    setIsModalOpen(true);
    setConnectStatus("Ready");
    setConnectError("");
    setIsConnecting(false);

    const timer = window.setTimeout(() => {
      closeModal();
      const url = new URL(window.location.href);
      url.searchParams.delete("mcp");
      window.history.replaceState({}, "", url.toString());
    }, 800);

    return () => window.clearTimeout(timer);
  }, [searchParams]);

  useEffect(() => {
    let isActive = true;

    const fetchStatus = async () => {
      if (!isLoaded) {
        if (isActive) {
          setIsConnected(false);
          setIsStatusLoading(true);
        }
        return;
      }

      if (!isSignedIn) {
        if (isActive) {
          setIsConnected(false);
          setIsStatusLoading(false);
        }
        return;
      }

      if (isActive) setIsStatusLoading(true);

      try {
        const token = await getToken({
          template: clerkJwtTemplate,
          skipCache: true,
        });
        if (!token) {
          if (isActive) setIsConnected(false);
          return;
        }

        const response = await fetch(`${backendUrl}/mcp/status`, {
          headers: {
            Authorization: `Bearer ${token}`,
          },
        });

        if (!response.ok) {
          if (isActive) setIsConnected(false);
          return;
        }

        const data = (await response.json()) as { connected?: boolean };
        if (isActive) setIsConnected(Boolean(data.connected));
      } catch {
        if (isActive) setIsConnected(false);
      } finally {
        if (isActive) setIsStatusLoading(false);
      }
    };

    void fetchStatus();

    return () => {
      isActive = false;
    };
  }, [getToken, isSignedIn, isLoaded]);

  useEffect(() => {
    let isActive = true;

    const loadLibrary = async () => {
      if (!isConnected || activeTab !== "analytics" || !isSignedIn) {
        return;
      }
      try {
        const token = await getToken({ template: clerkJwtTemplate });
        if (!token) return;

        const response = await fetch(`${backendUrl}/charts/library`, {
          headers: {
            Authorization: `Bearer ${token}`,
          },
        });

        if (!response.ok) {
          throw new Error(`Request failed (${response.status}).`);
        }

        const payload = (await response.json()) as {
          charts?: Array<{
            summary?: string;
            chart_spec?: VisualizationSpec;
            data?: Record<string, unknown>[];
            sql?: string;
            saved_at?: string;
          }>;
        };

        const items = Array.isArray(payload.charts) ? payload.charts : [];
        const parsed = items
          .map(parseLibraryItem)
          .filter((item): item is LibraryChart => item !== null);

        if (isActive) setLibraryCharts(parsed);
      } catch {
        if (isActive) setLibraryCharts([]);
      }
    };

    void loadLibrary();

    return () => {
      isActive = false;
    };
  }, [getToken, isConnected, activeTab, isSignedIn]);

  const handleDisconnect = async () => {
    try {
      const token = await getToken({ template: clerkJwtTemplate });
      if (!token) {
        return;
      }

      await fetch(`${backendUrl}/mcp/disconnect`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });
    } finally {
      setIsConnected(false);
      setLibraryCharts([]);
    }
  };

  const handleConnect = async () => {
    if (!projectRef.trim() || isConnecting) return;
    setIsConnecting(true);
    setConnectStatus("");
    setConnectError("");

    try {
      const token = await getToken({ template: clerkJwtTemplate });
      if (!token) {
        setConnectError("Authentication required.");
        return;
      }

      setConnectStatus("Authorizing...");
      const response = await fetch(`${backendUrl}/mcp/auth/start`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          project_ref: projectRef.trim(),
        }),
      });

      const data = (await response.json()) as { auth_url?: string; detail?: string };
      if (!response.ok) {
        throw new Error(data.detail || `Request failed (${response.status})`);
      }

      if (!data.auth_url) {
        throw new Error("Missing authorization URL.");
      }

      window.location.assign(data.auth_url);
    } catch (error) {
      setConnectError(
        error instanceof Error ? error.message : "Authorization failed."
      );
    } finally {
      setIsConnecting(false);
    }
  };

  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top_left,_#e2e8f0_0%,_#f8fafc_35%,_#f1f5f9_100%)] text-slate-900">
      <nav className="flex w-full items-center justify-end border-b border-slate-200 bg-white/70 px-6 py-4 backdrop-blur">
        <SignedOut>
          <SignInButton mode="modal">
            <button className="rounded-md bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-700">
              Log in
            </button>
          </SignInButton>
        </SignedOut>
        <SignedIn>
          <UserButton />
        </SignedIn>
      </nav>

      <SignedOut>
        <section className="flex min-h-[calc(100vh-73px)] flex-col items-center justify-center px-6 text-center">
          <h1 className="text-balance text-5xl font-semibold tracking-tight text-slate-900 md:text-7xl">
            AI SQL &amp; Analytics Agent
          </h1>
          <SignInButton mode="modal">
            <button className="mt-8 rounded-md bg-slate-900 px-8 py-3 text-base font-semibold text-white transition hover:bg-slate-700">
              Try it out for free
            </button>
          </SignInButton>
        </section>
      </SignedOut>

      <SignedIn>
        <section className="flex min-h-[calc(100vh-73px)] w-full items-start justify-center px-6 py-12">
          <div
            className={`w-full ${
              isConnected && activeTab === "analytics"
                ? "max-w-6xl"
                : "max-w-4xl"
            }`}
          >
            <div className="flex items-center gap-3 rounded-xl border border-slate-200 bg-white/80 p-2 shadow-sm">
              <button
                type="button"
                onClick={() => setActiveTab("sql")}
                className={`flex-1 rounded-lg px-4 py-2 text-sm font-semibold transition ${
                  activeTab === "sql"
                    ? "bg-slate-900 text-white"
                    : "text-slate-600 hover:bg-slate-100"
                }`}
              >
                SQL Agent
              </button>
              <button
                type="button"
                onClick={() => setActiveTab("analytics")}
                className={`flex-1 rounded-lg px-4 py-2 text-sm font-semibold transition ${
                  activeTab === "analytics"
                    ? "bg-slate-900 text-white"
                    : "text-slate-600 hover:bg-slate-100"
                }`}
              >
                Analytics Agent
              </button>
            </div>

            {isStatusLoading ? (
              <div className="mt-10 rounded-2xl border border-dashed border-slate-300 bg-white/70 px-6 py-16 text-center">
                <div className="flex flex-col items-center justify-center gap-3 text-slate-600">
                  <span
                    className="h-6 w-6 animate-spin rounded-full border-2 border-slate-300 border-t-slate-600"
                    aria-hidden="true"
                  />
                  <p className="text-sm font-semibold">Loading your data...</p>
                </div>
              </div>
            ) : isConnected ? (
              activeTab === "sql" ? (
                <div className="mt-10 rounded-2xl border border-slate-200 bg-white/80 px-6 py-8 text-left shadow-sm">
                  <SqlChatbot onLogout={handleDisconnect} />
                </div>
              ) : (
                <div className="mt-10 flex flex-col gap-6 lg:flex-row lg:items-start">
                  <div className="w-full max-w-4xl rounded-2xl border border-slate-200 bg-white/80 px-6 py-8 text-left shadow-sm">
                    <AnalyticsAgent
                      onLogout={handleDisconnect}
                      libraryCharts={libraryCharts}
                      setLibraryCharts={setLibraryCharts}
                    />
                  </div>
                  <ChartLibrary charts={libraryCharts} maxCharts={4} />
                </div>
              )
            ) : (
              <div className="mt-10 rounded-2xl border border-dashed border-slate-300 bg-white/70 px-6 py-16 text-center">
                <button
                  type="button"
                  onClick={() => setIsModalOpen(true)}
                  className="inline-flex h-20 w-20 items-center justify-center rounded-full border-2 border-slate-300 bg-white text-5xl font-semibold text-slate-700 transition hover:border-slate-400 hover:text-slate-900"
                  aria-label={`Open ${
                    activeTab === "sql" ? "SQL" : "Analytics"
                  } connection modal`}
                >
                  +
                </button>
              </div>
            )}
          </div>
        </section>
      </SignedIn>

      {isModalOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-6"
          role="dialog"
          aria-modal="true">
          <div className="relative w-full max-w-lg rounded-2xl bg-white p-6 text-left shadow-xl">
            <h2 className="text-xl font-semibold text-slate-900">
              Connect to Supabase
            </h2>
            <p className="mt-2 text-sm text-slate-600">
              Enter your project ref and authorize access.
            </p>
            <label className="mt-4 block text-sm font-semibold text-slate-700">
              Project ref
              <input
                type="text"
                placeholder="your-project-ref"
                value={projectRef}
                onChange={(event) => setProjectRef(event.target.value)}
                className="mt-2 w-full rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-900 shadow-sm focus:border-slate-400 focus:outline-none"
              />
            </label>
            <p className="mt-2 text-xs text-slate-500">
              Find your project ref in Supabase Dashboard -&gt; Settings -&gt; General.
            </p>

            {connectError && (
              <p className="mt-4 text-sm font-semibold text-red-600">
                {connectError}
              </p>
            )}
            {connectStatus && (
              <p className="mt-4 text-sm font-semibold text-emerald-700">
                {connectStatus}
              </p>
            )}

            <div className="mt-6 flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={handleConnect}
                disabled={!projectRef.trim() || isConnecting}
                className="rounded-md bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-700 disabled:cursor-not-allowed disabled:bg-slate-400"
              >
                {isConnecting ? "Authorizing..." : "Authorize with Supabase"}
              </button>
              <button
                type="button"
                onClick={closeModal}
                className="rounded-md border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-100"
              >
                Close
              </button>
            </div>

          </div>
        </div>
      )}
    </main>
  );
}
