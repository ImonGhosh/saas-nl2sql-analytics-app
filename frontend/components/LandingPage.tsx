"use client";

import {
  SignInButton,
  SignedIn,
  SignedOut,
  UserButton,
  useAuth,
} from "@clerk/nextjs";
import { useEffect, useState } from "react";
import SqlChatbot from "./SqlChatbot";

const backendUrl =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://127.0.0.1:8000";

export default function LandingPage() {
  const { getToken, isSignedIn, isLoaded } = useAuth();
  const [activeTab, setActiveTab] = useState<"sql" | "analytics">("sql");
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isInfoOpen, setIsInfoOpen] = useState(false);
  const [connectionString, setConnectionString] = useState("");
  const [connectStatus, setConnectStatus] = useState("");
  const [connectError, setConnectError] = useState("");
  const [isConnecting, setIsConnecting] = useState(false);
  const [isConnected, setIsConnected] = useState(false);
  const [isStatusLoading, setIsStatusLoading] = useState(true);

  const closeModal = () => {
    setIsModalOpen(false);
    setIsInfoOpen(false);
    setConnectError("");
    setConnectStatus("");
  };

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
        const token = await getToken({ skipCache: true });
        if (!token) {
          if (isActive) setIsConnected(false);
          return;
        }

        const response = await fetch(`${backendUrl}/db/status`, {
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

  const handleDisconnect = async () => {
    try {
      const token = await getToken();
      if (!token) {
        return;
      }

      await fetch(`${backendUrl}/db/disconnect`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });
    } finally {
      setIsConnected(false);
    }
  };

  const handleConnect = async () => {
    if (!connectionString.trim() || isConnecting) return;
    setIsConnecting(true);
    setConnectStatus("");
    setConnectError("");

    try {
      const token = await getToken();
      if (!token) {
        setConnectError("Authentication required.");
        return;
      }

      const response = await fetch(`${backendUrl}/db/connect`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          connection_string: connectionString.trim(),
        }),
      });

      const text = await response.text();
      if (!response.ok) {
        throw new Error(text || `Request failed (${response.status})`);
      }

      setConnectStatus(text);
      setIsConnected(true);
      setTimeout(() => {
        closeModal();
      }, 800);
    } catch (error) {
      setConnectError(
        error instanceof Error ? error.message : "Connection failed."
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
          <div className="w-full max-w-4xl">
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

            <div
              className={`mt-10 rounded-2xl border ${
                isConnected && activeTab === "sql"
                  ? "border-slate-200 bg-white/80 px-6 py-8 text-left shadow-sm"
                  : "border-dashed border-slate-300 bg-white/70 px-6 py-16 text-center"
              }`}>
              {isStatusLoading ? (
                <div className="flex flex-col items-center justify-center gap-3 text-slate-600">
                  <span
                    className="h-6 w-6 animate-spin rounded-full border-2 border-slate-300 border-t-slate-600"
                    aria-hidden="true"
                  />
                  <p className="text-sm font-semibold">
                    Loading your data...
                  </p>
                </div>
                ) : isConnected ? (
                activeTab === "sql" ? (
                  <SqlChatbot onLogout={handleDisconnect} />
                ) : (
                  <button
                    type="button"
                    onClick={handleDisconnect}
                    className="rounded-md border border-slate-300 bg-white px-6 py-3 text-sm font-semibold text-slate-700 transition hover:bg-slate-100"
                  >
                    Logout
                  </button>
                )
                ) : (
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
              )}
            </div>
          </div>
        </section>
      </SignedIn>

      {isModalOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-6"
          role="dialog"
          aria-modal="true"
        >
          <div className="relative w-full max-w-lg rounded-2xl bg-white p-6 text-left shadow-xl">
            <h2 className="text-xl font-semibold text-slate-900">
              Connect to Supabase
            </h2>
            <p className="mt-2 text-sm text-slate-600">
              Paste your Postgres connection string below.
            </p>
            <label className="mt-4 block text-sm font-semibold text-slate-700">
              Connection string
              <input
                type="password"
                placeholder="postgresql://user.project_ref:password@host:6543/postgres"
                value={connectionString}
                onChange={(event) => setConnectionString(event.target.value)}
                className="mt-2 w-full rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-900 shadow-sm focus:border-slate-400 focus:outline-none"
              />
            </label>
            <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700">
              <p className="font-semibold text-slate-800">Where to find it</p>
              <p className="mt-1">
                Supabase Dashboard → your project → Connect →
                Connection string (use Transaction Pooler connection string).
              </p>
              <p className="mt-3 font-semibold text-slate-800">Precautions</p>
              <div className="relative mt-1 flex items-center gap-2">
                <p>
                  Use a least-privileged database user (read-only if possible)
                </p>
                <button
                  type="button"
                  onClick={() => setIsInfoOpen((prev) => !prev)}
                  className="inline-flex h-5 w-5 items-center justify-center rounded-full border border-slate-300 text-xs font-semibold text-slate-600 transition hover:bg-slate-100"
                  aria-label="Show SQL script for read-only user"
                >
                  i
                </button>
                {isInfoOpen && (
                  <div className="absolute left-0 top-full z-10 mt-2 w-full max-w-sm rounded-xl border border-slate-200 bg-white p-4 text-left text-xs text-slate-700 shadow-md max-h-[60vh] overflow-auto md:left-full md:top-1/2 md:mt-0 md:ml-3 md:w-80 md:-translate-y-1/2">
                    <p className="text-sm font-semibold text-slate-800">
                      SQL Script (Read-Only User)
                    </p>
                    <pre className="mt-2 whitespace-pre-wrap font-mono text-[11px] leading-relaxed text-slate-700">
                        {`-- 1) Create a login role
                        create role app_readonly login password 'REPLACE_WITH_STRONG_PASSWORD';

                        -- 2) Allow connection to your database (usually "postgres")
                        grant connect on database postgres to app_readonly;

                        -- 3) Allow usage on schema (typically "public")
                        grant usage on schema public to app_readonly;

                        -- 4) Grant read access to existing tables/views
                        grant select on all tables in schema public to app_readonly;

                        -- 5) Ensure future tables are read-only by default
                        alter default privileges in schema public
                        grant select on tables to app_readonly;`}
                    </pre>
                  </div>
                )}
              </div>
              <p className="mt-2">
                If you have network restrictions enabled, allow the backend IP
                so the app can reach your database.
              </p>
              <p className="mt-2">
                Rotate credentials if you revoke access.
              </p>
            </div>
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
                disabled={!connectionString.trim() || isConnecting}
                className="rounded-md bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-700 disabled:cursor-not-allowed disabled:bg-slate-400"
              >
                {isConnecting ? "Connecting..." : "Connect"}
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
