import { motion } from "framer-motion";
import { cn } from "@/lib/utils";

/**
 * Animated RAG pipeline diagram. Query flows left → right through 5 stages,
 * each with its own icon node, connected by beams that pulse a light streak.
 * Each node has a delay so the animation reads as a progressive flow.
 */
export function AnimatedBeamPipeline({
  active,
  className,
}: {
  active?: number; // which stage is "live" (0..4); if undefined, loop
  className?: string;
}) {
  // A simple SVG-free DOM layout so we don't fight alignment math.
  const nodes = [
    { label: "Query", hint: "User input", color: "bg-light-accent" },
    { label: "Dense + BM25", hint: "Hybrid retrieval", color: "bg-clearance-internal" },
    { label: "RRF", hint: "Fusion (k=60)", color: "bg-clearance-internal" },
    { label: "Rerank", hint: "Cross-encoder", color: "bg-clearance-confidential" },
    { label: "LLM", hint: "Grounded answer", color: "bg-clearance-public" },
  ];

  return (
    <div
      className={cn(
        "relative w-full grid grid-cols-[auto_1fr_auto_1fr_auto_1fr_auto_1fr_auto] items-center gap-0",
        className
      )}
    >
      {nodes.map((n, i) => (
        <div key={n.label} style={{ gridColumn: 2 * i + 1 }} className="flex flex-col items-center gap-1.5">
          <motion.div
            initial={{ scale: 0.8, opacity: 0 }}
            whileInView={{ scale: 1, opacity: 1 }}
            viewport={{ once: true, margin: "-40px" }}
            transition={{ delay: i * 0.12, duration: 0.4, ease: "easeOut" }}
            className={cn(
              "w-12 h-12 rounded-xl border border-light-border shadow-light-card bg-white flex items-center justify-center relative",
              active === i && "ring-2 ring-offset-2 ring-light-accent ring-offset-light-bg"
            )}
          >
            <div className={cn("w-2 h-2 rounded-full", n.color)} />
            {active === i && (
              <motion.span
                className={cn("absolute inset-0 rounded-xl", n.color, "opacity-30")}
                animate={{ scale: [1, 1.35, 1], opacity: [0.3, 0, 0.3] }}
                transition={{ duration: 1.4, repeat: Infinity }}
              />
            )}
          </motion.div>
          <div className="text-center">
            <div className="text-[11px] font-semibold text-light-fg leading-tight">{n.label}</div>
            <div className="text-[10px] text-light-fgSubtle leading-tight">{n.hint}</div>
          </div>
        </div>
      ))}

      {/* beams between nodes */}
      {nodes.slice(0, -1).map((_, i) => (
        <div
          key={`beam-${i}`}
          style={{ gridColumn: 2 * i + 2, gridRow: 1 }}
          className="relative h-0.5 self-center mt-[-18px] overflow-hidden bg-light-border"
        >
          <motion.div
            className="absolute inset-y-0 left-0 w-16 bg-gradient-to-r from-transparent via-light-accent to-transparent"
            initial={{ x: "-100%" }}
            whileInView={{ x: "200%" }}
            viewport={{ once: false, margin: "-40px" }}
            transition={{
              delay: i * 0.25,
              duration: 1.8,
              repeat: Infinity,
              repeatDelay: 1.2,
              ease: "linear",
            }}
          />
        </div>
      ))}
    </div>
  );
}
