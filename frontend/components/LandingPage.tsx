"use client";

import {
  SignInButton,
  SignedIn,
  SignedOut,
  UserButton,
  useAuth,
} from "@clerk/clerk-react";
import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import type { VisualizationSpec } from "vega-embed";
import ChartLibrary, { type LibraryChart } from "./ChartLibrary";
import ConversationsBar, {
  type ConversationSummary,
} from "./ConversationsBar";
import SqlChatbot from "./SqlChatbot";
import AnalyticsAgent from "./AnalyticsAgent";
import { BACKEND_URL } from "../lib/backend";

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
  const [metadataStatus, setMetadataStatus] = useState("missing");
  const [metadataErrorMessage, setMetadataErrorMessage] = useState("");
  const [libraryCharts, setLibraryCharts] = useState<LibraryChart[]>([]);
  const [selectedChart, setSelectedChart] = useState<LibraryChart | null>(null);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [activeConversation, setActiveConversation] = useState<{
    sessionId: string;
    messages: Array<{
      role: "user" | "assistant";
      content: string;
      timestamp?: string;
      sql?: string;
    }>;
  } | null>(null);

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
    if (!status) return;
    const url = new URL(window.location.href);
    url.searchParams.delete("mcp");
    window.history.replaceState({}, "", url.toString());
  }, [searchParams]);

  useEffect(() => {
    let isActive = true;

    const fetchStatus = async () => {
      if (!isLoaded) {
        if (isActive) {
          setIsConnected(false);
          setIsStatusLoading(true);
          setMetadataStatus("missing");
          setMetadataErrorMessage("");
        }
        return;
      }

      if (!isSignedIn) {
        if (isActive) {
          setIsConnected(false);
          setIsStatusLoading(false);
          setMetadataStatus("missing");
          setMetadataErrorMessage("");
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

        const response = await fetch(`${BACKEND_URL}/mcp/status`, {
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
    let intervalId: ReturnType<typeof setInterval> | null = null;

    const fetchMetadataStatus = async () => {
      if (!isLoaded || !isSignedIn || !isConnected) {
        if (isActive) {
          setMetadataStatus("missing");
          setMetadataErrorMessage("");
        }
        return;
      }

      try {
        const token = await getToken({ template: clerkJwtTemplate });
        if (!token) {
          if (isActive) {
            setMetadataStatus("missing");
            setMetadataErrorMessage("");
          }
          return;
        }

        const response = await fetch(`${BACKEND_URL}/mcp/metadata/status`, {
          headers: {
            Authorization: `Bearer ${token}`,
          },
        });

        if (!response.ok) {
          if (isActive) {
            setMetadataStatus("missing");
            setMetadataErrorMessage("");
          }
          return;
        }

        const payload = (await response.json()) as {
          status?: string;
          error_message?: string | null;
        };
        if (isActive) {
          setMetadataStatus(payload.status ?? "missing");
          setMetadataErrorMessage(payload.error_message ?? "");
        }
      } catch {
        if (isActive) {
          setMetadataStatus("missing");
          setMetadataErrorMessage("");
        }
      }
    };

    void fetchMetadataStatus();

    if (isLoaded && isSignedIn && isConnected) {
      intervalId = setInterval(fetchMetadataStatus, 4000);
    }

    return () => {
      isActive = false;
      if (intervalId) clearInterval(intervalId);
    };
  }, [getToken, isConnected, isSignedIn, isLoaded]);

  useEffect(() => {
    let isActive = true;

    const loadLibrary = async () => {
      if (
        !isConnected ||
        metadataStatus !== "ready" ||
        activeTab !== "analytics" ||
        !isSignedIn
      ) {
        return;
      }
      try {
        const token = await getToken({ template: clerkJwtTemplate });
        if (!token) return;

        const response = await fetch(`${BACKEND_URL}/charts/library`, {
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
  }, [getToken, isConnected, metadataStatus, activeTab, isSignedIn]);

  useEffect(() => {
    let isActive = true;

    const loadConversations = async () => {
      if (
        !isConnected ||
        metadataStatus !== "ready" ||
        activeTab !== "sql" ||
        !isSignedIn
      ) {
        if (isActive) {
          setConversations([]);
          setActiveConversation(null);
        }
        return;
      }
      try {
        const token = await getToken({ template: clerkJwtTemplate });
        if (!token) return;

        const response = await fetch(`${BACKEND_URL}/sql/conversations`, {
          headers: {
            Authorization: `Bearer ${token}`,
          },
        });

        if (!response.ok) {
          throw new Error(`Request failed (${response.status}).`);
        }

        const payload = (await response.json()) as {
          conversations?: Array<{
            session_id?: string;
            title?: string;
            message_count?: number;
            updated_at?: string;
          }>;
        };

        const items = Array.isArray(payload.conversations)
          ? payload.conversations
          : [];
        const parsed: ConversationSummary[] = items
          .map((item) => {
            if (!item.session_id || !item.title || !item.updated_at) {
              return null;
            }
            return {
              sessionId: item.session_id,
              title: item.title,
              messageCount: item.message_count ?? 0,
              updatedAt: item.updated_at,
            };
          })
          .filter((item): item is ConversationSummary => item !== null);

        if (isActive) setConversations(parsed);
      } catch {
        if (isActive) setConversations([]);
      }
    };

    void loadConversations();

    return () => {
      isActive = false;
    };
  }, [getToken, isConnected, metadataStatus, activeTab, isSignedIn]);

  const handleDisconnect = async () => {
    try {
      const token = await getToken({ template: clerkJwtTemplate });
      if (!token) {
        return;
      }

      await fetch(`${BACKEND_URL}/mcp/disconnect`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });
    } finally {
      setIsConnected(false);
      setMetadataStatus("missing");
      setMetadataErrorMessage("");
      setLibraryCharts([]);
      setSelectedChart(null);
      setConversations([]);
      setActiveConversation(null);
    }
  };

  const handleSelectChart = (chart: LibraryChart) => {
    setSelectedChart(chart);
  };

  const handleDeleteConversation = async (
    conversation: ConversationSummary
  ) => {
    try {
      const token = await getToken({ template: clerkJwtTemplate });
      if (!token) return;

      const response = await fetch(
        `${BACKEND_URL}/sql/conversations/${encodeURIComponent(
          conversation.sessionId
        )}`,
        {
          method: "DELETE",
          headers: {
            Authorization: `Bearer ${token}`,
          },
        }
      );

      if (!response.ok) {
        throw new Error(`Request failed (${response.status}).`);
      }
    } catch {
      return;
    } finally {
      setConversations((prev) =>
        prev.filter((item) => item.sessionId !== conversation.sessionId)
      );
      if (activeConversation?.sessionId === conversation.sessionId) {
        setActiveConversation(null);
      }
    }
  };

  const handleDeleteChart = async (chart: LibraryChart) => {
    try {
      const token = await getToken({ template: clerkJwtTemplate });
      if (!token) return;

      const response = await fetch(
        `${BACKEND_URL}/charts/library/${encodeURIComponent(chart.savedAt)}`,
        {
          method: "DELETE",
          headers: {
            Authorization: `Bearer ${token}`,
          },
        }
      );

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

      setLibraryCharts(parsed);
      if (selectedChart?.savedAt === chart.savedAt) {
        setSelectedChart(null);
      }
    } catch {
      if (selectedChart?.savedAt === chart.savedAt) {
        setSelectedChart(null);
      }
    }
  };

  const refreshConversations = async () => {
    if (
      !isConnected ||
      metadataStatus !== "ready" ||
      activeTab !== "sql" ||
      !isSignedIn
    )
      return;
    try {
      const token = await getToken({ template: clerkJwtTemplate });
      if (!token) return;

      const response = await fetch(`${BACKEND_URL}/sql/conversations`, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      if (!response.ok) {
        throw new Error(`Request failed (${response.status}).`);
      }

      const payload = (await response.json()) as {
        conversations?: Array<{
          session_id?: string;
          title?: string;
          message_count?: number;
          updated_at?: string;
        }>;
      };

      const items = Array.isArray(payload.conversations)
        ? payload.conversations
        : [];
      const parsed: ConversationSummary[] = items
        .map((item) => {
          if (!item.session_id || !item.title || !item.updated_at) {
            return null;
          }
          return {
            sessionId: item.session_id,
            title: item.title,
            messageCount: item.message_count ?? 0,
            updatedAt: item.updated_at,
          };
        })
        .filter((item): item is ConversationSummary => item !== null);

      setConversations(parsed);
    } catch {
      setConversations([]);
    }
  };

  const handleMetadataRetry = async () => {
    if (metadataStatus !== "error") return;
    setMetadataStatus("queued");
    setMetadataErrorMessage("");

    try {
      const token = await getToken({ template: clerkJwtTemplate });
      if (!token) {
        setMetadataStatus("error");
        setMetadataErrorMessage("Authentication required.");
        return;
      }

      const response = await fetch(`${BACKEND_URL}/mcp/metadata/retry`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      const text = await response.text();
      if (!response.ok) {
        throw new Error(text || `Request failed (${response.status})`);
      }
    } catch (error) {
      setMetadataStatus("error");
      setMetadataErrorMessage(
        error instanceof Error ? error.message : "Retry failed."
      );
    }
  };

  const handleSelectConversation = async (
    conversation: ConversationSummary
  ) => {
    try {
      const token = await getToken({ template: clerkJwtTemplate });
      if (!token) return;

      const response = await fetch(
        `${BACKEND_URL}/sql/conversations/${encodeURIComponent(
          conversation.sessionId
        )}`,
        {
          headers: {
            Authorization: `Bearer ${token}`,
          },
        }
      );

      if (!response.ok) {
        throw new Error(`Request failed (${response.status}).`);
      }

      const payload = (await response.json()) as {
        session_id?: string;
        messages?: Array<{
          role?: "user" | "assistant";
          content?: string;
          timestamp?: string;
          sql?: string;
        }>;
      };

      const sessionId = payload.session_id ?? conversation.sessionId;
      const messages = Array.isArray(payload.messages)
        ? payload.messages.map(
            (message): {
              role: "user" | "assistant";
              content: string;
              timestamp?: string;
              sql?: string;
            } | null => {
              if (!message.role || !message.content) return null;
              return {
                role: message.role,
                content: message.content,
                ...(message.timestamp != null ? { timestamp: message.timestamp } : {}),
                ...(message.sql != null ? { sql: message.sql } : {}),
              };
            }
          )
        : [];
      const safeMessages = messages.filter(
        (message): message is {
          role: "user" | "assistant";
          content: string;
          timestamp?: string;
          sql?: string;
        } => message !== null
      );

      setActiveConversation({ sessionId, messages: safeMessages });
    } catch {
      setActiveConversation(null);
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
      const response = await fetch(`${BACKEND_URL}/mcp/auth/start`, {
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
    <main className="min-h-screen bg-[radial-gradient(circle_at_top_left,_#253454_0%,_#101a2b_45%,_#0c1422_100%)] text-[#E5ECF5]">
      <nav className="grid w-full grid-cols-3 items-center border-b border-[#2a3b5a] bg-gradient-to-r from-[#16263f]/95 via-[#172944]/95 to-[#14223a]/95 px-6 py-4 backdrop-blur shadow-[0_12px_30px_-20px_rgba(37,99,235,0.5)]">
        <div className="hidden sm:block" />
        <div className="text-center text-sm font-semibold tracking-[0.18em] text-[#c7d2e6]">
          Supa-Connect
        </div>
        <div className="flex items-center justify-end">
          <SignedOut>
            <SignInButton mode="modal">
              <button className="rounded-md bg-gradient-to-r from-[#3B82F6] to-[#2563EB] px-4 py-2 text-sm font-semibold text-white transition hover:from-[#2563EB] hover:to-[#1D4ED8]">
                Log in
              </button>
            </SignInButton>
          </SignedOut>
          <SignedIn>
            <UserButton />
          </SignedIn>
        </div>
      </nav>

      <SignedOut>
        <section className="flex min-h-[calc(100vh-73px)] flex-col items-center justify-center px-6 text-center">
          <h1 className="text-balance text-5xl font-semibold tracking-tight text-[#E5ECF5] md:text-7xl">
            Supa-Connect :<br /> AI Powered SQL &amp; Visual Analytics
          </h1>
          <SignInButton mode="modal">
            <button className="mt-8 rounded-md bg-gradient-to-r from-[#3B82F6] to-[#2563EB] px-8 py-3 text-base font-semibold text-white transition hover:from-[#2563EB] hover:to-[#1D4ED8]">
              Try it out for free
            </button>
          </SignInButton>
          <p
            className="mt-6 max-w-2xl text-sm italic text-[#A7B6CC]"
            style={{
              fontFamily:
                '"Caveat", "Patrick Hand", "Bradley Hand", "Comic Sans MS", cursive',
            }}
          >
            Connect to your supabase project and chat with it to extract data-driven insights.
          </p>
          <p className="mt-3 text-xs font-medium tracking-[0.18em] text-[#7c8eab]">
            © {new Date().getFullYear()} Supa-Connect. All rights reserved.
          </p>
        </section>
      </SignedOut>
      <SignedOut>
        <div className="fixed bottom-2 right-4 z-20 sm:bottom-6 sm:right-8">
          <a
            href="https://www.flaticon.com/free-icons/analysis"
            title="analysis icons"
            target="_blank"
            rel="noreferrer"
            className="block"
            aria-label="Analysis icons created by Freepik - Flaticon"
          >
            <img
              src="/analysis-icon.svg"
              alt="Analysis icon"
              className="h-32 w-32 opacity-90 transition hover:opacity-100 sm:h-40 sm:w-40"
              loading="lazy"
            />
          </a>
        </div>
      </SignedOut>
      <SignedOut>
        <div className="fixed bottom-2 left-4 z-20 sm:bottom-6 sm:left-8">
          <a
            href="https://www.flaticon.com/free-icons/database"
            title="database icons"
            target="_blank"
            rel="noreferrer"
            className="block"
            aria-label="Database icons created by Freepik - Flaticon"
          >
            <img
              src="/database-icon.svg"
              alt="Database icon"
              className="h-32 w-32 opacity-90 transition hover:opacity-100 sm:h-40 sm:w-40"
              loading="lazy"
            />
          </a>
        </div>
      </SignedOut>

      <SignedIn>
        <section className="flex min-h-[calc(100vh-73px)] w-full items-start justify-center px-6 py-12">
          <div
            className={`w-full ${
              isConnected && (activeTab === "analytics" || activeTab === "sql")
                ? "max-w-6xl"
                : "max-w-4xl"
            }`}
          >
            <div className="flex items-center gap-3 rounded-2xl border border-[#2a3b5a] bg-gradient-to-r from-[#16263f] via-[#192d49] to-[#16263f] p-2 shadow-[0_18px_36px_-26px_rgba(59,130,246,0.7)] ring-1 ring-[#2f4163]">
              <button
                type="button"
                onClick={() => setActiveTab("sql")}
                className={`flex-1 rounded-lg px-4 py-2 text-sm font-semibold transition ${
                  activeTab === "sql"
                    ? "bg-[linear-gradient(135deg,_#3B82F6,_#2563EB)] text-white shadow-[0_12px_22px_-12px_rgba(59,130,246,0.9)]"
                    : "text-[#A7B6CC] hover:bg-[#1b2f4b]"
                }`}
              >
                SQL Agent
              </button>
              <button
                type="button"
                onClick={() => setActiveTab("analytics")}
                className={`flex-1 rounded-lg px-4 py-2 text-sm font-semibold transition ${
                  activeTab === "analytics"
                    ? "bg-[linear-gradient(135deg,_#3B82F6,_#2563EB)] text-white shadow-[0_12px_22px_-12px_rgba(59,130,246,0.9)]"
                    : "text-[#A7B6CC] hover:bg-[#1b2f4b]"
                }`}
              >
                Analytics Agent
              </button>
            </div>

            {isStatusLoading ? (
              <div className="mt-10 rounded-2xl border border-dashed border-[#2a3b5a] bg-[#14223a]/85 px-6 py-16 text-center">
                <div className="flex flex-col items-center justify-center gap-3 text-[#A7B6CC]">
                  <span
                    className="h-6 w-6 animate-spin rounded-full border-2 border-[#2a3b5a] border-t-[#7aa2f7]"
                    aria-hidden="true"
                  />
                  <p className="text-sm font-semibold">Loading your data...</p>
                </div>
              </div>
            ) : isConnected ? (
              metadataStatus !== "ready" ? (
                <div className="mt-10 rounded-2xl border border-dashed border-[#2a3b5a] bg-[#14223a]/85 px-6 py-16 text-center">
                  <div className="flex flex-col items-center justify-center gap-3 text-[#A7B6CC]">
                    <span
                      className="h-6 w-6 animate-spin rounded-full border-2 border-[#2a3b5a] border-t-[#7aa2f7]"
                      aria-hidden="true"
                    />
                    <p className="text-sm font-semibold">
                      Extracting metadata...
                    </p>
                    {metadataStatus === "error" ? (
                      <>
                        <p className="text-sm font-semibold text-red-500">
                          {metadataErrorMessage ||
                            "Metadata extraction failed. Retry to continue."}
                        </p>
                        <button
                          type="button"
                          onClick={handleMetadataRetry}
                          className="rounded-md bg-gradient-to-r from-[#3B82F6] to-[#2563EB] px-4 py-2 text-sm font-semibold text-white transition hover:from-[#2563EB] hover:to-[#1D4ED8]"
                        >
                          Retry
                        </button>
                      </>
                    ) : null}
                  </div>
                </div>
              ) : activeTab === "sql" ? (
                <div className="mt-10 flex flex-col gap-6 lg:flex-row lg:items-start">
                  <div className="w-full max-w-4xl rounded-2xl border border-[#2a3b5a] bg-[#14223a]/90 px-6 py-8 text-left shadow-[0_22px_44px_-28px_rgba(8,12,20,0.65)]">
                    <SqlChatbot
                      onLogout={handleDisconnect}
                      activeConversation={activeConversation}
                      onConversationUpdated={refreshConversations}
                      onNewConversation={() => setActiveConversation(null)}
                    />
                  </div>
                  <ConversationsBar
                    conversations={conversations}
                    onSelect={handleSelectConversation}
                    onDelete={handleDeleteConversation}
                  />
                </div>
              ) : (
                <div className="mt-10 flex flex-col gap-6 lg:flex-row lg:items-start">
                  <div className="w-full max-w-4xl rounded-2xl border border-[#2a3b5a] bg-[#14223a]/90 px-6 py-8 text-left shadow-[0_22px_44px_-28px_rgba(8,12,20,0.65)]">
                    <AnalyticsAgent
                      onLogout={handleDisconnect}
                      libraryCharts={libraryCharts}
                      setLibraryCharts={setLibraryCharts}
                      selectedChart={selectedChart}
                    />
                  </div>
                  <ChartLibrary
                    charts={libraryCharts}
                    maxCharts={4}
                    onSelect={handleSelectChart}
                    onDelete={handleDeleteChart}
                  />
                </div>
              )
            ) : (
              <div className="mt-10 rounded-2xl border border-dashed border-[#2a3b5a] bg-[#14223a]/85 px-6 py-16 text-center">
                <button
                  type="button"
                  onClick={() => setIsModalOpen(true)}
                  className="inline-flex h-20 w-20 items-center justify-center rounded-full border-2 border-[#2a3b5a] bg-[#14223a] text-5xl font-semibold text-[#7aa2f7] transition hover:border-[#3a5177] hover:text-[#3B82F6]"
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
          className="fixed inset-0 z-50 flex items-center justify-center bg-[#05070c]/70 px-6"
          role="dialog"
          aria-modal="true">
          <div className="relative w-full max-w-lg rounded-2xl border border-[#2a3b5a] bg-gradient-to-br from-[#16263f] via-[#172944] to-[#14223a] p-6 text-left shadow-2xl">
            <h2 className="text-xl font-semibold text-[#E5ECF5]">
              Connect to Supabase
            </h2>
            <p className="mt-2 text-sm text-[#A7B6CC]">
              Enter your project ref and authorize access.
            </p>
            <label className="mt-4 block text-sm font-semibold text-[#C7D2E6]">
              Project ref
              <input
                type="text"
                placeholder="your-project-ref"
                value={projectRef}
                onChange={(event) => setProjectRef(event.target.value)}
                className="mt-2 w-full rounded-md border border-[#344b74] bg-[#111c2e] px-3 py-2 text-sm text-[#E5ECF5] shadow-sm focus:border-[#3B82F6] focus:outline-none"
              />
            </label>
            <p className="mt-2 text-xs text-[#93A4BD]">
              Find your project ref in Supabase Dashboard -&gt; Settings -&gt; General.
            </p>

            {connectError && (
              <p className="mt-4 text-sm font-semibold text-red-600">
                {connectError}
              </p>
            )}
            {connectStatus && (
              <p className="mt-4 text-sm font-semibold text-emerald-300">
                {connectStatus}
              </p>
            )}

            <div className="mt-6 flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={handleConnect}
                disabled={!projectRef.trim() || isConnecting}
                className="rounded-md bg-gradient-to-r from-[#3B82F6] to-[#2563EB] px-4 py-2 text-sm font-semibold text-white transition hover:from-[#2563EB] hover:to-[#1D4ED8] disabled:cursor-not-allowed disabled:bg-[#435884]"
              >
                {isConnecting ? "Authorizing..." : "Authorize with Supabase"}
              </button>
              <button
                type="button"
                onClick={closeModal}
                className="rounded-md border border-[#344b74] px-4 py-2 text-sm font-semibold text-[#C7D2E6] transition hover:bg-[#1b2f4b]"
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
