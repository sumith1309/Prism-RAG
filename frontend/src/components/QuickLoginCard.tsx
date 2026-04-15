import { ChevronRight, Lock } from "lucide-react";
import type { Classification, User } from "@/types";
import { ClassificationPill } from "./ClassificationPill";
import { cn } from "@/lib/utils";

interface Props {
  role: User["role"];
  title: string;
  username: string;
  password: string;
  classification: Classification;
  level: number;
  reads: string;
  onClick: (username: string, password: string) => void;
  loading: boolean;
}

export function QuickLoginCard({
  role,
  title,
  username,
  password,
  classification,
  level,
  reads,
  onClick,
  loading,
}: Props) {
  return (
    <button
      type="button"
      disabled={loading}
      onClick={() => onClick(username, password)}
      className={cn(
        "group w-full text-left card card-hover p-4 transition-all",
        "disabled:opacity-60 disabled:pointer-events-none",
        "focus-visible:border-accent"
      )}
    >
      <div className="flex items-start justify-between gap-3 mb-2">
        <div>
          <div className="text-[11px] uppercase tracking-wider text-fg-subtle mb-0.5">
            Sign in as
          </div>
          <div className="text-sm font-semibold text-fg">{title}</div>
          <div className="text-xs text-fg-muted mt-0.5 font-mono">
            {username} · {password}
          </div>
        </div>
        <ChevronRight className="w-4 h-4 text-fg-subtle group-hover:text-accent transition-colors flex-shrink-0" />
      </div>

      <div className="flex items-center gap-2 mb-1.5">
        <ClassificationPill classification={classification} level={level} />
        <span className="text-[10px] uppercase tracking-wider text-fg-subtle">role: {role}</span>
      </div>
      <div className="text-xs text-fg-muted flex items-start gap-1.5">
        <Lock className="w-3 h-3 mt-0.5 flex-shrink-0" />
        <span>Reads: {reads}</span>
      </div>
    </button>
  );
}
