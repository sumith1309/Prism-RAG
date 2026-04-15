import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import ForceGraph3D from "react-force-graph-3d";
// @ts-expect-error — three doesn't ship types via this shim
import * as THREE from "three";
// @ts-expect-error — three's example renderers have no shipped types
import { CSS2DRenderer, CSS2DObject } from "three/examples/jsm/renderers/CSS2DRenderer.js";
import {
  Activity,
  ArrowUpRight,
  Cpu,
  Database,
  EyeOff,
  Flame,
  Layers,
  ShieldCheck,
  Sparkles,
  Zap,
} from "lucide-react";
import { toast } from "sonner";

import { fetchGraph, fetchGraphHeat, traceGraphQuery } from "@/lib/api";
import type {
  Classification,
  GraphEdge,
  GraphNode,
  GraphTraceResponse,
  TraceStageHit,
} from "@/types";
import { useAppStore } from "@/store/appStore";
import { cn } from "@/lib/utils";

type LensRole = "executive" | "manager" | "employee" | "guest";

const ROLE_LEVEL: Record<LensRole, number> = {
  guest: 1,
  employee: 2,
  manager: 3,
  executive: 4,
};

const CLASSIFICATION_COLOR: Record<Classification, string> = {
  PUBLIC: "#22c55e",
  INTERNAL: "#3b82f6",
  CONFIDENTIAL: "#f59e0b",
  RESTRICTED: "#ef4444",
};

type Stage = "dense" | "bm25" | "rrf" | "rerank";

const STAGE_COLOR: Record<Stage, string> = {
  dense: "#3b82f6", // blue
  bm25: "#f97316", // orange
  rrf: "#a855f7", // purple
  rerank: "#facc15", // yellow — final top-k
};

interface FGNode extends GraphNode {
  x?: number;
  y?: number;
  z?: number;
}

export function GraphPage() {
  const { user } = useAppStore();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const fgRef = useRef<any>(null);

  const [nodes, setNodes] = useState<FGNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [stats, setStats] = useState<{
    docs: number;
    chunks: number;
    by_classification: Record<string, number>;
  } | null>(null);

  const [heat, setHeat] = useState<Record<string, number>>({}); // nodeId → retrieval/citation count
  const [lens, setLens] = useState<LensRole>("executive");
  const [showHeat, setShowHeat] = useState(true);
  const [selected, setSelected] = useState<FGNode | null>(null);

  // Live trace state
  const [traceQuery, setTraceQuery] = useState("");
  const [trace, setTrace] = useState<GraphTraceResponse | null>(null);
  const [tracing, setTracing] = useState(false);

  const [dim, setDim] = useState({ w: 0, h: 0 });
  useEffect(() => {
    const update = () => {
      if (containerRef.current) {
        const r = containerRef.current.getBoundingClientRect();
        setDim({ w: Math.max(320, r.width), h: Math.max(320, r.height) });
      }
    };
    update();
    const ro = new ResizeObserver(update);
    if (containerRef.current) ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    fetchGraph()
      .then((g) => {
        setNodes(g.nodes as FGNode[]);
        setEdges(g.edges);
        setStats(g.stats);
      })
      .catch((e) => toast.error(`Graph load failed: ${e.message}`));
    fetchGraphHeat()
      .then((h) => {
        const merged: Record<string, number> = {};
        for (const [docId, v] of Object.entries(h.docs)) {
          merged[`doc:${docId}`] = v.retrieved;
        }
        for (const [chunkId, v] of Object.entries(h.chunks)) {
          merged[chunkId] = (merged[chunkId] || 0) + v.cited;
        }
        setHeat(merged);
      })
      .catch(() => {
        /* heat is optional */
      });
  }, []);

  // Live-trace pipeline stage map. Each retrieved chunk is tagged with
  // the *latest* (highest-rank) stage it appeared in: dense → bm25 → rrf
  // → rerank. Drives the node colour overlay during a trace.
  const traceChunkStage = useMemo(() => {
    const m = new Map<string, { stage: Stage; score: number }>();
    const ingest = (hits: TraceStageHit[], stage: Stage) => {
      for (const h of hits) {
        const prev = m.get(h.chunk_id);
        const rank: Record<Stage, number> = { dense: 1, bm25: 2, rrf: 3, rerank: 4 };
        if (!prev || rank[stage] > rank[prev.stage]) {
          m.set(h.chunk_id, { stage, score: h.score });
        }
      }
    };
    if (trace) {
      ingest(trace.dense, "dense");
      ingest(trace.bm25, "bm25");
      ingest(trace.rrf, "rrf");
      ingest(trace.rerank, "rerank");
    }
    return m;
  }, [trace]);

  const runTrace = useCallback(
    async (q?: string) => {
      const query = (q ?? traceQuery).trim();
      if (!query) {
        setTrace(null);
        return;
      }
      setTracing(true);
      try {
        const t = await traceGraphQuery(
          query,
          user?.role === "executive" && lens !== "executive" ? lens : undefined
        );
        setTrace(t);
      } catch (e) {
        toast.error(`Trace failed: ${(e as Error).message}`);
      } finally {
        setTracing(false);
      }
    },
    [traceQuery, user?.role, lens]
  );

  useEffect(() => {
    if (trace) runTrace(trace.query); // re-run when lens changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lens]);

  // Spread the cluster apart so doc labels aren't crowding each other.
  // Stronger repulsion + longer ideal link length = breathable galaxy.
  // Configured via d3Force on the ForceGraph3D ref once nodes are mounted.
  useEffect(() => {
    if (!fgRef.current || nodes.length === 0) return;
    const charge = fgRef.current.d3Force?.("charge");
    if (charge && typeof charge.strength === "function") charge.strength(-220);
    const link = fgRef.current.d3Force?.("link");
    if (link && typeof link.distance === "function") link.distance(45);
    fgRef.current.d3ReheatSimulation?.();
  }, [nodes.length]);

  const isRoleBlocked = useCallback(
    (n: GraphNode) => {
      const lv = n.doc_level ?? 1;
      if (lv > ROLE_LEVEL[lens]) return true;
      if (lens !== "executive" && (n.disabled_for_roles || []).includes(lens)) return true;
      return false;
    },
    [lens]
  );

  const maxHeat = useMemo(
    () => Math.max(1, ...Object.values(heat)),
    [heat]
  );

  const nodeVal = useCallback(
    (n: FGNode) => {
      const baseDoc = n.type === "doc" ? 4 : 1;
      if (!showHeat) return baseDoc;
      const h = heat[n.id] || 0;
      return baseDoc + (h / maxHeat) * 6;
    },
    [heat, maxHeat, showHeat]
  );

  const nodeColor = useCallback(
    (n: FGNode) => {
      const blocked = isRoleBlocked(n);
      const cls = (n.classification || "PUBLIC") as Classification;
      const base = CLASSIFICATION_COLOR[cls];
      // Blocked nodes dim to near-invisible.
      if (blocked) return "rgba(180,180,200,0.12)";
      const hit = traceChunkStage.get(n.id);
      if (hit) return STAGE_COLOR[hit.stage];
      // If in-scope and not traced, mild opacity by heat.
      const h = heat[n.id] || 0;
      if (showHeat && h > 0) {
        return base;
      }
      return n.type === "doc" ? base : shadeForType(base, 0.55);
    },
    [isRoleBlocked, traceChunkStage, heat, showHeat]
  );

  const nodeThreeObject = useCallback(
    (n: FGNode) => {
      const hit = traceChunkStage.get(n.id);
      const blocked = isRoleBlocked(n);
      const color = blocked
        ? new THREE.Color("#c7c7d3")
        : hit
        ? new THREE.Color(STAGE_COLOR[hit.stage])
        : new THREE.Color(
            CLASSIFICATION_COLOR[(n.classification || "PUBLIC") as Classification]
          );
      // Bigger nodes — docs anchor the cluster, chunks orbit around them.
      const radius = n.type === "doc"
        ? Math.max(4.5, Math.sqrt(nodeVal(n)) * 2.6)
        : Math.max(2.2, Math.sqrt(nodeVal(n)) * 1.7);
      const group = new THREE.Group();
      const sphere = new THREE.Mesh(
        new THREE.SphereGeometry(radius, 24, 24),
        new THREE.MeshLambertMaterial({
          color,
          transparent: true,
          opacity: blocked ? 0.18 : hit ? 1 : 0.95,
          emissive: hit ? color : color.clone().multiplyScalar(0.18),
          emissiveIntensity: hit ? 0.85 : 0.18,
        })
      );
      group.add(sphere);

      // Soft outer halo for docs (and for any actively-traced chunk) so
      // they read as "important" against the corporate light canvas.
      if (!blocked && (n.type === "doc" || hit)) {
        const halo = new THREE.Mesh(
          new THREE.SphereGeometry(radius * 1.55, 18, 18),
          new THREE.MeshBasicMaterial({
            color,
            transparent: true,
            opacity: hit ? 0.22 : 0.1,
          })
        );
        group.add(halo);
      }

      // Doc-name label hovering above the sphere — kept compact and
      // readable. Chunk labels are skipped to avoid visual noise; the
      // inspector pane shows their detail on click.
      if (n.type === "doc" && !blocked) {
        const div = document.createElement("div");
        div.textContent = prettifyDocLabel(n.label || "");
        div.style.cssText = [
          "color: #1f2540",
          "font-size: 11px",
          "font-weight: 600",
          "letter-spacing: 0.01em",
          "background: rgba(255,255,255,0.95)",
          "border: 1px solid rgba(60,80,140,0.18)",
          "border-radius: 5px",
          "padding: 3px 7px",
          "white-space: nowrap",
          "pointer-events: none",
          "box-shadow: 0 2px 6px rgba(40,50,90,0.08)",
          "transform: translateY(-6px)",
          "max-width: 220px",
          "overflow: hidden",
          "text-overflow: ellipsis",
        ].join(";");
        const label = new CSS2DObject(div);
        label.position.set(0, radius + 5, 0);
        group.add(label);
      }

      return group;
    },
    [traceChunkStage, isRoleBlocked, nodeVal]
  );

  const linkColor = useCallback(
    (link: any) => {
      const s = typeof link.source === "string" ? link.source : link.source?.id;
      const t = typeof link.target === "string" ? link.target : link.target?.id;
      const blocked = [s, t].some((id) => {
        const n = nodes.find((x) => x.id === id);
        return n && isRoleBlocked(n);
      });
      if (blocked) return "rgba(180,180,200,0.08)";
      return "rgba(100,110,140,0.35)";
    },
    [nodes, isRoleBlocked]
  );

  const counts = useMemo(() => {
    const total = nodes.length;
    const blocked = nodes.filter((n) => isRoleBlocked(n)).length;
    return { total, visible: total - blocked, blocked };
  }, [nodes, isRoleBlocked]);

  const focusOnNode = (n: FGNode) => {
    if (!fgRef.current || !n.x) return;
    const dist = 100;
    const ratio = 1 + dist / Math.hypot(n.x, n.y ?? 0, n.z ?? 0);
    fgRef.current.cameraPosition(
      { x: (n.x || 0) * ratio, y: (n.y || 0) * ratio, z: (n.z || 0) * ratio },
      n,
      1000
    );
  };

  return (
    <div className="h-full flex flex-col overflow-hidden bg-bg">
      {/* Top bar */}
      <div className="px-5 py-3 border-b border-border bg-white/80 backdrop-blur-sm">
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-md bg-accent-soft border border-accent/30 flex items-center justify-center">
              <Sparkles className="w-4 h-4 text-accent" strokeWidth={1.75} />
            </div>
            <div>
              <div className="text-[14px] font-semibold text-fg">
                Knowledge Graph
              </div>
              <div className="text-[10.5px] uppercase tracking-wider text-fg-subtle -mt-0.5">
                Structure · RBAC Lens · Live Retrieval · Heat
              </div>
            </div>
          </div>

          <div className="flex items-center gap-3 flex-wrap">
            {stats && (
              <div className="flex items-center gap-1.5 text-[11px] text-fg-muted">
                <Database className="w-3.5 h-3.5" strokeWidth={1.75} />
                <span>
                  <b className="text-fg font-semibold">{stats.docs}</b> docs · <b className="text-fg font-semibold">{stats.chunks}</b> chunks
                </span>
              </div>
            )}
            <div className="flex items-center gap-1.5 text-[11px] text-fg-muted">
              <span>
                Visible in lens: <b className="text-fg font-semibold">{counts.visible}</b>
                {counts.blocked > 0 && (
                  <>
                    {" "}· hidden{" "}
                    <b className="text-clearance-restricted font-semibold">{counts.blocked}</b>
                  </>
                )}
              </span>
            </div>

            {user?.role === "executive" && (
              <div className="flex items-center gap-1 bg-bg border border-border rounded-md p-0.5">
                <span className="text-[10px] uppercase tracking-wider text-fg-subtle px-2">
                  Lens
                </span>
                {(["guest", "employee", "manager", "executive"] as LensRole[]).map((r) => (
                  <button
                    key={r}
                    onClick={() => setLens(r)}
                    className={cn(
                      "text-[11px] px-2.5 py-1 rounded transition-colors capitalize",
                      lens === r
                        ? "bg-accent text-white font-semibold"
                        : "text-fg-muted hover:text-fg hover:bg-bg-subtle"
                    )}
                  >
                    {r}
                  </button>
                ))}
              </div>
            )}

            <button
              onClick={() => setShowHeat((v) => !v)}
              className={cn(
                "inline-flex items-center gap-1.5 px-2.5 py-1 rounded text-[11px] border transition-colors",
                showHeat
                  ? "border-accent/40 bg-accent-soft text-accent"
                  : "border-border bg-white text-fg-muted hover:text-fg"
              )}
              title="Toggle observability heat (node size = usage)"
            >
              <Flame className="w-3 h-3" strokeWidth={2} />
              Heat
            </button>

            <Link
              to="/app/pipeline"
              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded text-[11px] border border-accent/40 bg-accent text-white font-semibold hover:bg-accent/90 transition-colors shadow-sm"
              title="Open the educational pipeline lab"
            >
              <Cpu className="w-3 h-3" strokeWidth={2.25} />
              Pipeline Lab
              <ArrowUpRight className="w-2.5 h-2.5" strokeWidth={2.5} />
            </Link>
          </div>
        </div>

        {/* Live query bar */}
        <div className="mt-3 flex items-center gap-2">
          <div className="flex-1 relative">
            <input
              type="text"
              value={traceQuery}
              onChange={(e) => setTraceQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") runTrace();
              }}
              placeholder="Type a query to light up the retrieval path…"
              className="w-full px-3 py-2 text-[13px] rounded-md border border-border bg-bg-elevated focus:outline-none focus:border-accent/60"
            />
            {tracing && (
              <div className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] text-accent animate-pulse">
                tracing…
              </div>
            )}
          </div>
          <button
            onClick={() => runTrace()}
            disabled={tracing || !traceQuery.trim()}
            className="px-3 py-2 rounded-md bg-accent text-white text-[12px] font-semibold hover:bg-accent/90 disabled:opacity-50"
          >
            <Zap className="w-3.5 h-3.5 inline -mt-0.5 mr-1" strokeWidth={2.25} /> Trace
          </button>
          {trace && (
            <button
              onClick={() => {
                setTrace(null);
                setTraceQuery("");
              }}
              className="px-3 py-2 rounded-md border border-border text-[12px] text-fg-muted hover:text-fg hover:bg-bg-subtle"
            >
              Clear
            </button>
          )}
        </div>

        {trace && (
          <div className="mt-2 flex items-center gap-3 text-[11px] text-fg-muted flex-wrap">
            <span>
              Role: <b className="text-fg capitalize">{trace.role}</b>
            </span>
            <StageBadge label="Dense" count={trace.dense.length} color={STAGE_COLOR.dense} />
            <StageBadge label="BM25" count={trace.bm25.length} color={STAGE_COLOR.bm25} />
            <StageBadge label="RRF" count={trace.rrf.length} color={STAGE_COLOR.rrf} />
            <StageBadge label="Rerank" count={trace.rerank.length} color={STAGE_COLOR.rerank} />
            <span>
              <Activity className="w-3 h-3 inline -mt-0.5" strokeWidth={2} />{" "}
              <b className="text-fg font-mono">{trace.latency_ms}ms</b>
            </span>
          </div>
        )}

      </div>

      {/* Graph canvas + inspector */}
      <div className="flex-1 flex min-h-0">
        <div
          ref={containerRef}
          className="flex-1 relative overflow-hidden"
          style={{
            background:
              "radial-gradient(ellipse at 50% 30%, #f3f5fc 0%, #eef0f8 45%, #e6e9f4 100%)",
          }}
        >
          {/* Subtle dot grid overlay — corporate observability look */}
          <div
            className="absolute inset-0 pointer-events-none"
            style={{
              backgroundImage:
                "radial-gradient(circle at 1px 1px, rgba(60,80,140,0.12) 1px, transparent 0)",
              backgroundSize: "22px 22px",
              opacity: 0.55,
            }}
          />
          {nodes.length > 0 && dim.w > 0 && (
            <ForceGraph3D
              ref={fgRef}
              width={dim.w}
              height={dim.h}
              graphData={{
                nodes: nodes as any,
                links: edges.map((e) => ({ source: e.source, target: e.target })),
              }}
              backgroundColor="#ffffff00"
              extraRenderers={[new CSS2DRenderer() as any]}
              nodeLabel={(n: any) =>
                `<div style="padding:6px 8px;background:#0b1020;color:white;border-radius:6px;font-size:11px">
                  <b>${
                    (n as FGNode).type === "doc"
                      ? prettifyDocLabel((n as FGNode).label || "")
                      : (n as FGNode).label
                  }</b><br/>
                  ${(n as FGNode).type === "doc"
                    ? `L${(n as FGNode).doc_level} ${(n as FGNode).classification}`
                    : `chunk ${(n as FGNode).chunk_index ?? ""}`}
                </div>`
              }
              nodeThreeObject={nodeThreeObject as any}
              nodeColor={nodeColor as any}
              nodeVal={nodeVal as any}
              linkColor={linkColor as any}
              linkOpacity={0.55}
              linkWidth={0.9}
              onNodeClick={(n: any) => {
                setSelected(n as FGNode);
                focusOnNode(n as FGNode);
              }}
              cooldownTicks={220}
              warmupTicks={80}
              d3AlphaDecay={0.012}
              d3VelocityDecay={0.32}
              onEngineStop={() => {
                // Pull the camera in once the layout settles so the cluster
                // fills the viewport instead of looking like distant dots.
                if (fgRef.current) {
                  fgRef.current.zoomToFit(900, 100);
                }
              }}
            />
          )}

          {/* Legend */}
          <div className="absolute bottom-3 left-3 bg-white/95 backdrop-blur rounded-md border border-border shadow-sm px-3 py-2.5 text-[10.5px] text-fg-muted">
            <div className="font-semibold text-fg-subtle uppercase tracking-wider mb-1.5 text-[9.5px]">
              Classification
            </div>
            {(["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"] as Classification[]).map(
              (c) => (
                <div key={c} className="flex items-center gap-1.5 mb-0.5">
                  <span
                    className="w-2.5 h-2.5 rounded-full"
                    style={{ background: CLASSIFICATION_COLOR[c] }}
                  />
                  {c}
                </div>
              )
            )}
            {trace && (
              <>
                <div className="font-semibold text-fg-subtle uppercase tracking-wider mt-2 mb-1.5 text-[9.5px]">
                  Retrieval stage
                </div>
                {(["dense", "bm25", "rrf", "rerank"] as Stage[]).map((s) => (
                  <div key={s} className="flex items-center gap-1.5 mb-0.5">
                    <span
                      className="w-2.5 h-2.5 rounded-full shadow-[0_0_6px_currentColor]"
                      style={{ background: STAGE_COLOR[s], color: STAGE_COLOR[s] }}
                    />
                    <span className="capitalize">{s}</span>
                  </div>
                ))}
              </>
            )}
          </div>
        </div>

        {/* Right inspector */}
        <aside className="w-80 shrink-0 border-l border-border bg-white overflow-y-auto p-4 space-y-4 text-[12.5px]">
          {selected ? (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-fg-subtle font-semibold">
                {selected.type === "doc" ? "Document" : "Chunk"}
              </div>
              <div className="text-[14px] font-semibold text-fg mt-1 break-words">
                {selected.label}
              </div>
              <div className="flex items-center gap-1.5 mt-2 flex-wrap">
                <span
                  className="text-[10px] px-1.5 py-0.5 rounded font-semibold"
                  style={{
                    background: `${CLASSIFICATION_COLOR[(selected.classification || "PUBLIC") as Classification]}22`,
                    color: CLASSIFICATION_COLOR[(selected.classification || "PUBLIC") as Classification],
                  }}
                >
                  L{selected.doc_level} · {selected.classification}
                </span>
                {selected.disabled_for_roles?.length ? (
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-clearance-restricted/10 text-clearance-restricted font-semibold inline-flex items-center gap-1">
                    <EyeOff className="w-2.5 h-2.5" />
                    Hidden from {selected.disabled_for_roles.join(", ")}
                  </span>
                ) : null}
                {heat[selected.id] > 0 && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-accent-soft text-accent font-semibold inline-flex items-center gap-1">
                    <Flame className="w-2.5 h-2.5" />
                    {heat[selected.id]} {selected.type === "doc" ? "queries" : "citations"}
                  </span>
                )}
              </div>
              {selected.uploaded_by_username && (
                <div className="text-[11px] text-fg-muted mt-2">
                  Uploaded by{" "}
                  <b className="text-fg capitalize">
                    {selected.uploaded_by_username} · {selected.uploaded_by_role}
                  </b>
                </div>
              )}
              {selected.text_preview && (
                <div className="mt-3 p-2 rounded bg-bg-subtle border border-border text-[11.5px] leading-relaxed font-mono whitespace-pre-wrap">
                  {selected.text_preview}
                  {selected.text_preview.length >= 240 && "…"}
                </div>
              )}
              {traceChunkStage.get(selected.id) && (
                <div className="mt-3 p-2 rounded border border-accent/30 bg-accent-soft text-[11px]">
                  <div className="font-semibold text-accent uppercase tracking-wider text-[9.5px] mb-0.5">
                    In current trace
                  </div>
                  Stage:{" "}
                  <b className="capitalize">
                    {traceChunkStage.get(selected.id)?.stage}
                  </b>{" "}
                  · score{" "}
                  <span className="font-mono">
                    {traceChunkStage.get(selected.id)?.score.toFixed(3)}
                  </span>
                </div>
              )}
            </div>
          ) : (
            <InspectorEmpty />
          )}
        </aside>
      </div>
    </div>
  );
}

function StageBadge({
  label,
  count,
  color,
}: {
  label: string;
  count: number;
  color: string;
}) {
  return (
    <span
      className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-semibold"
      style={{ background: `${color}22`, color }}
    >
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: color }} />
      {label} · {count}
    </span>
  );
}

function InspectorEmpty() {
  return (
    <div className="space-y-3 text-fg-muted text-[11.5px] leading-relaxed">
      <div className="flex items-center gap-2 font-semibold text-fg text-[12.5px]">
        <Layers className="w-4 h-4" strokeWidth={1.75} />
        How to read this
      </div>
      <ul className="space-y-2 pl-1">
        <li>
          <span className="font-semibold text-fg">Dots</span> — documents (big) and
          chunks (small), coloured by clearance level.
        </li>
        <li>
          <span className="font-semibold text-fg">RBAC Lens</span> — switch roles at
          top; nodes above that role's clearance fade to ghost.
        </li>
        <li>
          <span className="font-semibold text-fg">Live trace</span> — type a query and
          the dots light up by pipeline stage: dense → BM25 → RRF → rerank.
        </li>
        <li>
          <span className="font-semibold text-fg">Heat</span> — node size grows with
          real-world retrieval + citation count from your audit log.
        </li>
        <li>
          <span className="font-semibold text-fg">Click any node</span> — inspector
          shows the doc or chunk text, uploader, classification, and current trace.
        </li>
      </ul>
      <div className="flex items-center gap-1.5 text-[10.5px] text-fg-subtle pt-1 border-t border-border mt-3">
        <ShieldCheck className="w-3 h-3" strokeWidth={1.75} />
        RBAC is enforced server-side — the Lens is pure visualization.
      </div>
    </div>
  );
}

function shadeForType(hex: string, opacity: number) {
  // hex '#rrggbb' to rgba
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${opacity})`;
}

// Cleans the raw filename into a label that reads well in the canvas:
// strips file extension, drops the redundant "TechNova_" prefix
// (every doc here is TechNova's), turns underscores/dashes into spaces,
// and truncates very long names to 36 chars with an ellipsis.
function prettifyDocLabel(filename: string): string {
  let s = filename.replace(/\.[a-z0-9]+$/i, "");
  s = s.replace(/^TechNova[_\- ]+/i, "");
  s = s.replace(/[_\-]+/g, " ").trim();
  if (s.length > 36) s = s.slice(0, 33) + "…";
  return s || filename;
}
