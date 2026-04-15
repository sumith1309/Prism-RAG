import type { Classification } from "@/types";
import { cn } from "@/lib/utils";

const STYLES: Record<Classification, { dot: string; label: string }> = {
  PUBLIC: { dot: "bg-clearance-public", label: "text-clearance-public" },
  INTERNAL: { dot: "bg-clearance-internal", label: "text-clearance-internal" },
  CONFIDENTIAL: { dot: "bg-clearance-confidential", label: "text-clearance-confidential" },
  RESTRICTED: { dot: "bg-clearance-restricted", label: "text-clearance-restricted" },
};

export function ClassificationPill({
  classification,
  level,
  size = "sm",
}: {
  classification: Classification;
  level?: number;
  size?: "xs" | "sm";
}) {
  const s = STYLES[classification];
  return (
    <span
      className={cn(
        "pill border border-border",
        size === "xs" ? "text-[10px] px-1.5 py-0" : "text-[11px]"
      )}
    >
      <span className={cn("w-1.5 h-1.5 rounded-full", s.dot)} />
      <span className={s.label}>{classification}</span>
      {level !== undefined && <span className="text-fg-subtle ml-0.5">L{level}</span>}
    </span>
  );
}
