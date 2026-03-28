"use client";

import { X } from "lucide-react";
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
  onSelect?: (chart: LibraryChart) => void;
  onDelete?: (chart: LibraryChart) => void;
};

const buildThumbnailSpec = (
  spec: VisualizationSpec,
  data: Record<string, unknown>[]
): VisualizationSpec => {
  const typedSpec = spec as VisualizationSpec;
  const getEncoding = (value: unknown) => {
    if (!value || typeof value !== "object") return undefined;
    const maybe = value as { encoding?: Record<string, unknown> };
    return maybe.encoding;
  };
  const setEncoding = (value: unknown, encoding: Record<string, unknown> | undefined) => {
    if (!encoding || !value || typeof value !== "object") return value;
    if ("encoding" in (value as Record<string, unknown>)) {
      return { ...(value as Record<string, unknown>), encoding };
    }
    const withSpec = value as { spec?: Record<string, unknown> };
    if (withSpec.spec) {
      return {
        ...(value as Record<string, unknown>),
        spec: { ...withSpec.spec, encoding },
      };
    }
    return value;
  };
  const baseEncoding = getEncoding(typedSpec) ?? getEncoding((typedSpec as { spec?: unknown }).spec);
  const getFieldValue = (row: Record<string, unknown>, field: string) => {
    const parts = field.split(".");
    let current: unknown = row;
    for (const part of parts) {
      if (current && typeof current === "object" && part in current) {
        current = (current as Record<string, unknown>)[part];
      } else {
        return undefined;
      }
    }
    return current;
  };

  const isCategorical = (encoding: Record<string, unknown> | undefined) => {
    if (!encoding) return false;
    const type = String(encoding.type ?? "").toLowerCase();
    const scale = encoding.scale as Record<string, unknown> | undefined;
    const scaleType = String(scale?.type ?? "").toLowerCase();
    return ["nominal", "ordinal", "band", "point"].includes(type) ||
      ["band", "point", "ordinal"].includes(scaleType);
  };

  const computeAxisValues = (
    encoding: Record<string, unknown> | undefined
  ): unknown[] | null => {
    if (!encoding) return null;
    const field = encoding.field;
    if (typeof field !== "string" || !field) return null;

    const values = data
      .map((row) => getFieldValue(row, field))
      .filter((value) => value !== undefined && value !== null);
    if (values.length === 0) return null;

    const categorical =
      isCategorical(encoding) ||
      String(encoding.type ?? "").toLowerCase() === "temporal";

    if (categorical) {
      const unique: unknown[] = [];
      const seen = new Set<string>();
      for (const value of values) {
        const key = String(value);
        if (!seen.has(key)) {
          seen.add(key);
          unique.push(value);
        }
      }
      if (unique.length <= 4) return unique;
      return [unique[0], unique[Math.floor((unique.length - 1) / 2)], unique[unique.length - 1]];
    }

    const numeric = values
      .map((value) => {
        if (typeof value === "number") return value;
        const asNumber = Number(value);
        return Number.isFinite(asNumber) ? asNumber : null;
      })
      .filter((value): value is number => value !== null);
    if (numeric.length === 0) return null;
    const min = Math.min(...numeric);
    const max = Math.max(...numeric);
    if (!Number.isFinite(min) || !Number.isFinite(max)) return null;
    if (min === max) return [min];
    return [min, min + (max - min) / 2, max];
  };

  const axisOverride = (
    axis: Record<string, unknown> | undefined,
    values: unknown[] | null
  ) => ({
    ...(axis ?? {}),
    labelAngle: 0,
    labelFontSize: 7,
    labelLimit: 60,
    labelOverlap: "greedy",
    labelFlush: true,
    tickCount: 3,
    ...(values ? { values } : {}),
  });
  const xValues = computeAxisValues(baseEncoding?.x as Record<string, unknown> | undefined);
  const yValues = computeAxisValues(baseEncoding?.y as Record<string, unknown> | undefined);
  const encoding = baseEncoding
    ? {
        ...baseEncoding,
        x: baseEncoding.x
          ? {
              ...(baseEncoding.x as Record<string, unknown>),
              axis: axisOverride(
                (baseEncoding.x as { axis?: Record<string, unknown> }).axis,
                xValues
              ),
            }
          : baseEncoding.x,
        y: baseEncoding.y
          ? {
              ...(baseEncoding.y as Record<string, unknown>),
              axis: axisOverride(
                (baseEncoding.y as { axis?: Record<string, unknown> }).axis,
                yValues
              ),
            }
          : baseEncoding.y,
      }
    : baseEncoding;
  const withEncoding = setEncoding(typedSpec, encoding) as VisualizationSpec;
  return {
    ...(withEncoding as VisualizationSpec),
    title: undefined,
    width: "container",
    height: "container",
    autosize: { type: "fit", contains: "padding", resize: true },
    padding: { top: 4, right: 6, bottom: 4, left: 6 },
    config: {
      ...(typedSpec.config ?? {}),
      view: {
        ...((typedSpec.config as { view?: Record<string, unknown> } | undefined)?.view ??
          {}),
        stroke: null,
      },
      axis: {
        ...((typedSpec.config as { axis?: Record<string, unknown> } | undefined)?.axis ??
          {}),
        labelFontSize: 8,
        titleFontSize: 0,
        tickCount: 3,
        tickSize: 0,
        grid: false,
        labelLimit: 60,
      },
      axisX: {
        ...((typedSpec.config as { axisX?: Record<string, unknown> } | undefined)?.axisX ??
          {}),
        labelAngle: 0,
        labelFontSize: 7,
        tickCount: 3,
      },
      axisY: {
        ...((typedSpec.config as { axisY?: Record<string, unknown> } | undefined)?.axisY ??
          {}),
        labelFontSize: 7,
        tickCount: 3,
      },
      legend: {
        ...((typedSpec.config as { legend?: Record<string, unknown> } | undefined)
          ?.legend ?? {}),
        labelFontSize: 0,
        titleFontSize: 0,
        symbolSize: 0,
        orient: "none",
      },
    } as VisualizationSpec["config"],
  } as unknown as VisualizationSpec;
};

export default function ChartLibrary({
  charts,
  maxCharts,
  onSelect,
  onDelete,
}: ChartLibraryProps) {
  return (
    <aside className="w-full rounded-xl border border-[#2a3b5a] bg-[#14223a]/90 p-4 shadow-sm lg:w-64">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-[#C7D2E6]">Library</h3>
        <span className="text-xs text-[#93A4BD]">
          {charts.length}/{maxCharts}
        </span>
      </div>
      {charts.length === 0 ? (
        <div className="mt-4 rounded-lg border border-dashed border-[#2a3b5a] p-4 text-center text-xs text-[#93A4BD]">
          No saved charts yet.
        </div>
        ) : (
        <div className="mt-4 flex flex-col gap-3">
          {charts.map((chart, index) => (
            <div
              key={`${chart.savedAt}-${index}`}
              className="group relative overflow-hidden rounded-lg border border-[#2a3b5a] bg-[#111c2e] p-2 shadow-sm transition hover:border-[#3a5177]"
              role="button"
              tabIndex={0}
              onClick={() => onSelect?.(chart)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onSelect?.(chart);
                }
              }}>
              {onDelete && (
                <button
                  type="button"
                  onClick={(event) => {
                    event.stopPropagation();
                    onDelete(chart);
                  }}
                  className="absolute right-2 top-2 z-10 rounded-full border border-[#2a3b5a] bg-[#14223a]/90 p-1 text-[#93A4BD] opacity-0 shadow-sm transition hover:text-[#E5ECF5] group-hover:opacity-100"
                  aria-label="Delete chart"
                >
                  <X className="h-3 w-3" />
                </button>
              )}
              <div className="h-[140px] w-full overflow-hidden">
                <VegaLite
                  spec={buildThumbnailSpec(chart.spec, chart.data)}
                  data={{ values: chart.data }}
                  actions={false}
                  renderer="svg"
                  className="h-full w-full"
                  style={{ width: "100%", height: "100%" }}
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </aside>
  );
}
