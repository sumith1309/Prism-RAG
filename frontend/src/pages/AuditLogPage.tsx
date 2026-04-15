import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, Filter, Loader2, XCircle } from "lucide-react";
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

  return (
    <div className="flex-1 flex flex-col min-h-0 min-w-0">
      <div className="px-6 py-5 border-b border-border">
        <div className="text-[11px] uppercase tracking-wider text-fg-muted">Compliance</div>
        <h1 className="text-xl font-semibold text-fg mt-0.5">Audit log</h1>
        <p className="text-sm text-fg-muted mt-1">
          Every query against /api/chat — who asked, their clearance, what we retrieved, and
          whether access was refused.
        </p>

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
