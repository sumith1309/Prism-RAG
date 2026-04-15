import { useEffect, useMemo, useState } from "react";
import { Activity, AlertTriangle, CheckCircle2, Clock, Filter, Gauge, Loader2, ShieldAlert, XCircle } from "lucide-react";
import ReactECharts from "echarts-for-react";
import { fetchAudit } from "@/lib/api";
import { useAppStore } from "@/store/appStore";
import { cn } from "@/lib/utils";
import type { AuditRow } from "@/types";

type StatusFilter = "all" | "answered" | "refused";

export function AuditLogPage() {
  const user = useAppStore((s) => s.user);
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");

  useEffect(() => {
    if (!user || user.level < 4) return;
    let alive = true;
    setLoading(true);
    fetchAudit(500)
      .then((r) => alive && setRows(r.rows))
      .catch((e) => alive && setError(String(e.message || e)))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [user]);

  const filtered = useMemo(() => {
    return rows.filter((r) => {
      if (statusFilter === "answered" && r.refused) return false;
      if (statusFilter === "refused" && !r.refused) return false;
      if (q) {
        const needle = q.toLowerCase();
        if (
          !r.query.toLowerCase().includes(needle) &&
          !r.username.toLowerCase().includes(needle)
        )
          return false;
      }
      return true;
    });
  }, [rows, statusFilter, q]);

  if (!user || user.level < 4) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-center px-6">
        <AlertTriangle className="w-8 h-8 text-clearance-confidential mb-3" strokeWidth={1.5} />
        <div className="text-lg font-semibold text-fg">Audit log is executive-only</div>
        <div className="text-sm text-fg-muted mt-1 max-w-sm">
          Your current role ({user?.role || "unknown"}, level {user?.level ?? 0}) does not have
          clearance to view the global audit log.
        </div>
      </div>
    );
  }

  const kpis = useMemo(() => computeKpis(rows), [rows]);

  return (
    <div className="flex-1 flex flex-col min-h-0 min-w-0">
      <div className="px-6 py-5 border-b border-border">
        <div className="text-[11px] uppercase tracking-wider text-fg-muted">Compliance</div>
        <h1 className="text-xl font-semibold text-fg mt-0.5">Audit log</h1>
        <p className="text-sm text-fg-muted mt-1">
          Every query against /api/chat — who asked, their clearance, what we retrieved, and
          whether access was refused.
        </p>

        {!loading && rows.length > 0 && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-4">
            <KpiCard
              icon={<Activity className="w-3.5 h-3.5" />}
              label="Queries (24h)"
              value={kpis.queries24h.toString()}
              hint={`${rows.length.toLocaleString()} all-time`}
              spark={kpis.spark24hQueries}
              color="#7c6cff"
            />
            <KpiCard
              icon={<ShieldAlert className="w-3.5 h-3.5" />}
              label="Refused / unknown"
              value={`${kpis.refusedPct}%`}
              hint={`${kpis.refused24h} in last 24h`}
              spark={kpis.spark24hRefused}
              color="#ef4444"
            />
            <KpiCard
              icon={<Clock className="w-3.5 h-3.5" />}
              label="Avg latency (24h)"
              value={`${kpis.avgLatencyMs}ms`}
              hint={`p95 ${kpis.p95LatencyMs}ms`}
              spark={kpis.spark24hLatency}
              color="#3b82f6"
            />
            <KpiCard
              icon={<Gauge className="w-3.5 h-3.5" />}
              label="Avg faithfulness"
              value={
                kpis.avgFaith === null ? "—" : `${Math.round(kpis.avgFaith * 100)}%`
              }
              hint={`${kpis.scoredCount} grounded scored`}
              spark={kpis.spark24hFaith}
              color="#22c55e"
            />
          </div>
        )}

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <div className="relative">
            <Filter className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-fg-subtle" />
            <input
              className="input pl-9 w-72"
              placeholder="Filter by query or user…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>
          <div className="flex items-center gap-1 bg-bg-elevated border border-border rounded-md p-0.5">
            {(["all", "answered", "refused"] as StatusFilter[]).map((f) => (
              <button
                key={f}
                onClick={() => setStatusFilter(f)}
                className={cn(
                  "px-2.5 py-1 text-xs rounded-sm capitalize transition-colors",
                  statusFilter === f
                    ? "bg-surface-active text-fg"
                    : "text-fg-muted hover:text-fg"
                )}
              >
                {f}
              </button>
            ))}
          </div>
          <div className="ml-auto text-xs text-fg-muted">
            {filtered.length} of {rows.length} rows
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-auto scrollbar-thin">
        {loading && (
          <div className="flex items-center justify-center py-16 text-fg-muted">
            <Loader2 className="w-5 h-5 animate-spin mr-2" /> Loading audit log…
          </div>
        )}
        {error && (
          <div className="px-6 py-4 text-sm text-clearance-restricted">Error: {error}</div>
        )}

        {!loading && !error && (
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-bg border-b border-border text-fg-muted">
              <tr className="text-left">
                <th className="px-4 py-2.5 font-medium text-[11px] uppercase tracking-wider">
                  Time
                </th>
                <th className="px-4 py-2.5 font-medium text-[11px] uppercase tracking-wider">
                  User
                </th>
                <th className="px-4 py-2.5 font-medium text-[11px] uppercase tracking-wider">
                  Level
                </th>
                <th className="px-4 py-2.5 font-medium text-[11px] uppercase tracking-wider">
                  Status
                </th>
                <th className="px-4 py-2.5 font-medium text-[11px] uppercase tracking-wider">
                  Query
                </th>
                <th className="px-4 py-2.5 font-medium text-[11px] uppercase tracking-wider text-right">
                  Chunks
                </th>
                <th className="px-4 py-2.5 font-medium text-[11px] uppercase tracking-wider text-right">
                  Cited docs
                </th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => (
                <tr key={r.id} className="border-b border-border/60 hover:bg-surface-hover/40">
                  <td className="px-4 py-2.5 text-fg-muted font-mono text-xs whitespace-nowrap">
                    {new Date(r.ts).toLocaleString()}
                  </td>
                  <td className="px-4 py-2.5 text-fg font-medium">{r.username}</td>
                  <td className="px-4 py-2.5 text-fg-muted">L{r.user_level}</td>
                  <td className="px-4 py-2.5">
                    {r.refused ? (
                      <span className="inline-flex items-center gap-1.5 text-clearance-restricted">
                        <XCircle className="w-3.5 h-3.5" />
                        <span className="text-xs font-medium">REFUSED</span>
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1.5 text-clearance-public">
                        <CheckCircle2 className="w-3.5 h-3.5" />
                        <span className="text-xs font-medium">ANSWERED</span>
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 max-w-xl">
                    <div className="truncate text-fg" title={r.query}>
                      {r.query}
                    </div>
                  </td>
                  <td className="px-4 py-2.5 text-right text-fg-muted font-mono text-xs">
                    {r.returned_chunks}
                  </td>
                  <td className="px-4 py-2.5 text-right text-fg-muted font-mono text-xs">
                    {r.allowed_doc_ids.length}
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && !loading && (
                <tr>
                  <td className="px-4 py-8 text-center text-fg-muted" colSpan={7}>
                    No rows match the current filter.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

// ─── KPI strip helpers ───────────────────────────────────────────────────

interface AuditKpis {
  queries24h: number;
  refused24h: number;
  refusedPct: number;
  avgLatencyMs: number;
  p95LatencyMs: number;
  avgFaith: number | null;
  scoredCount: number;
  spark24hQueries: number[];
  spark24hRefused: number[];
  spark24hLatency: number[];
  spark24hFaith: number[];
}

function computeKpis(rows: AuditRow[]): AuditKpis {
  const empty: AuditKpis = {
    queries24h: 0,
    refused24h: 0,
    refusedPct: 0,
    avgLatencyMs: 0,
    p95LatencyMs: 0,
    avgFaith: null,
    scoredCount: 0,
    spark24hQueries: [],
    spark24hRefused: [],
    spark24hLatency: [],
    spark24hFaith: [],
  };
  if (!rows.length) return empty;

  const now = Date.now();
  const start = now - 24 * 3600_000;
  const buckets = 24;
  const sliceMs = (now - start) / buckets;

  const sparkQueries: number[] = Array(buckets).fill(0);
  const sparkRefused: number[] = Array(buckets).fill(0);
  const latencyByBucket: number[][] = Array.from({ length: buckets }, () => []);
  const faithByBucket: number[][] = Array.from({ length: buckets }, () => []);

  let queries24h = 0;
  let refused24h = 0;
  const allLatencies: number[] = [];
  const allFaiths: number[] = [];

  for (const r of rows) {
    const t = new Date(r.ts).getTime();
    if (t < start) continue;
    queries24h++;
    const idx = Math.min(buckets - 1, Math.max(0, Math.floor((t - start) / sliceMs)));
    sparkQueries[idx]++;
    if (r.refused) {
      refused24h++;
      sparkRefused[idx]++;
    }
    const lat = r.latency_total_ms ?? 0;
    if (lat > 0) {
      allLatencies.push(lat);
      latencyByBucket[idx].push(lat);
    }
    const f = r.faithfulness ?? -1;
    if (f >= 0) {
      allFaiths.push(f);
      faithByBucket[idx].push(f);
    }
  }

  const avgLatencyMs = allLatencies.length
    ? Math.round(allLatencies.reduce((a, b) => a + b, 0) / allLatencies.length)
    : 0;
  const sortedLat = [...allLatencies].sort((a, b) => a - b);
  const p95LatencyMs = sortedLat[Math.floor(sortedLat.length * 0.95)] ?? 0;
  const avgFaith = allFaiths.length
    ? allFaiths.reduce((a, b) => a + b, 0) / allFaiths.length
    : null;

  return {
    queries24h,
    refused24h,
    refusedPct: queries24h ? Math.round((refused24h / queries24h) * 100) : 0,
    avgLatencyMs,
    p95LatencyMs,
    avgFaith,
    scoredCount: allFaiths.length,
    spark24hQueries: sparkQueries,
    spark24hRefused: sparkRefused,
    spark24hLatency: latencyByBucket.map((b) =>
      b.length ? Math.round(b.reduce((a, c) => a + c, 0) / b.length) : 0
    ),
    spark24hFaith: faithByBucket.map((b) =>
      b.length ? +(b.reduce((a, c) => a + c, 0) / b.length).toFixed(3) : 0
    ),
  };
}

function KpiCard({
  icon,
  label,
  value,
  hint,
  spark,
  color,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  hint?: string;
  spark: number[];
  color: string;
}) {
  const option = useMemo(
    () => ({
      grid: { left: 0, right: 0, top: 4, bottom: 0 },
      xAxis: { type: "category", show: false, data: spark.map((_, i) => i) },
      yAxis: { type: "value", show: false },
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "none" },
        formatter: (params: any[]) => `<b>${params[0].value}</b>`,
      },
      series: [
        {
          type: "line",
          smooth: true,
          symbol: "none",
          areaStyle: {
            color: {
              type: "linear",
              x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0, color: color + "55" },
                { offset: 1, color: color + "00" },
              ],
            },
          },
          lineStyle: { color, width: 1.6 },
          data: spark,
        },
      ],
    }),
    [spark, color]
  );

  return (
    <div className="rounded-md border border-border bg-white shadow-sm overflow-hidden">
      <div className="px-3 pt-3 pb-1">
        <div className="flex items-center gap-1.5 text-fg-subtle text-[10.5px] uppercase tracking-wider font-semibold">
          <span style={{ color }}>{icon}</span>
          {label}
        </div>
        <div className="flex items-baseline gap-2 mt-1">
          <div className="text-[20px] font-semibold text-fg tabular-nums">
            {value}
          </div>
          {hint && <div className="text-[10.5px] text-fg-muted">{hint}</div>}
        </div>
      </div>
      <div className="h-9">
        <ReactECharts option={option} style={{ height: "100%", width: "100%" }} />
      </div>
    </div>
  );
}
