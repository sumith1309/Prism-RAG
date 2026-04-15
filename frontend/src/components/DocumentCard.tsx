import { FileText, Trash2 } from "lucide-react";
import type { DocumentMeta } from "@/types";
import { useAppStore } from "@/store/appStore";
import { cn, formatRelative } from "@/lib/utils";
import { ClassificationPill } from "./ClassificationPill";

export function DocumentCard({
  doc,
  onDelete,
  canDelete,
}: {
  doc: DocumentMeta;
  onDelete: () => void;
  canDelete: boolean;
}) {
  const { activeDocIds, toggleActive } = useAppStore();
  const active = activeDocIds.has(doc.doc_id);

  const ext = (doc.filename.split(".").pop() || "").toUpperCase();

  return (
    <div
      className={cn(
        "group relative rounded-md border p-2.5 transition-all duration-150 cursor-pointer",
        active
          ? "border-accent/50 bg-accent-soft shadow-subtle"
          : "border-border bg-white hover:border-border-strong hover:bg-surface-hover hover:shadow-subtle"
      )}
      onClick={() => toggleActive(doc.doc_id)}
      title={active ? "In scope for retrieval — click to remove" : "Click to include in retrieval"}
    >
      <div className="flex items-start gap-2.5">
        <div
          className={cn(
            "mt-0.5 h-7 w-7 shrink-0 rounded-md flex items-center justify-center text-[9px] font-bold border transition-colors",
            active
              ? "bg-accent text-white border-accent"
              : "bg-bg-subtle text-fg-muted border-border"
          )}
        >
          {ext || <FileText className="w-3.5 h-3.5" />}
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-[12.5px] font-medium truncate text-fg" title={doc.filename}>
            {doc.filename}
          </div>
          <div className="text-[10.5px] text-fg-subtle mt-0.5 flex items-center gap-1.5">
            <span>{doc.pages} pg</span>
            <span className="opacity-40">·</span>
            <span>{doc.chunks} chunks</span>
            <span className="opacity-40">·</span>
            <span className="truncate">{formatRelative(doc.created_at)}</span>
          </div>
        </div>
        {canDelete && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              onDelete();
            }}
            className="opacity-0 group-hover:opacity-100 transition p-1 rounded hover:bg-clearance-restricted/20 text-fg-subtle hover:text-clearance-restricted"
            title="Remove"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        )}
      </div>
      <div className="mt-2 flex items-center gap-1.5">
        <ClassificationPill classification={doc.classification} level={doc.doc_level} size="xs" />
        {active && (
          <span className="text-[10px] font-medium text-accent uppercase tracking-wider">
            • in scope
          </span>
        )}
      </div>
    </div>
  );
}
