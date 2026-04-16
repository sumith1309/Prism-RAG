import { motion } from "framer-motion";
import { AlertCircle, BadgeCheck } from "lucide-react";

import { cn } from "@/lib/utils";

/** Tier 1.1 — visible warning chip when the LLM cited [Source N] tags
 * that don't actually point to a chunk in the sources, OR cited
 * sources whose text has no substantive overlap with the cited
 * sentence. Catches a class of hallucinations that the faithfulness
 * judge can miss (the judge looks at the answer-vs-sources blend, not
 * per-citation accuracy).
 *
 * Hidden when all citations are valid — no clutter on clean answers.
 */
export function CitationCheckChip({
  check,
}: {
  check: {
    total: number;
    valid: number;
    fabricated: number[];
    weak: number[];
    score: number;
  };
}) {
  if (check.total === 0) return null;
  const allClean = check.fabricated.length === 0 && check.weak.length === 0;

  if (allClean) {
    return (
      <motion.div
        initial={{ opacity: 0, scale: 0.96 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.2 }}
        className="inline-flex items-center gap-1.5 rounded-full border border-clearance-public/30 bg-clearance-public/5 pl-1 pr-2.5 py-[3px]"
        title={`All ${check.total} citations verified against source chunks`}
      >
        <BadgeCheck
          className="w-3.5 h-3.5 text-clearance-public"
          strokeWidth={2.25}
        />
        <span className="text-[11px] font-semibold text-clearance-public leading-none">
          {check.total} citations verified
        </span>
      </motion.div>
    );
  }

  const issues: string[] = [];
  if (check.fabricated.length > 0) {
    issues.push(`${check.fabricated.length} fabricated`);
  }
  if (check.weak.length > 0) {
    issues.push(`${check.weak.length} weak`);
  }
  const tooltipParts: string[] = [];
  if (check.fabricated.length > 0) {
    tooltipParts.push(
      `Fabricated (no chunk exists): [Source ${check.fabricated.join("], [Source ")}]`
    );
  }
  if (check.weak.length > 0) {
    tooltipParts.push(
      `Weak (no word overlap with chunk): [Source ${check.weak.join("], [Source ")}]`
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.96 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.2 }}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border pl-1 pr-2.5 py-[3px]",
        "border-clearance-confidential/40 bg-clearance-confidential/10"
      )}
      title={tooltipParts.join(" · ")}
    >
      <AlertCircle
        className="w-3.5 h-3.5 text-clearance-confidential"
        strokeWidth={2.25}
      />
      <span className="text-[11px] font-semibold text-clearance-confidential leading-none">
        Citation check: {issues.join(", ")} of {check.total}
      </span>
    </motion.div>
  );
}
