import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { motion } from "framer-motion";
import { AlertTriangle, FileText, GitCompareArrows } from "lucide-react";

import type { ComparisonColumn } from "@/types";
import { cn } from "@/lib/utils";
import { SourceCitationCard } from "./SourceCitationCard";

/** Tier 2.2 — side-by-side answer view. Rendered when the user clicked
 * "Compare all" on a disambiguation card. Each column is an independent
 * answer scoped to one document, so content never blends across docs.
 *
 * Layout: stacks vertically on narrow screens, switches to a 2-3 column
 * grid on wider viewports. Each column is self-contained — its own
 * answer body, its own source citations, its own error state if that
 * doc's retrieval/generation failed.
 */
export function ComparisonCard({
  columns,
}: {
  columns: ComparisonColumn[];
}) {
  if (!columns.length) return null;
  const n = columns.length;
  const gridCols = n === 2 ? "md:grid-cols-2" : n === 3 ? "md:grid-cols-3" : "md:grid-cols-2";

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22 }}
    >
      <div className="flex items-start gap-2.5 max-w-full">
        <div className="w-7 h-7 shrink-0 rounded-md bg-accent-soft border border-accent/30 flex items-center justify-center mt-0.5">
          <GitCompareArrows
            className="w-3.5 h-3.5 text-accent"
            strokeWidth={1.75}
          />
        </div>
        <div className="flex-1 min-w-0 space-y-3">
          <div className="text-[10.5px] uppercase tracking-wider font-semibold text-accent">
            Side-by-side comparison · {n} documents
          </div>
          <div className={cn("grid grid-cols-1 gap-3", gridCols)}>
            {columns.map((col) => (
              <ComparisonColumnView key={col.doc_id} column={col} />
            ))}
          </div>
        </div>
      </div>
    </motion.div>
  );
}

function ComparisonColumnView({ column }: { column: ComparisonColumn }) {
  return (
    <div className="card px-3.5 py-3 space-y-2 flex flex-col">
      <div className="flex items-center gap-2 min-w-0">
        <div className="w-6 h-6 shrink-0 rounded bg-bg border border-border flex items-center justify-center">
          <FileText className="w-3 h-3 text-fg-muted" strokeWidth={1.75} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-[12.5px] font-semibold text-fg truncate">
            {column.label || column.filename}
          </div>
          <div className="text-[10px] text-fg-subtle">
            {column.sources.length} source{column.sources.length === 1 ? "" : "s"}
          </div>
        </div>
      </div>

      {!column.ok && (
        <div className="rounded border border-clearance-confidential/30 bg-clearance-confidential/10 px-2.5 py-1.5 text-[11.5px] leading-relaxed flex items-start gap-1.5">
          <AlertTriangle
            className="w-3 h-3 shrink-0 text-clearance-confidential mt-0.5"
            strokeWidth={2.25}
          />
          <div className="text-fg">
            {column.error === "weak_match"
              ? "This document has no strong match for your question."
              : column.error
              ? `Error: ${column.error}`
              : "No confident answer from this document."}
          </div>
        </div>
      )}

      {column.answer && (
        <div className="text-[13px] leading-relaxed text-fg prose-like flex-1">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              p: ({ children }) => (
                <p className="my-1.5 first:mt-0 last:mb-0">{children}</p>
              ),
              ul: ({ children }) => (
                <ul className="list-disc pl-4 my-1.5 space-y-0.5">{children}</ul>
              ),
              ol: ({ children }) => (
                <ol className="list-decimal pl-4 my-1.5 space-y-0.5">{children}</ol>
              ),
              strong: ({ children }) => (
                <strong className="text-fg font-semibold">{children}</strong>
              ),
              code: ({ children }) => (
                <code className="bg-accent-soft border border-accent/15 text-accent rounded px-1 py-0.5 text-[11.5px] font-mono">
                  {children}
                </code>
              ),
            }}
          >
            {column.answer.replace(/\[Source (\d+)\]/g, "**[Source $1]**")}
          </ReactMarkdown>
        </div>
      )}

      {column.sources.length > 0 && (
        <div className="space-y-1 pt-1 border-t border-border">
          <div className="text-[9.5px] uppercase tracking-wider text-fg-subtle font-semibold">
            Sources
          </div>
          {column.sources.slice(0, 3).map((s) => (
            <SourceCitationCard key={`${s.doc_id}-${s.index}`} source={s} />
          ))}
          {column.sources.length > 3 && (
            <div className="text-[10px] text-fg-subtle">
              +{column.sources.length - 3} more
            </div>
          )}
        </div>
      )}
    </div>
  );
}
