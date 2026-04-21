import { useState, useMemo } from "react";
import { motion } from "framer-motion";
import ReactECharts from "echarts-for-react";
import {
  BarChart3,
  ChevronDown,
  ChevronUp,
  Code2,
  Database,
  FileSpreadsheet,
  Timer,
  Table2,
  AlertTriangle,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface AnalyticsPayload {
  ok: boolean;
  result: any;
  result_type: "table" | "scalar" | "error";
  chart: {
    type: "bar" | "line" | "pie";
    title: string;
    xAxis?: string[];
    series: { name: string; data: number[] }[];
  } | null;
  error: string | null;
  code: string;
  doc_id: string;
  filename: string;
  tables?: string[];
  filenames?: string[];
  tables_joined?: string[];
  validator_concern?: string | null;
}

// Map loaded table name → canonical filename for display.
// e.g. "employees" → "02_Employees.xlsx"
function matchTableToFilename(tableName: string, filenames: string[]): string | null {
  if (!filenames || filenames.length === 0) return null;
  const needle = tableName.toLowerCase().replace(/_/g, "");
  const hit = filenames.find((f) =>
    f.toLowerCase().replace(/[^a-z0-9]/g, "").includes(needle)
  );
  return hit ?? null;
}

// Extract the DataFrames ACTUALLY referenced by the generated code.
// The LLM loads all tabular docs but usually touches only 2-4.
function extractReferencedTables(code: string): string[] {
  if (!code) return [];
  const matches = Array.from(code.matchAll(/\bdf_([a-z][a-z0-9_]*)/gi));
  const uniq = new Set<string>(matches.map((m) => m[1].toLowerCase()));
  return Array.from(uniq).sort();
}

export function DataCard({
  data,
  latencyMs,
}: {
  data: AnalyticsPayload;
  latencyMs?: number;
}) {
  const [showCode, setShowCode] = useState(false);
  const [showFullTable, setShowFullTable] = useState(false);

  // Compute actual sources used: parse code for df_xxx refs, map to
  // original filenames. Falls back to data.filename when no match.
  const sourceFiles = useMemo(() => {
    const filenames = data.filenames ?? [];
    const tableRefs = extractReferencedTables(data.code);
    if (tableRefs.length > 0 && filenames.length > 0) {
      const matched = tableRefs
        .map((t) => matchTableToFilename(t, filenames))
        .filter((x): x is string => !!x);
      if (matched.length > 0) return Array.from(new Set(matched));
    }
    // Single-table or fallback: just the primary filename
    if (data.filename && !data.filename.includes(" + ")) return [data.filename];
    // Multi-table filename string — split it
    return data.filename ? data.filename.split(" + ").map((s) => s.trim()).filter(Boolean).slice(0, 6) : [];
  }, [data.code, data.filenames, data.filename]);

  if (!data.ok) {
    return (
      <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}>
        <div className="flex items-start gap-2.5 max-w-full">
          <div className="w-7 h-7 shrink-0 rounded-md bg-red-50 border border-red-200 flex items-center justify-center mt-0.5">
            <AlertTriangle className="w-3.5 h-3.5 text-red-500" strokeWidth={1.75} />
          </div>
          <div className="flex-1 min-w-0 card px-4 py-3">
            <div className="text-[11px] uppercase tracking-wider font-semibold text-red-500 mb-1">
              Analytics error
            </div>
            <div className="text-[13px] text-fg">{data.error}</div>
            {data.code && (
              <button
                onClick={() => setShowCode(!showCode)}
                className="mt-2 text-[11px] text-fg-muted hover:text-accent flex items-center gap-1"
              >
                <Code2 className="w-3 h-3" />
                {showCode ? "Hide code" : "Show generated code"}
              </button>
            )}
            {showCode && data.code && <CodeBlock code={data.code} />}
          </div>
        </div>
      </motion.div>
    );
  }

  return (
    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}>
      <div className="flex items-start gap-2.5 max-w-full">
        <div className="w-7 h-7 shrink-0 rounded-md bg-sky-50 border border-sky-200 flex items-center justify-center mt-0.5">
          <Database className="w-3.5 h-3.5 text-sky-600" strokeWidth={1.75} />
        </div>

        <div className="flex-1 min-w-0 space-y-3">
          {/* Header — just the mode badge, sources go in the bottom panel */}
          <div className="flex items-center gap-2 flex-wrap">
            <span className="inline-flex items-center gap-1 rounded-full border border-sky-200 bg-sky-50 px-2.5 py-[3px] text-[10.5px] font-semibold text-sky-700">
              <BarChart3 className="w-3 h-3" strokeWidth={2.25} />
              Data Analytics
            </span>
            {typeof latencyMs === "number" && latencyMs > 0 && (
              <span className="inline-flex items-center gap-1 text-[11px] text-fg-muted">
                <Timer className="w-3 h-3" strokeWidth={2} />
                {formatLatency(latencyMs)}
              </span>
            )}
          </div>

          {/* Scalar result */}
          {data.result_type === "scalar" && (
            <div className="card px-4 py-3">
              <div className="text-[24px] font-bold text-fg">
                {typeof data.result === "object"
                  ? JSON.stringify(data.result, null, 2)
                  : String(data.result)}
              </div>
            </div>
          )}

          {/* Table result */}
          {data.result_type === "table" && data.result && (
            <div className="card overflow-hidden">
              <div className="px-3 py-2 border-b border-border flex items-center justify-between">
                <div className="flex items-center gap-1.5 text-[11px] text-fg-muted">
                  <Table2 className="w-3 h-3" strokeWidth={2} />
                  {data.result.total_rows} rows
                  {data.result.truncated && " (showing first 50)"}
                  {" · "}
                  {data.result.columns?.length || 0} columns
                </div>
              </div>
              <div className="overflow-x-auto max-h-[320px] overflow-y-auto">
                <table className="w-full text-[12px]">
                  <thead className="sticky top-0">
                    <tr className="bg-bg-elevated border-b border-border">
                      {(data.result.columns || []).map((col: string) => (
                        <th
                          key={col}
                          className="px-3 py-2 text-left font-semibold text-fg-muted whitespace-nowrap"
                        >
                          {col}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {(showFullTable
                      ? data.result.rows
                      : (data.result.rows || []).slice(0, 10)
                    ).map((row: Record<string, any>, i: number) => (
                      <tr
                        key={i}
                        className={cn(
                          "border-b border-border/50 hover:bg-accent-soft/30 transition-colors",
                          i % 2 === 0 ? "bg-surface" : "bg-bg"
                        )}
                      >
                        {(data.result.columns || []).map((col: string) => (
                          <td key={col} className="px-3 py-1.5 text-fg whitespace-nowrap">
                            {formatCell(row[col])}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {(data.result.rows || []).length > 10 && (
                <button
                  onClick={() => setShowFullTable(!showFullTable)}
                  className="w-full px-3 py-1.5 text-[11px] text-accent hover:bg-accent-soft/30 flex items-center justify-center gap-1 border-t border-border transition-colors"
                >
                  {showFullTable ? (
                    <>
                      <ChevronUp className="w-3 h-3" /> Show less
                    </>
                  ) : (
                    <>
                      <ChevronDown className="w-3 h-3" /> Show all {data.result.rows.length} rows
                    </>
                  )}
                </button>
              )}
            </div>
          )}

          {/* ECharts chart */}
          {data.chart && <ChartRenderer chart={data.chart} />}

          {/* Validator concern — second-LLM sanity check flagged something */}
          {data.validator_concern && (
            <div className="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2">
              <AlertTriangle className="w-3.5 h-3.5 text-amber-600 mt-[1px] shrink-0" strokeWidth={2} />
              <div className="text-[11.5px] leading-relaxed text-amber-900">
                <span className="font-semibold">Sanity check: </span>
                {data.validator_concern}
              </div>
            </div>
          )}

          {/* Sources + latency panel — replaces the raw code dump */}
          <div className="card px-3 py-2.5">
            <div className="flex items-center justify-between gap-3 flex-wrap">
              <div className="flex items-center gap-1.5 min-w-0 flex-1">
                <FileSpreadsheet className="w-3 h-3 text-fg-muted shrink-0" strokeWidth={2} />
                <span className="text-[11px] text-fg-muted shrink-0">Sources:</span>
                <div className="flex items-center gap-1.5 flex-wrap">
                  {sourceFiles.length > 0 ? (
                    sourceFiles.map((fn) => (
                      <span
                        key={fn}
                        className="inline-flex items-center rounded-md border border-border bg-bg-elevated px-2 py-[2px] text-[10.5px] font-medium text-fg"
                        title={fn}
                      >
                        {prettifyFilename(fn)}
                      </span>
                    ))
                  ) : (
                    <span className="text-[11px] text-fg-muted italic">—</span>
                  )}
                </div>
              </div>
              {typeof latencyMs === "number" && latencyMs > 0 && (
                <div className="flex items-center gap-1 text-[11px] text-fg-muted shrink-0">
                  <Timer className="w-3 h-3" strokeWidth={2} />
                  <span className="font-medium text-fg">{formatLatency(latencyMs)}</span>
                </div>
              )}
            </div>
            {data.code && (
              <button
                onClick={() => setShowCode(!showCode)}
                className="mt-2 text-[10.5px] text-fg-muted hover:text-accent flex items-center gap-1 transition-colors"
              >
                <Code2 className="w-3 h-3" />
                {showCode ? "Hide" : "View"} generated pandas code
              </button>
            )}
            {showCode && data.code && <CodeBlock code={data.code} />}
          </div>
        </div>
      </div>
    </motion.div>
  );
}

function formatLatency(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

function ChartRenderer({
  chart,
}: {
  chart: {
    type: "bar" | "line" | "pie";
    title: string;
    xAxis?: string[];
    series: { name: string; data: number[] }[];
  };
}) {
  const option: any = {
    backgroundColor: "transparent",
    title: {
      text: chart.title || "",
      left: "center",
      textStyle: { fontSize: 13, fontWeight: 600, color: "#1d1d1f" },
    },
    tooltip: { trigger: chart.type === "pie" ? "item" : "axis" },
    grid: { left: "8%", right: "5%", bottom: "12%", top: "18%" },
  };

  if (chart.type === "pie") {
    option.series = [
      {
        type: "pie",
        radius: ["40%", "70%"],
        data: (chart.series[0]?.data || []).map((v: number, i: number) => ({
          value: v,
          name: chart.xAxis?.[i] || `Item ${i + 1}`,
        })),
        emphasis: { itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: "rgba(0,0,0,0.15)" } },
        label: { fontSize: 11 },
      },
    ];
  } else {
    option.xAxis = {
      type: "category",
      data: chart.xAxis || [],
      axisLabel: { fontSize: 10, rotate: chart.xAxis && chart.xAxis.length > 8 ? 30 : 0 },
    };
    option.yAxis = { type: "value", axisLabel: { fontSize: 10 } };
    option.series = (chart.series || []).map((s) => ({
      name: s.name,
      type: chart.type,
      data: s.data,
      smooth: chart.type === "line",
      barMaxWidth: 32,
      itemStyle: { borderRadius: chart.type === "bar" ? [4, 4, 0, 0] : undefined },
    }));
    if (chart.series.length > 1) {
      option.legend = {
        bottom: 0,
        textStyle: { fontSize: 10 },
      };
    }
  }

  return (
    <div className="card overflow-hidden">
      <ReactECharts option={option} style={{ height: 260, width: "100%" }} />
    </div>
  );
}

function CodeBlock({ code }: { code: string }) {
  return (
    <div className="rounded-md border border-border bg-[#1e1e2e] px-3 py-2.5 overflow-x-auto">
      <pre className="text-[11.5px] leading-relaxed text-[#cdd6f4] font-mono whitespace-pre">
        {code}
      </pre>
    </div>
  );
}

function prettifyFilename(fn: string): string {
  return fn.replace(/\.[a-z0-9]+$/i, "").replace(/[_-]/g, " ");
}

function formatCell(value: any): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") {
    if (Number.isInteger(value)) return value.toLocaleString();
    return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }
  return String(value);
}
