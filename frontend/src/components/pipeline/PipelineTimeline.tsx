import { useEffect, useRef } from "react";
import { gsap } from "@/lib/gsap";

/**
 * Master GSAP timeline controller for the Pipeline Lab. Orchestrates
 * the entire 7-stage choreography as SSE events arrive:
 *
 *   embed → dense → bm25 → rrf → rerank → generate → done
 *
 * Each stage triggers:
 *   1. Progress bar segment fills with eased color
 *   2. Stage node in the System Flow pulses
 *   3. Connecting edge lights up with particle flow
 *   4. Stage card reveals with StageReveal
 *   5. Numbers count up in the card
 *
 * Usage in PipelinePage:
 *   const { triggerStage, reset } = usePipelineTimeline();
 *   // On SSE event:
 *   triggerStage("dense");
 */

export type PipelineStage =
  | "idle"
  | "embed"
  | "dense"
  | "bm25"
  | "rrf"
  | "rerank"
  | "generate"
  | "done";

const STAGE_ORDER: PipelineStage[] = [
  "embed",
  "dense",
  "bm25",
  "rrf",
  "rerank",
  "generate",
  "done",
];

const STAGE_COLORS: Record<PipelineStage, string> = {
  idle: "#94a3b8",
  embed: "#6366f1",   // indigo
  dense: "#3b82f6",   // blue
  bm25: "#f97316",    // orange
  rrf: "#a855f7",     // purple
  rerank: "#facc15",  // yellow
  generate: "#22c55e", // green
  done: "#14b8a6",    // teal
};

export function usePipelineTimeline() {
  const currentStageRef = useRef<PipelineStage>("idle");
  const timelineRef = useRef<gsap.core.Timeline | null>(null);

  const triggerStage = (stage: PipelineStage) => {
    currentStageRef.current = stage;
    const idx = STAGE_ORDER.indexOf(stage);
    if (idx < 0) return;

    // Animate the progress bar segment for this stage.
    const progressEl = document.querySelector(
      `[data-pipeline-progress="${stage}"]`
    );
    if (progressEl) {
      gsap.fromTo(
        progressEl,
        { scaleX: 0, opacity: 0.6 },
        {
          scaleX: 1,
          opacity: 1,
          duration: 0.6,
          ease: "power2.out",
          transformOrigin: "left center",
          backgroundColor: STAGE_COLORS[stage],
        }
      );
    }

    // Pulse the stage node in the System Flow SVG.
    const nodeEl = document.querySelector(
      `[data-pipeline-node="${stage}"]`
    );
    if (nodeEl) {
      gsap.timeline()
        .to(nodeEl, {
          scale: 1.15,
          duration: 0.25,
          ease: "power2.out",
          transformOrigin: "center center",
        })
        .to(nodeEl, {
          scale: 1,
          duration: 0.4,
          ease: "elastic.out(1, 0.5)",
        })
        .to(
          nodeEl,
          {
            filter: `drop-shadow(0 0 8px ${STAGE_COLORS[stage]}88)`,
            duration: 0.3,
          },
          0
        );
    }

    // Pulse the stage label/badge.
    const badgeEl = document.querySelector(
      `[data-pipeline-badge="${stage}"]`
    );
    if (badgeEl) {
      gsap.fromTo(
        badgeEl,
        { scale: 0.8, opacity: 0 },
        {
          scale: 1,
          opacity: 1,
          duration: 0.4,
          ease: "back.out(2)",
        }
      );
    }
  };

  const reset = () => {
    currentStageRef.current = "idle";
    timelineRef.current?.kill();

    // Reset all progress bars.
    document.querySelectorAll("[data-pipeline-progress]").forEach((el) => {
      gsap.set(el, { scaleX: 0, opacity: 0.6 });
    });

    // Reset all node highlights.
    document.querySelectorAll("[data-pipeline-node]").forEach((el) => {
      gsap.set(el, { scale: 1, filter: "none" });
    });

    // Reset all badges.
    document.querySelectorAll("[data-pipeline-badge]").forEach((el) => {
      gsap.set(el, { scale: 0.8, opacity: 0 });
    });
  };

  // Cleanup on unmount.
  useEffect(() => {
    return () => {
      timelineRef.current?.kill();
    };
  }, []);

  return {
    triggerStage,
    reset,
    currentStage: currentStageRef,
    stageColors: STAGE_COLORS,
    stageOrder: STAGE_ORDER,
  };
}

/**
 * Visual progress bar component — renders one colored segment per
 * pipeline stage. Each segment has a `data-pipeline-progress` attribute
 * that the timeline controller targets.
 */
export function PipelineProgressBar({
  stages = STAGE_ORDER.filter((s) => s !== "done"),
}: {
  stages?: PipelineStage[];
}) {
  return (
    <div className="flex items-center gap-1 w-full h-2 rounded-full bg-bg-subtle overflow-hidden border border-border">
      {stages.map((stage) => (
        <div
          key={stage}
          data-pipeline-progress={stage}
          className="flex-1 h-full rounded-full"
          style={{
            backgroundColor: STAGE_COLORS[stage],
            transform: "scaleX(0)",
            transformOrigin: "left center",
            opacity: 0.6,
          }}
        />
      ))}
    </div>
  );
}

/**
 * Stage label badges — small pills showing the stage name with a
 * latency counter. Animated in by the timeline controller.
 */
export function StageBadge({
  stage,
  label,
  latencyMs,
  active,
}: {
  stage: PipelineStage;
  label: string;
  latencyMs?: number;
  active: boolean;
}) {
  return (
    <div
      data-pipeline-badge={stage}
      className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold border transition-colors"
      style={{
        borderColor: active ? `${STAGE_COLORS[stage]}66` : "#e5e5ea",
        backgroundColor: active ? `${STAGE_COLORS[stage]}15` : "white",
        color: active ? STAGE_COLORS[stage] : "#8e8e93",
        opacity: 0,
        transform: "scale(0.8)",
      }}
    >
      <span
        className="w-2 h-2 rounded-full"
        style={{ backgroundColor: STAGE_COLORS[stage] }}
      />
      {label}
      {latencyMs !== undefined && (
        <span className="font-mono text-[10px] opacity-70">
          {latencyMs}ms
        </span>
      )}
    </div>
  );
}
