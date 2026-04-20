import { useState } from "react";
import { motion } from "framer-motion";
import ReactECharts from "echarts-for-react";
import {
  BarChart3,
  ChevronDown,
  ChevronUp,
  Code2,
  Database,
  Sparkles,
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
}

export function DataCard({ data }: { data: AnalyticsPayload }) {
  const [showCode, setShowCode] = useState(false);
  const [showFullTable, setShowFullTable] = useState(false);

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
          {/* Header */}
          <div className="flex items-center gap-2 flex-wrap">
            <span className="inline-flex items-center gap-1 rounded-full border border-sky-200 bg-sky-50 px-2.5 py-[3px] text-[10.5px] font-semibold text-sky-700">
              <BarChart3 className="w-3 h-3" strokeWidth={2.25} />
              Data Analytics
            </span>
            <span className="text-[11px] text-fg-muted">
              from <span className="font-medium text-fg">{prettifyFilename(data.filename)}</span>
            </span>
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

          {/* Generated code toggle */}
          <button
            onClick={() => setShowCode(!showCode)}
            className="text-[11px] text-fg-muted hover:text-accent flex items-center gap-1 transition-colors"
          >
            <Code2 className="w-3 h-3" />
            {showCode ? "Hide" : "Show"} generated code
          </button>
          {showCode && data.code && <CodeBlock code={data.code} />}
        </div>
      </div>
    </motion.div>
  );
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
