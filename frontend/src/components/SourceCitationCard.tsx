import { useState } from "react";
import { ChevronDown, Copy, FileText } from "lucide-react";
import { toast } from "sonner";

import type { Source } from "@/types";
import { cn } from "@/lib/utils";

function clampScore(score: number, min: number, max: number) {
  const v = Math.max(min, Math.min(max, score));
  return ((v - min) / (max - min)) * 100;
}

export function SourceCitationCard({ source }: { source: Source }) {
  const [expanded, setExpanded] = useState(false);

  const rrfPct = clampScore(source.rrf_score, 0, 0.08);
  const rerankPct =
    source.rerank_score === null ? 0 : clampScore(source.rerank_score, -5, 5);

  const onCopy = (e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard.writeText(source.text);
    toast.success("Copied source text");
  };

  return (
    <div className="card card-hover overflow-hidden">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-2 text-left"
      >
        <span className="shrink-0 w-5 h-5 rounded bg-accent text-white flex items-center justify-center text-[10px] font-bold">
          {source.index}
        </span>
        <FileText className="w-3.5 h-3.5 text-fg-subtle shrink-0" strokeWidth={1.5} />
        <span className="text-[12.5px] font-medium truncate text-fg">{source.filename}</span>
        <span className="text-[11px] text-fg-muted shrink-0">p.{source.page}</span>
        {source.section && (
          <span className="text-[10.5px] text-fg-subtle truncate">· {source.section}</span>
        )}
        <span className="ml-auto text-[11px] text-fg-muted font-mono shrink-0">
          {source.rerank_score !== null
            ? source.rerank_score.toFixed(2)
            : source.rrf_score.toFixed(3)}
        </span>
        <ChevronDown
          className={cn(
            "w-3.5 h-3.5 text-fg-subtle transition-transform shrink-0",
            expanded && "rotate-180"
          )}
        />
      </button>

      {expanded && (
        <div className="px-3 pb-3 space-y-2 text-[12.5px] border-t border-border">
          <div className="rounded bg-bg-subtle border border-border p-2.5 text-fg whitespace-pre-wrap leading-relaxed max-h-60 overflow-y-auto scrollbar-thin font-mono text-[12px]">
            {source.text}
          </div>
          <div className="grid grid-cols-2 gap-3 text-[11px] pt-1">
            <ScoreBar
              label="RRF (hybrid)"
              value={source.rrf_score.toFixed(4)}
              pct={rrfPct}
            />
            <ScoreBar
              label="Cross-encoder rerank"
              value={source.rerank_score === null ? "—" : source.rerank_score.toFixed(3)}
              pct={rerankPct}
            />
          </div>
          <div className="flex justify-end">
            <button onClick={onCopy} className="btn-ghost text-[11px] px-2 py-1">
              <Copy className="w-3 h-3" /> Copy source
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function ScoreBar({ label, value, pct }: { label: string; value: string; pct: number }) {
  return (
    <div>
      <div className="flex items-center justify-between text-fg-muted mb-1">
        <span>{label}</span>
        <span className="font-mono text-fg-subtle">{value}</span>
      </div>
      <div className="h-1 rounded-full bg-bg-subtle overflow-hidden">
        <div className="h-full bg-accent transition-all duration-500" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
