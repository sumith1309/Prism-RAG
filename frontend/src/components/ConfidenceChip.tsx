import { motion } from "framer-motion";
import { AlertTriangle, CheckCircle2, ShieldCheck, Sparkles, Zap } from "lucide-react";

import { cn } from "@/lib/utils";

/** 0..100 composite confidence from (top rerank score + LLM faithfulness).
 * Renders inline with the answer metadata so the user gets an at-a-glance
 * read on "should I trust this answer?" without needing to open the trace.
 *
 * Bands:
 *   >= 80  "High confidence"  — green, check icon
 *   60-79  "Confident"        — blue, shield icon
 *   40-59  "Limited"          — amber, warn icon + "Broaden" button
 *   <  40  "Low"              — red, warn icon + "Broaden" button + note
 */
export function ConfidenceChip({
  value,
  onBroaden,
}: {
  value: number;
  onBroaden?: () => void;
}) {
  const band = getBand(value);
  const canBroaden = value < 60 && !!onBroaden;

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.96 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.2 }}
      className={cn(
        "inline-flex items-center gap-2 rounded-full border pl-1 pr-2.5 py-[3px]",
        band.ring
      )}
      title={`Confidence ${value}/100 — ${band.hint}`}
    >
      <span
        className={cn(
          "w-5 h-5 rounded-full flex items-center justify-center",
          band.iconBg
        )}
      >
        <band.Icon className={cn("w-3 h-3", band.iconColor)} strokeWidth={2.25} />
      </span>
      <span className={cn("text-[11px] font-semibold leading-none", band.label)}>
        {band.title}
      </span>
      <span className="text-[10.5px] font-mono tabular-nums text-fg-subtle leading-none">
        {value}
      </span>
      {canBroaden && (
        <button
          onClick={onBroaden}
          className="ml-1 inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full border border-accent/40 bg-accent/10 text-[10px] font-semibold text-accent hover:bg-accent hover:text-white transition-colors"
          title="Re-run with multi-query fan-out for broader retrieval"
        >
          <Zap className="w-2.5 h-2.5" strokeWidth={2.5} />
          Broaden
        </button>
      )}
    </motion.div>
  );
}

function getBand(v: number) {
  if (v >= 80) {
    return {
      title: "High confidence",
      hint: "strong retrieval + grounded answer",
      Icon: CheckCircle2,
      iconBg: "bg-clearance-public/15",
      iconColor: "text-clearance-public",
      ring: "border-clearance-public/40 bg-clearance-public/5",
      label: "text-clearance-public",
    };
  }
  if (v >= 60) {
    return {
      title: "Confident",
      hint: "reasonable match; answer is grounded",
      Icon: ShieldCheck,
      iconBg: "bg-accent/15",
      iconColor: "text-accent",
      ring: "border-accent/30 bg-accent-soft",
      label: "text-accent",
    };
  }
  if (v >= 40) {
    return {
      title: "Limited confidence",
      hint: "partial retrieval match — consider broadening",
      Icon: Sparkles,
      iconBg: "bg-clearance-confidential/20",
      iconColor: "text-clearance-confidential",
      ring: "border-clearance-confidential/40 bg-clearance-confidential/10",
      label: "text-clearance-confidential",
    };
  }
  return {
    title: "Low confidence",
    hint: "weak match — strongly consider broadening or rephrasing",
    Icon: AlertTriangle,
    iconBg: "bg-clearance-restricted/15",
    iconColor: "text-clearance-restricted",
    ring: "border-clearance-restricted/40 bg-clearance-restricted/5",
    label: "text-clearance-restricted",
  };
}
