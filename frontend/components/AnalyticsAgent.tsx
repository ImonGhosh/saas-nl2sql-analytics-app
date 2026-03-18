"use client";

import { BarChart3 } from "lucide-react";
import dynamic from "next/dynamic";
import { useState, type FormEvent } from "react";
import type { VisualizationSpec } from "vega-embed";

const VegaLite = dynamic(
  () => import("react-vega").then((mod) => mod.VegaLite),
  { ssr: false }
);

type AnalyticsAgentProps = {
  onLogout: () => void;
};

type ChartPayload = {
  spec: VisualizationSpec;
  data: Record<string, unknown>[];
  summary?: string;
  sql?: string;
};

export default function AnalyticsAgent({ onLogout }: AnalyticsAgentProps) {
  const [chartInput, setChartInput] = useState("");
  const [lastRequest, setLastRequest] = useState<string | null>(null);
  const [chartPayload, setChartPayload] = useState<ChartPayload | null>(null);

  const handleCreate = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = chartInput.trim();
    if (!trimmed) return;

    setLastRequest(trimmed);
    setChartPayload(null);
    setChartInput("");
  };

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="text-xl font-semibold text-slate-900">Analytics Agent</h2>
        <p className="mt-1 text-sm text-slate-600">
          Describe the KPI or chart you want to generate.
        </p>
      </div>

      <form
        onSubmit={handleCreate}
        className="rounded-xl border border-slate-200 bg-slate-50 p-4">
        <div className="flex flex-col gap-3 sm:flex-row">
          <textarea
            value={chartInput}
            onChange={(event) => setChartInput(event.target.value)}
            placeholder="Example: Monthly revenue by plan tier for the last 12 months"
            rows={2}
            className="min-h-[44px] flex-1 resize-none rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm text-slate-900 focus:border-slate-400 focus:outline-none"
          />
          <button
            type="submit"
            disabled={!chartInput.trim()}
            className="h-[44px] rounded-lg bg-slate-900 px-6 text-sm font-semibold text-white transition hover:bg-slate-700 disabled:cursor-not-allowed disabled:bg-slate-400"
          >
            Create
          </button>
        </div>
      </form>

      <div className="min-h-[360px] rounded-xl border border-slate-200 bg-white shadow-sm">
        {chartPayload ? (
          <div className="flex h-full flex-col gap-4 p-6">
            {chartPayload.summary && (
              <p className="text-sm text-slate-700">{chartPayload.summary}</p>
            )}
            <VegaLite
              spec={chartPayload.spec}
              data={{ values: chartPayload.data }}
            />
            {chartPayload.sql && (
              <details className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-700">
                <summary className="cursor-pointer font-semibold text-slate-700">
                  View SQL
                </summary>
                <pre className="mt-2 whitespace-pre-wrap text-[11px] text-slate-600">
                  {chartPayload.sql}
                </pre>
              </details>
            )}
          </div>
        ) : (
          <div className="flex h-full flex-col items-center justify-center gap-3 p-8 text-center text-slate-500">
            <BarChart3 className="h-10 w-10 text-slate-400" />
            <p className="text-sm font-semibold">No chart yet</p>
            <p className="max-w-sm text-sm text-slate-500">
              Add a chart request above and click Create to render the analytics chart
              here.
            </p>
            {lastRequest && (
              <p className="text-xs text-slate-400">
                Latest request: <span className="font-medium">{lastRequest}</span>
              </p>
            )}
          </div>
        )}
      </div>

      <button
        type="button"
        onClick={onLogout}
        className="w-fit rounded-md border border-slate-300 bg-white px-6 py-3 text-sm font-semibold text-slate-700 transition hover:bg-slate-100"
      >
        Logout
      </button>
    </div>
  );
}
