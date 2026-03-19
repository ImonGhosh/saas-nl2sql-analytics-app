"use client";

import dynamic from "next/dynamic";
import type { VisualizationSpec } from "vega-embed";

const VegaLite = dynamic(
  () => import("react-vega").then((mod) => mod.VegaLite),
  { ssr: false }
);

export type LibraryChart = {
  spec: VisualizationSpec;
  data: Record<string, unknown>[];
  summary?: string;
  sql?: string;
  savedAt: string;
};

type ChartLibraryProps = {
  charts: LibraryChart[];
  maxCharts: number;
};

const buildThumbnailSpec = (spec: VisualizationSpec): VisualizationSpec => {
  const typedSpec = spec as VisualizationSpec & {
    config?: {
      axis?: Record<string, unknown>;
      legend?: Record<string, unknown>;
    };
  };
  return {
    ...typedSpec,
    title: null,
    width: 220,
    height: 120,
    autosize: { type: "fit", contains: "padding" },
    padding: { top: 4, right: 6, bottom: 4, left: 6 },
    config: {
      ...(typedSpec.config ?? {}),
      view: {
        ...(typedSpec.config?.view ?? {}),
        stroke: null,
      },
      axis: {
        ...(typedSpec.config?.axis ?? {}),
        labelFontSize: 8,
        titleFontSize: 0,
        tickSize: 0,
        grid: false,
        labelLimit: 60,
      },
      axisX: {
        ...(typedSpec.config?.axisX ?? {}),
        labelAngle: 0,
        labelFontSize: 7,
      },
      axisY: {
        ...(typedSpec.config?.axisY ?? {}),
        labelFontSize: 7,
      },
      legend: {
        ...(typedSpec.config?.legend ?? {}),
        labelFontSize: 7,
        titleFontSize: 0,
        symbolSize: 40,
        orient: "bottom",
      },
    },
  };
};

export default function ChartLibrary({ charts, maxCharts }: ChartLibraryProps) {
  return (
    <aside className="w-full rounded-xl border border-slate-200 bg-white/80 p-4 shadow-sm lg:w-64">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-700">Library</h3>
        <span className="text-xs text-slate-400">
          {charts.length}/{maxCharts}
        </span>
      </div>
      {charts.length === 0 ? (
        <div className="mt-4 rounded-lg border border-dashed border-slate-200 p-4 text-center text-xs text-slate-400">
          No saved charts yet.
        </div>
        ) : (
        <div className="mt-4 flex flex-col gap-3">
          {charts.map((chart, index) => (
            <div
              key={`${chart.savedAt}-${index}`}
              className="rounded-lg border border-slate-200 bg-white p-2 shadow-sm"
            >
              <VegaLite
                spec={buildThumbnailSpec(chart.spec)}
                data={{ values: chart.data }}
                className="w-full"
                style={{ width: "100%" }}
              />
            </div>
          ))}
        </div>
      )}
    </aside>
  );
}
