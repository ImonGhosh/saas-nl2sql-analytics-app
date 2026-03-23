"use client";

import { useAuth } from "@clerk/nextjs";
import { BarChart3, Loader2 } from "lucide-react";
import dynamic from "next/dynamic";
import {
  useEffect,
  useState,
  type Dispatch,
  type FormEvent,
  type SetStateAction,
} from "react";
import type { VisualizationSpec } from "vega-embed";
import type { LibraryChart } from "./ChartLibrary";

const VegaLite = dynamic(
  () => import("react-vega").then((mod) => mod.VegaLite),
  { ssr: false }
);

type AnalyticsAgentProps = {
  onLogout: () => void;
  libraryCharts: LibraryChart[];
  setLibraryCharts: Dispatch<SetStateAction<LibraryChart[]>>;
  selectedChart?: LibraryChart | null;
};

const backendUrl =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://127.0.0.1:8000";
const clerkJwtTemplate =
  process.env.NEXT_PUBLIC_CLERK_JWT_TEMPLATE ?? "backend";

type ChartPayload = {
  spec: VisualizationSpec;
  data: Record<string, unknown>[];
  summary?: string;
  sql?: string;
};

export default function AnalyticsAgent({
  onLogout,
  libraryCharts,
  setLibraryCharts,
  selectedChart,
}: AnalyticsAgentProps) {
  const { getToken } = useAuth();
  const [chartInput, setChartInput] = useState("");
  const [lastRequest, setLastRequest] = useState<string | null>(null);
  const [chartPayload, setChartPayload] = useState<ChartPayload | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [isSuggestionOpen, setIsSuggestionOpen] = useState(false);

  const buildChartPayload = (payload: {
    summary?: string;
    chart_spec?: VisualizationSpec;
    data?: Record<string, unknown>[];
    sql?: string;
  } | null): ChartPayload | null => {
    if (!payload) return null;
    if (!payload.chart_spec || typeof payload.chart_spec !== "object") {
      return null;
    }
    const data = Array.isArray(payload.data) ? payload.data : [];
    return {
      spec: payload.chart_spec,
      data,
      summary: typeof payload.summary === "string" ? payload.summary : undefined,
      sql: typeof payload.sql === "string" ? payload.sql : undefined,
    };
  };

  useEffect(() => {
    let isActive = true;

    const loadSuggestions = async () => {
      try {
        const token = await getToken({ template: clerkJwtTemplate });
        if (!token) return;

        const response = await fetch(`${backendUrl}/charts/suggestions`, {
          headers: {
            Authorization: `Bearer ${token}`,
          },
        });

        if (response.status === 404) return;
        if (!response.ok) {
          throw new Error(`Request failed (${response.status}).`);
        }

        const payload = (await response.json()) as { suggestions?: string[] };
        const items = Array.isArray(payload.suggestions) ? payload.suggestions : [];
        if (isActive) setSuggestions(items);
      } catch (error) {
        if (!isActive) return;
        const message =
          error instanceof Error ? error.message : "Failed to load suggestions.";
        setErrorMessage(message);
      }
    };

    void loadSuggestions();

    return () => {
      isActive = false;
    };
  }, [getToken]);

  useEffect(() => {
    if (!selectedChart) return;
    setChartPayload({
      spec: selectedChart.spec,
      data: selectedChart.data,
      summary: selectedChart.summary,
      sql: selectedChart.sql,
    });
  }, [selectedChart]);

  const handleCreate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (isCreating) return;
    const trimmed = chartInput.trim();
    if (!trimmed) return;

    setIsCreating(true);
    setErrorMessage(null);
    setIsSuggestionOpen(false);
    setLastRequest(trimmed);
    setChartPayload(null);

    try {
      const token = await getToken({ template: clerkJwtTemplate });
      if (!token) {
        throw new Error("Authentication required.");
      }

      const response = await fetch(`${backendUrl}/charts/query`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ question: trimmed }),
      });

      const payload = (await response.json()) as
        | {
            summary?: string;
            chart_spec?: VisualizationSpec;
            data?: Record<string, unknown>[];
            sql?: string;
            detail?: string;
          }
        | null;

      if (!response.ok) {
        const detail = payload?.detail || `Request failed (${response.status}).`;
        throw new Error(detail);
      }

      const parsed = buildChartPayload(payload);
      if (!parsed) {
        throw new Error("Chart spec missing from response.");
      }

      setChartPayload(parsed);
      setChartInput("");
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to create chart.";
      setErrorMessage(message);
    } finally {
      setIsCreating(false);
    }
  };

  const handleSaveToLibrary = async () => {
    if (!chartPayload || isSaving || libraryCharts.length >= 4) return;
    setIsSaving(true);
    setErrorMessage(null);

    try {
      const token = await getToken({ template: clerkJwtTemplate });
      if (!token) {
        throw new Error("Authentication required.");
      }

      const response = await fetch(`${backendUrl}/charts/library`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          summary: chartPayload.summary || "Saved chart",
          chart_spec: chartPayload.spec,
          data: chartPayload.data,
          sql: chartPayload.sql || "",
        }),
      });

      const payload = (await response.json()) as {
        summary?: string;
        chart_spec?: VisualizationSpec;
        data?: Record<string, unknown>[];
        sql?: string;
        saved_at?: string;
        detail?: string;
      };

      if (!response.ok) {
        const detail = payload?.detail || `Request failed (${response.status}).`;
        throw new Error(detail);
      }

      const parsed = buildChartPayload(payload);
      if (!parsed) {
        throw new Error("Library item missing chart spec.");
      }

      setLibraryCharts((prev) => [
        ...prev,
        {
          ...parsed,
          savedAt: typeof payload.saved_at === "string" ? payload.saved_at : "",
        },
      ]);
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to save chart.";
      setErrorMessage(message);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="text-xl font-semibold text-[#E5ECF5]">Analytics Agent</h2>
        <p className="mt-1 text-sm text-[#A7B6CC]">
          Describe the KPI or chart you want to generate.
        </p>
      </div>
      <form
        onSubmit={handleCreate}
        className="rounded-xl border border-[#2a3b5a] bg-[#111c2e] p-4"
      >
        <div className="flex flex-col gap-3 sm:flex-row">
          <div className="relative flex-1">
            <textarea
              value={chartInput}
              onChange={(event) => setChartInput(event.target.value)}
              onFocus={() => {
                if (suggestions.length > 0) setIsSuggestionOpen(true);
              }}
              onBlur={() => {
                window.setTimeout(() => setIsSuggestionOpen(false), 120);
              }}
              placeholder="Example: Monthly revenue by plan tier for the last 12 months"
              rows={2}
              className="min-h-[44px] w-full resize-none rounded-lg border border-[#2a3b5a] bg-[#14223a] px-4 py-2 text-sm text-[#E5ECF5] focus:border-[#3B82F6] focus:outline-none"
            />
            {isSuggestionOpen && suggestions.length > 0 && (
              <div className="absolute left-0 right-0 top-full z-10 mt-2 max-h-56 overflow-auto rounded-lg border border-[#2a3b5a] bg-[#111c2e] shadow-lg">
                <div className="px-3 pb-1 pt-2 text-xs font-semibold uppercase tracking-wide text-[#93A4BD]">
                  Suggestions
                </div>
                {suggestions.map((item) => (
                  <button
                    key={item}
                    type="button"
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => {
                      setChartInput(item);
                      setIsSuggestionOpen(false);
                    }}
                    className="w-full px-3 py-2 text-left text-sm text-[#C7D2E6] hover:bg-[#1b2f4b]"
                  >
                    {item}
                  </button>
                ))}
              </div>
            )}
          </div>
          <button
            type="submit"
            disabled={!chartInput.trim() || isCreating}
            className="h-[44px] rounded-lg bg-gradient-to-r from-[#3B82F6] to-[#2563EB] px-6 text-sm font-semibold text-white transition hover:from-[#2563EB] hover:to-[#1D4ED8] disabled:cursor-not-allowed disabled:bg-[#384b77]"
          >
            {isCreating ? (
              <span className="inline-flex items-center gap-2">
                <Loader2 className="h-4 w-4 animate-spin" />
                Creating
              </span>
            ) : (
              "Create"
            )}
          </button>
        </div>
      </form>

      <div className="min-h-[360px] rounded-xl border border-[#2a3b5a] bg-[#14223a] shadow-sm">
        {chartPayload ? (
          <div className="flex h-full flex-col gap-4 p-6">
            {chartPayload.summary && (
              <p className="text-sm text-[#C7D2E6]">{chartPayload.summary}</p>
            )}
            <div className="min-h-[320px] flex-1 w-full">
              <VegaLite
                spec={{
                  ...chartPayload.spec,
                  width: "container",
                  height: 360,
                  autosize: { type: "fit", contains: "padding" },
                }}
                data={{ values: chartPayload.data }}
                className="w-full"
                style={{ width: "100%" }}
              />
            </div>
            {chartPayload.sql && (
              <details className="rounded-md border border-[#2a3b5a] bg-[#111c2e] px-3 py-2 text-xs text-[#A7B6CC]">
                <summary className="cursor-pointer font-semibold text-[#A7B6CC]">
                  View SQL
                </summary>
                <pre className="mt-2 whitespace-pre-wrap text-[11px] text-[#A7B6CC]">
                  {chartPayload.sql}
                </pre>
              </details>
            )}
            <div className="flex items-center justify-end">
              <button
                type="button"
                onClick={handleSaveToLibrary}
                disabled={isSaving || libraryCharts.length >= 4}
                className="rounded-md bg-gradient-to-r from-[#3B82F6] to-[#2563EB] px-4 py-2 text-xs font-semibold text-white shadow-[0_8px_18px_-10px_rgba(59,130,246,0.9)] transition hover:from-[#2563EB] hover:to-[#1D4ED8] disabled:cursor-not-allowed disabled:bg-[#435884] disabled:shadow-none"
              >
                {isSaving ? "Saving..." : "Add to Library"}
              </button>
            </div>
          </div>
        ) : (
          <div className="flex h-full flex-col items-center justify-center gap-3 p-8 text-center text-[#93A4BD]">
            <BarChart3 className="h-10 w-10 text-[#A7B6CC]" />
            <p className="text-sm font-semibold">No chart yet</p>
            <p className="max-w-sm text-sm text-[#93A4BD]">
              Add a chart request above and click Create to render the analytics chart
              here.
            </p>
            {errorMessage && (
              <p className="max-w-sm text-sm font-semibold text-red-600">
                {errorMessage}
              </p>
            )}
            {lastRequest && (
              <p className="text-xs text-[#93A4BD]">
                Latest request: <span className="font-medium">{lastRequest}</span>
              </p>
            )}
          </div>
        )}
      </div>

      <button
        type="button"
        onClick={onLogout}
        className="w-fit rounded-md border border-[#2a3b5a] bg-[#14223a] px-6 py-3 text-sm font-semibold text-[#C7D2E6] transition hover:bg-[#1b2f4b]"
      >
        Logout
      </button>
    </div>
  );
}
