import type { User } from "@/types";
import { cn } from "@/lib/utils";

const ROLE_STYLE: Record<User["role"], { chip: string; dot: string }> = {
  guest: { chip: "text-clearance-public border-clearance-public/30", dot: "bg-clearance-public" },
  employee: { chip: "text-clearance-internal border-clearance-internal/30", dot: "bg-clearance-internal" },
  manager: { chip: "text-clearance-confidential border-clearance-confidential/30", dot: "bg-clearance-confidential" },
  executive: { chip: "text-clearance-restricted border-clearance-restricted/30", dot: "bg-clearance-restricted" },
};

export function RoleBadge({ user }: { user: User }) {
  const s = ROLE_STYLE[user.role];
  return (
    <div
      className={cn(
        "inline-flex items-center gap-2 rounded-md border px-2.5 py-1 bg-bg-elevated",
        s.chip
      )}
    >
      <span className={cn("w-1.5 h-1.5 rounded-full", s.dot)} />
      <span className="text-[11px] font-semibold uppercase tracking-wider">{user.role}</span>
      <span className="text-[11px] text-fg-muted border-l border-border pl-2">L{user.level}</span>
    </div>
  );
}
