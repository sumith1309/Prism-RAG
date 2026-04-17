/**
 * PipelineArchitecture — The "living machine" view of the RAG system.
 *
 * TWO MODES:
 *   Idle  → interactive architecture diagram. Every node is explorable.
 *           User understands the system before typing a query.
 *   Live  → the SAME diagram animates with real data flowing through it.
 *           Particles pulse along edges, nodes spotlight in sequence,
 *           real data appears inside each node as the SSE events arrive.
 *
 * DESIGN RULES:
 *   - Zero jargon on screen. The animation IS the explanation.
 *   - Grandmother test: anyone watching should understand the FLOW
 *     even if they don't understand the math.
 *   - Each node shows what it DOES, not what it IS.
 */
import { useEffect, useRef, type ReactNode } from "react";
import {
  Binary,
  BookOpen,
  Database,
  Filter,
  Gauge,
  Layers,
  MessageSquare,
  Search,
  Sparkles,
  Wand2,
  Zap,
} from "lucide-react";

import { gsap } from "@/lib/gsap";
import { cn } from "@/lib/utils";
import { CountUp } from "./CountUp";

// ─── Types ──────────────────────────────────────────────────────────────────

type Step =
  | "idle"
  | "embed"
  | "dense"
  | "bm25"
  | "rrf"
  | "rerank"
  | "generate"
  | "judge"
  | "done"
  | "error";

interface NodeData {
  embedMs?: number;
  embedModel?: string;
  embedDim?: number;
  denseCount?: number;
  denseMs?: number;
  bm25Count?: number;
  bm25Ms?: number;
  rrfCount?: number;
  rrfMs?: number;
  rerankCount?: number;
  rerankMs?: number;
  rerankModel?: string;
  answer?: string;
  generateMs?: number;
  generateModel?: string;
  faithfulness?: number;
  totalMs?: number;
}

// ─── Stage config ───────────────────────────────────────────────────────────

const STAGES = [
  {
    id: "query",
    label: "Your Question",
    desc: "enters the system",
    icon: MessageSquare,
    color: "#1d1d1f",
  },
  {
    id: "embed",
    label: "Embed",
    desc: "words → numbers",
    descActive: "Converting to 384 numbers...",
    icon: Binary,
    color: "#6366f1",
  },
  {
    id: "dense",
    label: "Vector Search",
    desc: "find by meaning",
    descActive: "Searching by meaning...",
    icon: Database,
    color: "#3b82f6",
  },
  {
    id: "bm25",
    label: "Keyword Search",
    desc: "find exact words",
    descActive: "Matching exact words...",
    icon: Search,
    color: "#f97316",
  },
  {
    id: "rrf",
    label: "Merge Results",
    desc: "combine both lists",
    descActive: "Fusing rankings...",
    icon: Layers,
    color: "#a855f7",
  },
  {
    id: "rerank",
    label: "Re-score",
    desc: "precision pass",
    descActive: "AI re-scoring for precision...",
    icon: Wand2,
    color: "#f59e0b",
  },
  {
    id: "generate",
    label: "Write Answer",
    desc: "cite the sources",
    descActive: "Writing grounded answer...",
    icon: BookOpen,
    color: "#22c55e",
  },
  {
    id: "judge",
    label: "Fact-Check",
    desc: "verify faithfulness",
    descActive: "Checking every claim...",
    icon: Gauge,
    color: "#ef4444",
  },
] as const;

type StageId = (typeof STAGES)[number]["id"];

const STAGE_INDEX = Object.fromEntries(
  STAGES.map((s, i) => [s.id, i])
) as Record<StageId, number>;

// Map step to a stage id.
function stepToStageId(step: Step): StageId | null {
  if (step === "idle" || step === "error") return null;
  if (step === "done") return "judge";
  return step as StageId;
}

// ─── Edge definitions (which nodes connect) ─────────────────────────────────

const EDGES: [StageId, StageId][] = [
  ["query", "embed"],
  ["embed", "dense"],
  ["embed", "bm25"],
  ["dense", "rrf"],
  ["bm25", "rrf"],
  ["rrf", "rerank"],
  ["rerank", "generate"],
  ["generate", "judge"],
];

// ─── Main component ────────────────────────────────────────────────────────

export function PipelineArchitecture({
  step,
  data,
  query,
}: {
  step: Step;
  data: NodeData;
  query: string;
}) {
  const isRunning = step !== "idle" && step !== "error";
  const activeId = stepToStageId(step);
  const activeIdx = activeId ? STAGE_INDEX[activeId] : -1;

  return (
    <div className="w-full py-6">
      {/* Flow layout: vertical on mobile, styled flow on desktop */}
      <div className="relative max-w-4xl mx-auto">
        {/* Edges — drawn as connecting lines behind nodes */}
        <svg
          className="absolute inset-0 w-full h-full pointer-events-none z-0"
          preserveAspectRatio="none"
        >
          {/* Edges will be drawn via CSS — SVG is placeholder for MotionPath */}
        </svg>

        {/* Nodes */}
        <div className="relative z-10 flex flex-col items-center gap-0">
          {/* Query node */}
          <ArchNode
            stage={STAGES[0]}
            state={isRunning ? "completed" : "idle"}
            isFirst
          >
            {isRunning && query && (
              <div className="mt-2 px-3 py-1.5 rounded-md bg-accent/10 border border-accent/20 text-[12.5px] text-fg max-w-sm truncate text-center">
                "{query}"
              </div>
            )}
          </ArchNode>

          <EdgeLine active={activeIdx >= 1} color={STAGES[1].color} />

          {/* Embed */}
          <ArchNode
            stage={STAGES[1]}
            state={nodeState("embed", step, activeIdx)}
          >
            {(step === "embed" || activeIdx > 1) && data.embedMs != null && (
              <NodeMetric
                label="Vector dimensions"
                value={data.embedDim || 384}
                suffix="d"
                ms={data.embedMs}
              />
            )}
          </ArchNode>

          <EdgeLine active={activeIdx >= 2} color={STAGES[2].color} />

          {/* Dense + BM25 (parallel) */}
          <div className="flex items-start gap-4 w-full max-w-2xl justify-center">
            <div className="flex-1 max-w-xs">
              <ArchNode
                stage={STAGES[2]}
                state={nodeState("dense", step, activeIdx)}
              >
                {activeIdx >= 2 && data.denseCount != null && (
                  <NodeMetric
                    label="Chunks found"
                    value={data.denseCount}
                    suffix=" hits"
                    ms={data.denseMs}
                  />
                )}
              </ArchNode>
            </div>
            <div className="flex flex-col items-center justify-center pt-8">
              <div className="w-px h-8 bg-border" />
              <div className="text-[9px] uppercase tracking-wider text-fg-subtle font-bold px-2 py-1 rounded-full bg-bg-subtle border border-border">
                parallel
              </div>
              <div className="w-px h-8 bg-border" />
            </div>
            <div className="flex-1 max-w-xs">
              <ArchNode
                stage={STAGES[3]}
                state={nodeState("bm25", step, activeIdx)}
              >
                {activeIdx >= 3 && data.bm25Count != null && (
                  <NodeMetric
                    label="Chunks found"
                    value={data.bm25Count}
                    suffix=" hits"
                    ms={data.bm25Ms}
                  />
                )}
              </ArchNode>
            </div>
          </div>

          {/* Merge arrows */}
          <div className="flex items-center gap-2 my-1">
            <div className="w-16 h-px bg-border" />
            <Zap
              className={cn(
                "w-4 h-4 transition-colors",
                activeIdx >= 4 ? "text-purple-500" : "text-fg-subtle"
              )}
              strokeWidth={2}
            />
            <div className="w-16 h-px bg-border" />
          </div>

          {/* RRF */}
          <ArchNode
            stage={STAGES[4]}
            state={nodeState("rrf", step, activeIdx)}
          >
            {activeIdx >= 4 && data.rrfCount != null && (
              <NodeMetric
                label="Fused results"
                value={data.rrfCount}
                suffix=" chunks"
                ms={data.rrfMs}
              />
            )}
          </ArchNode>

          <EdgeLine active={activeIdx >= 5} color={STAGES[5].color} />

          {/* Rerank */}
          <ArchNode
            stage={STAGES[5]}
            state={nodeState("rerank", step, activeIdx)}
          >
            {activeIdx >= 5 && data.rerankCount != null && (
              <NodeMetric
                label="Best matches"
                value={data.rerankCount}
                suffix={` of ${data.rrfCount || "?"}`}
                ms={data.rerankMs}
              />
            )}
          </ArchNode>

          <EdgeLine active={activeIdx >= 6} color={STAGES[6].color} />

          {/* Generate */}
          <ArchNode
            stage={STAGES[6]}
            state={nodeState("generate", step, activeIdx)}
          >
            {(step === "generate" || step === "judge" || step === "done") &&
              data.answer && (
                <div className="mt-2 rounded-md border border-emerald-200 bg-emerald-50/60 px-3 py-2 text-[12px] leading-relaxed text-fg max-h-24 overflow-hidden relative">
                  {data.answer.slice(0, 200)}
                  {data.answer.length > 200 && "..."}
                  {step === "generate" && (
                    <span className="inline-block w-1.5 h-3 bg-emerald-500/80 ml-0.5 align-middle animate-pulse" />
                  )}
                </div>
              )}
          </ArchNode>

          <EdgeLine active={activeIdx >= 7} color={STAGES[7].color} />

          {/* Judge */}
          <ArchNode
            stage={STAGES[7]}
            state={nodeState("judge", step, activeIdx)}
          >
            {step === "done" && data.faithfulness != null && data.faithfulness >= 0 && (
              <div className="mt-2 flex items-center justify-center gap-3">
                <div
                  className={cn(
                    "text-[22px] font-bold",
                    data.faithfulness >= 0.8
                      ? "text-emerald-500"
                      : data.faithfulness >= 0.5
                      ? "text-amber-500"
                      : "text-red-500"
                  )}
                >
                  <CountUp
                    value={Math.round(data.faithfulness * 100)}
                    suffix="%"
                    duration={1}
                    className="font-mono"
                  />
                </div>
                <span className="text-[11px] text-fg-muted">faithful</span>
              </div>
            )}
          </ArchNode>

          {/* Final result */}
          {step === "done" && data.totalMs != null && (
            <div className="mt-4 flex items-center justify-center gap-2">
              <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-emerald-50 border border-emerald-200 text-[13px] font-semibold text-emerald-700">
                <Sparkles className="w-4 h-4" strokeWidth={2} />
                Answer delivered in{" "}
                <CountUp
                  value={data.totalMs / 1000}
                  decimals={1}
                  suffix="s"
                  duration={0.8}
                  className="font-mono"
                />
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Helpers ────────────────────────────────────────────────────────────────

function nodeState(
  id: string,
  step: Step,
  activeIdx: number
): "idle" | "active" | "completed" {
  const idx = STAGE_INDEX[id as StageId];
  if (idx === undefined) return "idle";
  if (step === "idle") return "idle";
  if (idx === activeIdx) return "active";
  if (idx < activeIdx) return "completed";
  return "idle";
}

// ─── Architecture Node ──────────────────────────────────────────────────────

function ArchNode({
  stage,
  state,
  isFirst,
  children,
}: {
  stage: (typeof STAGES)[number];
  state: "idle" | "active" | "completed";
  isFirst?: boolean;
  children?: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const Icon = stage.icon;

  useEffect(() => {
    if (!ref.current) return;
    const el = ref.current;

    if (state === "active") {
      gsap
        .timeline()
        .to(el, {
          scale: 1.04,
          duration: 0.4,
          ease: "back.out(1.7)",
        })
        .to(
          el,
          {
            boxShadow: `0 0 24px ${stage.color}30, 0 4px 20px rgba(0,0,0,0.06)`,
            borderColor: `${stage.color}60`,
            duration: 0.3,
          },
          "-=0.2"
        );
    } else if (state === "completed") {
      gsap.to(el, {
        scale: 1,
        opacity: 1,
        boxShadow: `0 0 0px transparent, 0 2px 8px rgba(0,0,0,0.04)`,
        borderColor: `${stage.color}30`,
        duration: 0.35,
      });
    } else {
      gsap.to(el, {
        scale: 1,
        opacity: 0.7,
        boxShadow: "none",
        borderColor: "#e5e5ea",
        duration: 0.3,
      });
    }
  }, [state, stage.color]);

  return (
    <div
      ref={ref}
      className={cn(
        "w-full max-w-sm rounded-xl border bg-white px-4 py-3 transition-none will-change-transform",
        state === "active" && "z-10"
      )}
      style={{ opacity: state === "idle" ? 0.7 : 1 }}
    >
      <div className="flex items-center gap-3">
        <div
          className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0 border"
          style={{
            background: `${stage.color}12`,
            borderColor: `${stage.color}30`,
          }}
        >
          <Icon
            className="w-5 h-5"
            strokeWidth={1.75}
            style={{ color: stage.color }}
          />
        </div>
        <div className="min-w-0">
          <div className="text-[14px] font-semibold text-fg">
            {stage.label}
          </div>
          <div className="text-[11.5px] text-fg-muted">
            {state === "active" && "descActive" in stage
              ? (stage as any).descActive
              : stage.desc}
          </div>
        </div>
        {state === "active" && (
          <div className="ml-auto shrink-0">
            <div className="w-5 h-5 rounded-full border-2 border-t-transparent animate-spin"
              style={{ borderColor: `${stage.color}40`, borderTopColor: stage.color }}
            />
          </div>
        )}
        {state === "completed" && (
          <div
            className="ml-auto w-6 h-6 rounded-full flex items-center justify-center shrink-0"
            style={{ background: `${stage.color}18` }}
          >
            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke={stage.color} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="20 6 9 17 4 12" />
            </svg>
          </div>
        )}
      </div>
      {children}
    </div>
  );
}

// ─── Edge Line ──────────────────────────────────────────────────────────────

function EdgeLine({ active, color }: { active: boolean; color: string }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;
    if (active) {
      gsap.fromTo(
        ref.current,
        { scaleY: 0, opacity: 0 },
        {
          scaleY: 1,
          opacity: 1,
          duration: 0.4,
          ease: "power2.out",
          transformOrigin: "top center",
        }
      );
      // Pulse the dot
      const dot = ref.current.querySelector(".edge-dot");
      if (dot) {
        gsap.fromTo(
          dot,
          { scale: 0, opacity: 0 },
          {
            scale: 1,
            opacity: 1,
            duration: 0.3,
            ease: "back.out(3)",
            delay: 0.2,
          }
        );
      }
    }
  }, [active]);

  return (
    <div
      ref={ref}
      className="flex flex-col items-center my-1"
      style={{ opacity: active ? 1 : 0.3 }}
    >
      <div
        className="w-0.5 h-6 rounded-full"
        style={{ backgroundColor: active ? color : "#d2d2d7" }}
      />
      <div
        className="edge-dot w-2 h-2 rounded-full"
        style={{
          backgroundColor: active ? color : "#d2d2d7",
          boxShadow: active ? `0 0 8px ${color}60` : "none",
          opacity: 0,
        }}
      />
      <div
        className="w-0.5 h-6 rounded-full"
        style={{ backgroundColor: active ? color : "#d2d2d7" }}
      />
    </div>
  );
}

// ─── Node Metric ────────────────────────────────────────────────────────────

function NodeMetric({
  label,
  value,
  suffix = "",
  ms,
}: {
  label: string;
  value: number;
  suffix?: string;
  ms?: number;
}) {
  return (
    <div className="mt-2 flex items-center justify-between gap-3 px-1">
      <div className="text-[11px] text-fg-muted">{label}</div>
      <div className="flex items-center gap-2">
        <CountUp
          value={value}
          suffix={suffix}
          duration={0.7}
          className="text-[13px] font-semibold font-mono text-fg"
        />
        {ms != null && ms > 0 && (
          <CountUp
            value={ms}
            suffix="ms"
            duration={0.5}
            className="text-[10.5px] font-mono text-fg-subtle"
          />
        )}
      </div>
    </div>
  );
}
