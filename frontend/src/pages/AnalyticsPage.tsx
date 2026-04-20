import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import ReactECharts from "echarts-for-react";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  CalendarClock,
  CheckCircle2,
  Clock,
  Coins,
  Gauge,
  GitBranch,
  HelpCircle,
  Loader2,
  PieChart,
  ShieldAlert,
  Sparkles,
  TrendingUp,
  Users,
} from "lucide-react";

import { fetchAudit } from "@/lib/api";
import { useAppStore } from "@/store/appStore";
import { cn } from "@/lib/utils";
import type { AnswerMode, AuditRow } from "@/types";

export function AnalyticsPage() {
  const user = useAppStore((s) => s.user);
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!user || user.level < 4) return;
    let alive = true;
    setLoading(true);
    fetchAudit(1000)
      .then((r) => alive && setRows(r.rows))
      .catch((e) => alive && setError(String(e.message || e)))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [user]);

  const stats = useMemo(() => computeStats(rows), [rows]);

  if (!user || user.level < 4) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-center px-6">
        <AlertTriangle className="w-8 h-8 text-clearance-confidential mb-3" strokeWidth={1.5} />
        <div className="text-lg font-semibold text-fg">Analytics is executive-only</div>
        <div className="text-sm text-fg-muted mt-1 max-w-sm">
          Your current role ({user?.role || "unknown"}, level {user?.level ?? 0}) does not have
          clearance to view the observability dashboard.
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col min-h-0 min-w-0">
      <div className="px-6 py-5 border-b border-border">
        <div className="text-[11px] uppercase tracking-wider text-fg-muted">
          Observability
        </div>
        <h1 className="text-xl font-semibold text-fg mt-0.5">Analytics</h1>
        <p className="text-sm text-fg-muted mt-1">
          Live observability built from the audit log — every query writes one row; every row
          carries the full latency, token, mode, and faithfulness payload.
        </p>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin p-6 space-y-6">
        {loading && (
          <div className="flex items-center justify-center py-16 text-fg-muted">
            <Loader2 className="w-5 h-5 animate-spin mr-2" /> Loading analytics…
          </div>
        )}
        {error && (
          <div className="text-sm text-clearance-restricted">Error: {error}</div>
        )}

        {!loading && !error && stats && (
          <>
            {/* Top-level counters */}
            <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <StatCard
                icon={<Activity className="w-4 h-4" />}
                label="Total queries"
                value={stats.total.toLocaleString()}
              />
              <StatCard
                icon={<Users className="w-4 h-4" />}
                label="Unique users"
                value={stats.uniqueUsers.toString()}
              />
              <StatCard
                icon={<Clock className="w-4 h-4" />}
                label="Avg latency"
                value={`${stats.avgLatencyMs}ms`}
                hint={`p95 ${stats.p95LatencyMs}ms`}
              />
              <StatCard
                icon={<Coins className="w-4 h-4" />}
                label="Total tokens"
                value={compact(stats.totalTokens)}
                hint={`~$${stats.estCostUSD.toFixed(2)}`}
              />
            </section>

            {/* Distribution + Faithfulness gauge */}
            <section className="grid grid-cols-1 lg:grid-cols-[1.2fr_1fr] gap-3">
              <Panel title="Answer-mode distribution" icon={<PieChart className="w-3.5 h-3.5" />}>
                <ModeDonut byMode={stats.byMode} total={stats.total} />
              </Panel>

              <Panel title="Average faithfulness" icon={<Gauge className="w-3.5 h-3.5" />}>
                <FaithfulnessGauge
                  value={stats.avgFaithfulness}
                  scoredCount={stats.scoredCount}
                  groundedTotal={stats.byMode.grounded}
                />
              </Panel>
            </section>

            {/* Activity over time */}
            <Panel title="Activity over time" icon={<TrendingUp className="w-3.5 h-3.5" />}>
              <ActivityTimeline rows={rows} />
            </Panel>

            {/* Sankey + Heatmap */}
            <section className="grid grid-cols-1 lg:grid-cols-2 gap-3">
              <Panel title="Role → Answer mode" icon={<GitBranch className="w-3.5 h-3.5" />}>
                <RoleModeSankey rows={rows} />
              </Panel>
              <Panel title="When are queries asked?" icon={<CalendarClock className="w-3.5 h-3.5" />}>
                <WeekHourHeatmap rows={rows} />
              </Panel>
            </section>

            {/* Latency breakdown — proper ECharts horizontal bars */}
            <Panel title="Latency breakdown (avg ms)" icon={<BarChart3 className="w-3.5 h-3.5" />}>
              <LatencyBreakdown
                retrieve={stats.avgRetrieveMs}
                rerank={stats.avgRerankMs}
                generate={stats.avgGenerateMs}
              />
            </Panel>

            {/* Per-user usage */}
            <Panel title="Queries by user" icon={<Users className="w-3.5 h-3.5" />}>
              <UserBars byRole={stats.byRole} total={stats.total} />
            </Panel>

            {/* Top queries table */}
            <Panel title="Most frequent queries" icon={<TrendingUp className="w-3.5 h-3.5" />}>
              <div className="space-y-0.5 mt-1">
                {stats.topQueries.slice(0, 10).map(([q, n], i) => (
                  <div
                    key={q}
                    className="flex items-center gap-2 text-[12px] py-1.5 border-b border-border last:border-0"
                  >
                    <span className="w-5 h-5 rounded bg-accent-soft text-accent flex items-center justify-center text-[10px] font-bold border border-accent/20 shrink-0">
                      {i + 1}
                    </span>
                    <span className="truncate text-fg flex-1" title={q}>
                      {q}
                    </span>
                    <span className="font-mono text-fg-muted text-[11px]">{n}×</span>
                  </div>
                ))}
                {stats.topQueries.length === 0 && (
                  <div className="text-center text-fg-subtle text-[12px] py-4">
                    No queries yet.
                  </div>
                )}
              </div>
            </Panel>
          </>
        )}
      </div>
    </div>
  );
}

// ─── helpers ────────────────────────────────────────────────────────────

function StatCard({
  icon,
  label,
  value,
  hint,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      className="card p-4"
    >
      <div className="flex items-center gap-1.5 text-fg-subtle text-[10.5px] uppercase tracking-wider font-semibold mb-2">
        {icon}
        {label}
      </div>
      <div className="text-2xl font-semibold text-fg tabular-nums">{value}</div>
      {hint && <div className="text-[11px] text-fg-muted mt-1">{hint}</div>}
    </motion.div>
  );
}

function Panel({
  title,
  icon,
  children,
}: {
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      className="card p-4"
    >
      <div className="flex items-center gap-1.5 text-fg-muted mb-3">
        {icon}
        <span className="text-[10.5px] uppercase tracking-wider font-semibold">
          {title}
        </span>
      </div>
      {children}
    </motion.div>
  );
}

// ─── ECharts panels ───────────────────────────────────────────────────────

const MODE_COLORS: Record<AnswerMode, string> = {
  grounded: "#22c55e",
  general: "#3b82f6",
  refused: "#ef4444",
  unknown: "#6b7280",
  social: "#a855f7",
  meta: "#f59e0b",
  system: "#06b6d4",
  disambiguate: "#8b5cf6",
  comparison: "#14b8a6",
  blocked: "#dc2626",
};

function ModeDonut({
  byMode,
  total,
}: {
  byMode: Record<AnswerMode, number>;
  total: number;
}) {
  const option = useMemo(() => {
    const data = (Object.entries(byMode) as [AnswerMode, number][])
      .filter(([, n]) => n > 0)
      .map(([m, n]) => ({
        name: m,
        value: n,
        itemStyle: { color: MODE_COLORS[m] },
      }));
    return {
      tooltip: {
        trigger: "item",
        formatter: (p: any) =>
          `<b style="text-transform:capitalize">${p.name}</b><br/>` +
          `<span style="color:${p.color}">●</span> ${p.value} queries (${p.percent}%)`,
      },
      legend: {
        bottom: 0,
        textStyle: { color: "#374151", fontSize: 11 },
        itemWidth: 10,
        itemHeight: 10,
      },
      series: [
        {
          type: "pie",
          radius: ["55%", "78%"],
          center: ["50%", "44%"],
          avoidLabelOverlap: true,
          itemStyle: { borderColor: "#fff", borderWidth: 2 },
          label: {
            show: true,
            position: "center",
            formatter: () =>
              `{big|${total}}\n{lbl|TOTAL QUERIES}`,
            rich: {
              big: { fontSize: 28, fontWeight: 700, color: "#111827" },
              lbl: {
                fontSize: 10,
                color: "#6b7280",
                lineHeight: 18,
                letterSpacing: 1.2,
              },
            },
          },
          emphasis: {
            scale: true,
            scaleSize: 4,
            label: {
              formatter: (p: any) =>
                `{big|${p.value}}\n{lbl|${String(p.name).toUpperCase()}}`,
            },
          },
          data,
        },
      ],
    };
  }, [byMode, total]);
  return <ReactECharts option={option} style={{ height: 240, width: "100%" }} />;
}

function FaithfulnessGauge({
  value,
  scoredCount,
  groundedTotal,
}: {
  value: number | null;
  scoredCount: number;
  groundedTotal: number;
}) {
  const v = value ?? 0;
  const option = useMemo(
    () => ({
      series: [
        {
          type: "gauge",
          min: 0,
          max: 1,
          startAngle: 200,
          endAngle: -20,
          radius: "92%",
          progress: { show: true, width: 14, roundCap: true },
          axisLine: {
            lineStyle: {
              width: 14,
              color: [
                [0.5, "#ef4444"],
                [0.8, "#f59e0b"],
                [1, "#22c55e"],
              ],
            },
          },
          axisTick: { show: false },
          splitLine: { show: false },
          axisLabel: { show: false },
          pointer: { show: false },
          anchor: { show: false },
          itemStyle: { color: "#7c6cff" },
          detail: {
            valueAnimation: true,
            formatter: (val: number) =>
              value === null ? "—" : `${Math.round(val * 100)}%`,
            fontSize: 26,
            fontWeight: 700,
            color: "#111827",
            offsetCenter: [0, "20%"],
          },
          title: {
            show: true,
            offsetCenter: [0, "65%"],
            color: "#6b7280",
            fontSize: 11,
          },
          data: [{ value: v, name: "GROUNDED ALIGNMENT" }],
        },
      ],
    }),
    [v, value]
  );
  return (
    <div>
      <div style={{ height: 200 }}>
        <ReactECharts option={option} style={{ height: "100%", width: "100%" }} />
      </div>
      <div className="text-[11px] text-fg-muted text-center -mt-2">
        {scoredCount} of {groundedTotal} grounded responses scored by LLM judge.
      </div>
    </div>
  );
}

function ActivityTimeline({ rows }: { rows: AuditRow[] }) {
  const option = useMemo(() => {
    if (!rows.length) return null;
    // Bucket per-hour, last 48h.
    const now = Date.now();
    const start = now - 48 * 3600_000;
    const bucketKeys: number[] = [];
    for (let t = Math.floor(start / 3600_000) * 3600_000; t <= now; t += 3600_000) {
      bucketKeys.push(t);
    }
    const modes: AnswerMode[] = ["grounded", "general", "meta", "social", "refused", "unknown"];
    const series: Record<AnswerMode, number[]> = Object.fromEntries(
      modes.map((m) => [m, bucketKeys.map(() => 0)])
    ) as any;
    for (const r of rows) {
      const t = new Date(r.ts).getTime();
      if (t < start) continue;
      const idx = Math.floor((t - bucketKeys[0]) / 3600_000);
      if (idx < 0 || idx >= bucketKeys.length) continue;
      const m = (r.answer_mode || "grounded") as AnswerMode;
      if (series[m]) series[m][idx]++;
    }
    return {
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "line" },
      },
      legend: {
        top: 0,
        textStyle: { color: "#374151", fontSize: 11 },
        itemWidth: 10,
        itemHeight: 10,
      },
      grid: { left: 40, right: 16, top: 30, bottom: 30 },
      xAxis: {
        type: "category",
        data: bucketKeys.map((t) => {
          const d = new Date(t);
          return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:00`;
        }),
        axisLabel: {
          color: "#6b7280",
          fontSize: 10,
          interval: Math.max(0, Math.floor(bucketKeys.length / 8) - 1),
        },
        axisTick: { show: false },
      },
      yAxis: {
        type: "value",
        axisLabel: { color: "#6b7280", fontSize: 10 },
        splitLine: { lineStyle: { color: "#eef0f5" } },
      },
      series: modes.map((m) => ({
        name: m,
        type: "line",
        stack: "total",
        smooth: true,
        showSymbol: false,
        areaStyle: { opacity: 0.85 },
        lineStyle: { width: 0 },
        itemStyle: { color: MODE_COLORS[m] },
        emphasis: { focus: "series" },
        data: series[m],
      })),
    };
  }, [rows]);
  if (!option) return <EmptyChart />;
  return <ReactECharts option={option} style={{ height: 260, width: "100%" }} />;
}

function RoleModeSankey({ rows }: { rows: AuditRow[] }) {
  const option = useMemo(() => {
    if (!rows.length) return null;
    type Edge = { source: string; target: string; value: number };
    const counts = new Map<string, number>();
    for (const r of rows) {
      const role = r.username || "anon";
      const mode = r.answer_mode || "grounded";
      const k = `${role}|${mode}`;
      counts.set(k, (counts.get(k) || 0) + 1);
    }
    const roles = Array.from(new Set(rows.map((r) => r.username || "anon"))).sort();
    const modes = Array.from(new Set(rows.map((r) => r.answer_mode || "grounded"))).sort();
    const links: Edge[] = Array.from(counts.entries()).map(([k, v]) => {
      const [s, t] = k.split("|");
      return { source: s, target: t, value: v };
    });
    return {
      tooltip: { trigger: "item" },
      series: [
        {
          type: "sankey",
          left: 8,
          right: 110,
          top: 12,
          bottom: 12,
          data: [
            ...roles.map((r) => ({ name: r, itemStyle: { color: "#7c6cff" } })),
            ...modes.map((m) => ({
              name: m,
              itemStyle: { color: MODE_COLORS[m as AnswerMode] || "#9ca3af" },
            })),
          ],
          links,
          label: {
            color: "#374151",
            fontSize: 11,
            fontWeight: 500,
          },
          lineStyle: { color: "gradient", curveness: 0.55 },
          emphasis: { focus: "adjacency" },
          nodeAlign: "left",
        },
      ],
    };
  }, [rows]);
  if (!option) return <EmptyChart />;
  return <ReactECharts option={option} style={{ height: 280, width: "100%" }} />;
}

function WeekHourHeatmap({ rows }: { rows: AuditRow[] }) {
  const option = useMemo(() => {
    if (!rows.length) return null;
    const days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
    const hours = Array.from({ length: 24 }, (_, h) => `${h}h`);
    const grid: number[][] = Array.from({ length: 7 }, () => Array(24).fill(0));
    for (const r of rows) {
      const d = new Date(r.ts);
      grid[d.getDay()][d.getHours()]++;
    }
    const data: [number, number, number][] = [];
    let max = 0;
    for (let d = 0; d < 7; d++) {
      for (let h = 0; h < 24; h++) {
        data.push([h, d, grid[d][h]]);
        if (grid[d][h] > max) max = grid[d][h];
      }
    }
    return {
      tooltip: {
        position: "top",
        formatter: (p: any) =>
          `<b>${days[p.value[1]]} ${p.value[0]}:00</b><br/>${p.value[2]} queries`,
      },
      grid: { top: 20, left: 50, right: 20, bottom: 30 },
      xAxis: {
        type: "category",
        data: hours,
        axisLabel: { color: "#6b7280", fontSize: 10 },
        splitArea: { show: true },
        axisTick: { show: false },
      },
      yAxis: {
        type: "category",
        data: days,
        axisLabel: { color: "#374151", fontSize: 11, fontWeight: 500 },
        axisTick: { show: false },
      },
      visualMap: {
        min: 0,
        max: Math.max(1, max),
        calculable: false,
        orient: "horizontal",
        left: "center",
        bottom: 0,
        textStyle: { color: "#6b7280", fontSize: 10 },
        inRange: { color: ["#f4f6fb", "#c3c9ee", "#7c6cff", "#352d8c"] },
        itemHeight: 80,
      },
      series: [
        {
          type: "heatmap",
          data,
          label: { show: false },
          emphasis: {
            itemStyle: { shadowBlur: 8, shadowColor: "rgba(124,108,255,0.5)" },
          },
        },
      ],
    };
  }, [rows]);
  if (!option) return <EmptyChart />;
  return <ReactECharts option={option} style={{ height: 280, width: "100%" }} />;
}

function LatencyBreakdown({
  retrieve,
  rerank,
  generate,
}: {
  retrieve: number;
  rerank: number;
  generate: number;
}) {
  const option = useMemo(
    () => ({
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "shadow" },
        formatter: (params: any[]) => {
          const total = params.reduce((s, p) => s + p.value, 0);
          return params
            .map(
              (p) =>
                `<span style="color:${p.color}">●</span> ${p.seriesName}: <b>${p.value}ms</b>`
            )
            .join("<br/>") + `<br/>Total: <b>${total}ms</b>`;
        },
      },
      legend: { top: 0, textStyle: { color: "#374151", fontSize: 11 } },
      grid: { left: 40, right: 30, top: 30, bottom: 16 },
      xAxis: {
        type: "value",
        axisLabel: { color: "#6b7280", fontSize: 10, formatter: "{value}ms" },
        splitLine: { lineStyle: { color: "#eef0f5" } },
      },
      yAxis: {
        type: "category",
        data: ["avg query"],
        axisTick: { show: false },
        axisLabel: { color: "#374151" },
        axisLine: { show: false },
      },
      series: [
        { name: "Retrieve", type: "bar", stack: "total", data: [retrieve], itemStyle: { color: "#3b82f6", borderRadius: [4, 0, 0, 4] } },
        { name: "Rerank", type: "bar", stack: "total", data: [rerank], itemStyle: { color: "#a855f7" } },
        { name: "Generate", type: "bar", stack: "total", data: [generate], itemStyle: { color: "#22c55e", borderRadius: [0, 4, 4, 0] } },
      ],
    }),
    [retrieve, rerank, generate]
  );
  return <ReactECharts option={option} style={{ height: 110, width: "100%" }} />;
}

function UserBars({
  byRole,
  total,
}: {
  byRole: Record<string, number>;
  total: number;
}) {
  const sorted = useMemo(
    () =>
      Object.entries(byRole)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 12),
    [byRole]
  );
  const option = useMemo(
    () => ({
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "shadow" },
        formatter: (params: any[]) => {
          const p = params[0];
          const pct = total ? ((p.value / total) * 100).toFixed(1) : "0";
          return `<b>${p.name}</b><br/>${p.value} queries · ${pct}%`;
        },
      },
      grid: { left: 90, right: 30, top: 8, bottom: 16 },
      xAxis: {
        type: "value",
        axisLabel: { color: "#6b7280", fontSize: 10 },
        splitLine: { lineStyle: { color: "#eef0f5" } },
      },
      yAxis: {
        type: "category",
        data: sorted.map(([u]) => u).reverse(),
        axisLabel: { color: "#374151", fontSize: 11, fontWeight: 500 },
        axisTick: { show: false },
        axisLine: { show: false },
      },
      series: [
        {
          type: "bar",
          data: sorted
            .map(([, n]) => n)
            .reverse()
            .map((v) => ({ value: v, itemStyle: { color: "#7c6cff", borderRadius: [0, 4, 4, 0] } })),
          barWidth: 14,
          label: {
            show: true,
            position: "right",
            color: "#111827",
            fontSize: 10.5,
            fontWeight: 600,
          },
        },
      ],
    }),
    [sorted, total]
  );
  if (!sorted.length) return <EmptyChart />;
  return <ReactECharts option={option} style={{ height: Math.max(120, sorted.length * 24), width: "100%" }} />;
}

function EmptyChart() {
  return (
    <div className="text-center text-fg-subtle text-[12px] py-8 italic">
      No data yet — run a few queries and come back.
    </div>
  );
}

const MODE_STYLE: Record<
  AnswerMode,
  { label: string; icon: React.ElementType; color: string; barBg: string }
> = {
  grounded: { label: "Grounded", icon: CheckCircle2, color: "text-clearance-public", barBg: "bg-clearance-public" },
  general: { label: "General", icon: Sparkles, color: "text-accent", barBg: "bg-accent" },
  refused: { label: "Refused", icon: ShieldAlert, color: "text-clearance-restricted", barBg: "bg-clearance-restricted" },
  unknown: { label: "Unknown", icon: HelpCircle, color: "text-fg-muted", barBg: "bg-fg-muted/40" },
  social: { label: "Social", icon: Sparkles, color: "text-accent", barBg: "bg-accent/60" },
  meta: { label: "Meta", icon: Sparkles, color: "text-accent", barBg: "bg-accent/70" },
  system: { label: "System", icon: Sparkles, color: "text-accent", barBg: "bg-accent/80" },
  disambiguate: { label: "Clarify", icon: HelpCircle, color: "text-accent", barBg: "bg-accent/50" },
  comparison: { label: "Compare", icon: Sparkles, color: "text-accent", barBg: "bg-accent/70" },
  blocked: { label: "Blocked", icon: ShieldAlert, color: "text-clearance-restricted", barBg: "bg-clearance-restricted/60" },
};

function ModeBar({ mode, count, pct }: { mode: AnswerMode; count: number; pct: number }) {
  const s = MODE_STYLE[mode];
  const Icon = s.icon;
  return (
    <div>
      <div className="flex items-center gap-1.5 text-[11.5px] mb-1">
        <Icon className={cn("w-3 h-3", s.color)} strokeWidth={2} />
        <span className="text-fg">{s.label}</span>
        <span className="ml-auto font-mono text-fg-muted">
          {count} · {pct}%
        </span>
      </div>
      <div className="h-1.5 rounded-full bg-bg-subtle overflow-hidden">
        <div className={cn("h-full", s.barBg)} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function compact(n: number): string {
  if (n < 1000) return n.toString();
  if (n < 1_000_000) return `${(n / 1000).toFixed(1)}k`;
  return `${(n / 1_000_000).toFixed(2)}M`;
}

function computeStats(rows: AuditRow[]) {
  if (!rows.length) {
    return {
      total: 0,
      uniqueUsers: 0,
      cached: 0,
      cacheHitRate: 0,
      avgLatencyMs: 0,
      p95LatencyMs: 0,
      avgTotalMs: 0,
      avgRetrieveMs: 0,
      avgRerankMs: 0,
      avgGenerateMs: 0,
      totalTokens: 0,
      estCostUSD: 0,
      byMode: { grounded: 0, refused: 0, general: 0, unknown: 0 } as Record<AnswerMode, number>,
      byRole: {} as Record<string, number>,
      topQueries: [] as [string, number][],
      avgFaithfulness: null as number | null,
      scoredCount: 0,
    };
  }
  const total = rows.length;
  const uniqueUsers = new Set(rows.map((r) => r.username)).size;
  const cached = rows.filter((r) => r.cached).length;
  const cacheHitRate = Math.round((cached / total) * 100);

  const totals = rows.map((r) => r.latency_total_ms ?? 0);
  const avgLatencyMs = Math.round(totals.reduce((a, b) => a + b, 0) / total);
  const sorted = [...totals].sort((a, b) => a - b);
  const p95LatencyMs = sorted[Math.floor(sorted.length * 0.95)] ?? 0;

  const nonZero = (k: keyof AuditRow) => {
    const vals = rows.map((r) => (r[k] as number) ?? 0).filter((v) => v > 0);
    return vals.length ? Math.round(vals.reduce((a, b) => a + b, 0) / vals.length) : 0;
  };
  const avgRetrieveMs = nonZero("latency_retrieve_ms");
  const avgRerankMs = nonZero("latency_rerank_ms");
  const avgGenerateMs = nonZero("latency_generate_ms");
  const avgTotalMs = Math.max(avgRetrieveMs + avgRerankMs + avgGenerateMs, avgLatencyMs);

  const totalTokens = rows.reduce(
    (a, r) => a + (r.tokens_prompt ?? 0) + (r.tokens_completion ?? 0),
    0
  );
  // Rough rate: ~$0.005 / 1k prompt + $0.015 / 1k completion (gpt-4-class)
  const estCostUSD =
    (rows.reduce((a, r) => a + (r.tokens_prompt ?? 0), 0) / 1000) * 0.005 +
    (rows.reduce((a, r) => a + (r.tokens_completion ?? 0), 0) / 1000) * 0.015;

  const byMode: Record<AnswerMode, number> = {
    grounded: 0,
    refused: 0,
    general: 0,
    unknown: 0,
    social: 0,
    meta: 0,
    system: 0,
    disambiguate: 0,
    comparison: 0,
    blocked: 0,
  };
  for (const r of rows) {
    const m = (r.answer_mode || "grounded") as AnswerMode;
    byMode[m] = (byMode[m] || 0) + 1;
  }

  const byRole: Record<string, number> = {};
  for (const r of rows) byRole[r.username] = (byRole[r.username] || 0) + 1;

  const queryCounts: Record<string, number> = {};
  for (const r of rows) queryCounts[r.query] = (queryCounts[r.query] || 0) + 1;
  const topQueries = Object.entries(queryCounts).sort((a, b) => b[1] - a[1]);

  const scored = rows
    .filter((r) => (r.answer_mode || "grounded") === "grounded" && (r.faithfulness ?? -1) >= 0)
    .map((r) => r.faithfulness as number);
  const avgFaithfulness = scored.length
    ? scored.reduce((a, b) => a + b, 0) / scored.length
    : null;

  return {
    total,
    uniqueUsers,
    cached,
    cacheHitRate,
    avgLatencyMs,
    p95LatencyMs,
    avgTotalMs,
    avgRetrieveMs,
    avgRerankMs,
    avgGenerateMs,
    totalTokens,
    estCostUSD,
    byMode,
    byRole,
    topQueries,
    avgFaithfulness,
    scoredCount: scored.length,
  };
}
