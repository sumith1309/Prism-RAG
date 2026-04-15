import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  Clock,
  Coins,
  Gauge,
  HelpCircle,
  Loader2,
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

            {/* Mode distribution + cache */}
            <section className="grid grid-cols-1 lg:grid-cols-[1.2fr_1fr] gap-3">
              <Panel title="Answer modes" icon={<Sparkles className="w-3.5 h-3.5" />}>
                <div className="space-y-2 mt-1">
                  {(["grounded", "refused", "general", "unknown"] as AnswerMode[]).map((m) => {
                    const n = stats.byMode[m] || 0;
                    const pct = stats.total ? Math.round((n / stats.total) * 100) : 0;
                    return (
                      <ModeBar key={m} mode={m} count={n} pct={pct} />
                    );
                  })}
                </div>
              </Panel>

              <Panel title="Cache efficiency" icon={<Gauge className="w-3.5 h-3.5" />}>
                <div className="flex items-center justify-center h-full py-6">
                  <div className="text-center">
                    <div className="text-5xl font-semibold text-accent">
                      {stats.cacheHitRate}%
                    </div>
                    <div className="text-[11px] uppercase tracking-wider text-fg-subtle mt-1">
                      Cache hit rate
                    </div>
                    <div className="text-[11px] text-fg-muted mt-3">
                      {stats.cached.toLocaleString()} of {stats.total.toLocaleString()} queries
                      served from cache.
                    </div>
                  </div>
                </div>
              </Panel>
            </section>

            {/* Latency breakdown */}
            <Panel title="Latency breakdown (avg)" icon={<BarChart3 className="w-3.5 h-3.5" />}>
              <div className="grid grid-cols-[auto_1fr_auto] gap-x-3 gap-y-1.5 items-center text-[12px] mt-1">
                <span className="text-fg-muted">Retrieve</span>
                <div className="h-1.5 rounded-full bg-bg-subtle overflow-hidden">
                  <div
                    className="h-full bg-accent"
                    style={{ width: `${Math.min(100, (stats.avgRetrieveMs / Math.max(stats.avgTotalMs, 1)) * 100)}%` }}
                  />
                </div>
                <span className="font-mono text-fg text-right">{stats.avgRetrieveMs}ms</span>

                <span className="text-fg-muted">Rerank</span>
                <div className="h-1.5 rounded-full bg-bg-subtle overflow-hidden">
                  <div
                    className="h-full bg-accent/70"
                    style={{ width: `${Math.min(100, (stats.avgRerankMs / Math.max(stats.avgTotalMs, 1)) * 100)}%` }}
                  />
                </div>
                <span className="font-mono text-fg text-right">{stats.avgRerankMs}ms</span>

                <span className="text-fg-muted">Generate</span>
                <div className="h-1.5 rounded-full bg-bg-subtle overflow-hidden">
                  <div
                    className="h-full bg-clearance-internal"
                    style={{ width: `${Math.min(100, (stats.avgGenerateMs / Math.max(stats.avgTotalMs, 1)) * 100)}%` }}
                  />
                </div>
                <span className="font-mono text-fg text-right">{stats.avgGenerateMs}ms</span>
              </div>
            </Panel>

            {/* Per-role counts + faithfulness */}
            <section className="grid grid-cols-1 lg:grid-cols-2 gap-3">
              <Panel title="Queries by role" icon={<Users className="w-3.5 h-3.5" />}>
                <div className="space-y-2 mt-1">
                  {Object.entries(stats.byRole)
                    .sort((a, b) => b[1] - a[1])
                    .map(([label, count]) => {
                      const pct = stats.total ? Math.round((count / stats.total) * 100) : 0;
                      return (
                        <div key={label}>
                          <div className="flex items-center justify-between text-[11.5px] mb-1">
                            <span className="capitalize text-fg">{label}</span>
                            <span className="font-mono text-fg-muted">
                              {count} · {pct}%
                            </span>
                          </div>
                          <div className="h-1.5 rounded-full bg-bg-subtle overflow-hidden">
                            <div
                              className="h-full bg-accent"
                              style={{ width: `${pct}%` }}
                            />
                          </div>
                        </div>
                      );
                    })}
                </div>
              </Panel>

              <Panel
                title="Avg faithfulness (grounded only)"
                icon={<Gauge className="w-3.5 h-3.5" />}
              >
                <div className="flex items-center justify-center h-full py-6">
                  <div className="text-center">
                    <div
                      className={cn(
                        "text-5xl font-semibold",
                        stats.avgFaithfulness === null
                          ? "text-fg-subtle"
                          : stats.avgFaithfulness >= 0.8
                          ? "text-clearance-public"
                          : stats.avgFaithfulness >= 0.5
                          ? "text-clearance-confidential"
                          : "text-clearance-restricted"
                      )}
                    >
                      {stats.avgFaithfulness === null
                        ? "—"
                        : `${Math.round(stats.avgFaithfulness * 100)}%`}
                    </div>
                    <div className="text-[11px] uppercase tracking-wider text-fg-subtle mt-1">
                      Avg grounded answer alignment
                    </div>
                    <div className="text-[11px] text-fg-muted mt-3">
                      {stats.scoredCount} of {stats.byMode.grounded} grounded responses scored by
                      LLM judge.
                    </div>
                  </div>
                </div>
              </Panel>
            </section>

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

const MODE_STYLE: Record<
  AnswerMode,
  { label: string; icon: React.ElementType; color: string; barBg: string }
> = {
  grounded: { label: "Grounded", icon: CheckCircle2, color: "text-clearance-public", barBg: "bg-clearance-public" },
  general: { label: "General", icon: Sparkles, color: "text-accent", barBg: "bg-accent" },
  refused: { label: "Refused", icon: ShieldAlert, color: "text-clearance-restricted", barBg: "bg-clearance-restricted" },
  unknown: { label: "Unknown", icon: HelpCircle, color: "text-fg-muted", barBg: "bg-fg-muted/40" },
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
