import { useEffect, useRef, useState } from "react";
import { EyeOff, FileText, Settings, Trash2, User as UserIcon } from "lucide-react";
import { toast } from "sonner";

import type { DocumentMeta, TogglableRole } from "@/types";
import { useAppStore } from "@/store/appStore";
import { cn, formatRelative } from "@/lib/utils";
import { updateDocumentVisibility } from "@/lib/api";
import { ClassificationPill } from "./ClassificationPill";

const ROLE_LABEL: Record<string, string> = {
  system: "Seeded",
  legacy: "Legacy upload",
  guest: "Guest",
  employee: "Employee",
  manager: "Manager",
  executive: "Executive",
};

const TOGGLABLE_ROLES: { value: TogglableRole; label: string }[] = [
  { value: "guest", label: "Guest" },
  { value: "employee", label: "Employee" },
  { value: "manager", label: "Manager" },
];

export function DocumentCard({
  doc,
  onDelete,
  canDelete,
  onUpdated,
}: {
  doc: DocumentMeta;
  onDelete: () => void;
  canDelete: boolean;
  onUpdated?: (updated: DocumentMeta) => void;
}) {
  const { activeDocIds, toggleActive, user } = useAppStore();
  const active = activeDocIds.has(doc.doc_id);
  const isExec = user?.role === "executive";
  const ext = (doc.filename.split(".").pop() || "").toUpperCase();

  const uploaderRoleKey = (doc.uploaded_by_role || "").toLowerCase();
  const uploaderLabel = ROLE_LABEL[uploaderRoleKey] || doc.uploaded_by_role || "—";
  const isSystemDoc = uploaderRoleKey === "system" || uploaderRoleKey === "legacy";
  const uploaderName = isSystemDoc ? uploaderLabel : doc.uploaded_by_username || "unknown";

  const disabledSet = new Set<TogglableRole>(doc.disabled_for_roles || []);
  const hasDisabled = disabledSet.size > 0;

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
          <div className="text-[10.5px] text-fg-subtle mt-0.5 flex items-center gap-1.5 flex-wrap">
            <span>{doc.pages} pg</span>
            <span className="opacity-40">·</span>
            <span>{doc.chunks} chunks</span>
            <span className="opacity-40">·</span>
            <span className="truncate">{formatRelative(doc.created_at)}</span>
          </div>
        </div>
        <div className="flex items-center gap-0.5">
          {isExec && !isSystemDoc && (
            <VisibilityMenu doc={doc} onUpdated={onUpdated} />
          )}
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
      </div>
      <div className="mt-2 flex items-center gap-1.5 flex-wrap">
        <ClassificationPill classification={doc.classification} level={doc.doc_level} size="xs" />
        <span
          className={cn(
            "inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9.5px] font-medium border",
            isSystemDoc
              ? "bg-bg-subtle border-border text-fg-muted"
              : "bg-accent-soft border-accent/20 text-accent"
          )}
          title={
            isSystemDoc
              ? `Part of the ${uploaderLabel.toLowerCase()} corpus`
              : `Uploaded by ${uploaderName} (${uploaderLabel})`
          }
        >
          <UserIcon className="w-2.5 h-2.5" strokeWidth={2} />
          {isSystemDoc ? uploaderLabel : `${uploaderName} · ${uploaderLabel}`}
        </span>
        {hasDisabled && (
          <span
            className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9.5px] font-medium bg-clearance-restricted/10 border border-clearance-restricted/30 text-clearance-restricted"
            title={`Hidden from: ${[...disabledSet].join(", ")}`}
          >
            <EyeOff className="w-2.5 h-2.5" strokeWidth={2} />
            Hidden · {[...disabledSet].map((r) => ROLE_LABEL[r] || r).join(", ")}
          </span>
        )}
        {active && (
          <span className="text-[10px] font-medium text-accent uppercase tracking-wider">
            • in scope
          </span>
        )}
      </div>
    </div>
  );
}

function VisibilityMenu({
  doc,
  onUpdated,
}: {
  doc: DocumentMeta;
  onUpdated?: (updated: DocumentMeta) => void;
}) {
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);
  const [disabled, setDisabled] = useState<Set<TogglableRole>>(
    new Set(doc.disabled_for_roles || [])
  );

  useEffect(() => {
    setDisabled(new Set(doc.disabled_for_roles || []));
  }, [doc.disabled_for_roles]);

  useEffect(() => {
    if (!open) return;
    const onClickAway = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClickAway);
    return () => document.removeEventListener("mousedown", onClickAway);
  }, [open]);

  const commit = async (next: Set<TogglableRole>) => {
    setSaving(true);
    try {
      const updated = await updateDocumentVisibility(doc.doc_id, [...next]);
      onUpdated?.(updated);
      toast.success(
        next.size === 0
          ? "Visible to everyone cleared"
          : `Hidden from ${[...next].join(", ")}`
      );
    } catch (e) {
      toast.error((e as Error).message || "Couldn't update visibility");
      setDisabled(new Set(doc.disabled_for_roles || []));
    } finally {
      setSaving(false);
    }
  };

  const toggle = (role: TogglableRole) => {
    const next = new Set(disabled);
    next.has(role) ? next.delete(role) : next.add(role);
    setDisabled(next);
    commit(next);
  };

  return (
    <div ref={ref} className="relative">
      <button
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        className="p-1 rounded hover:bg-bg-subtle text-fg-subtle hover:text-fg"
        title="Manage visibility (executive-only)"
      >
        <Settings className="w-3.5 h-3.5" />
      </button>
      {open && (
        <div
          onClick={(e) => e.stopPropagation()}
          className="absolute right-0 top-7 z-30 w-56 card p-2 shadow-lg"
        >
          <div className="text-[10px] uppercase tracking-wider font-semibold text-fg-subtle px-1 pb-1.5">
            Hide this document from
          </div>
          <div className="space-y-0.5">
            {TOGGLABLE_ROLES.map((r) => (
              <label
                key={r.value}
                className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-bg-subtle cursor-pointer text-[12px]"
              >
                <input
                  type="checkbox"
                  checked={disabled.has(r.value)}
                  disabled={saving}
                  onChange={() => toggle(r.value)}
                  className="accent-accent"
                />
                <span className="text-fg">{r.label}</span>
                {disabled.has(r.value) && (
                  <span className="ml-auto text-[9.5px] font-semibold uppercase tracking-wider text-clearance-restricted">
                    hidden
                  </span>
                )}
              </label>
            ))}
          </div>
          <div className="text-[10px] text-fg-subtle px-1 pt-2 border-t border-border mt-1.5 leading-relaxed">
            Executive always sees the document. Hiding blocks it from listings
            and from retrieval for the selected roles.
          </div>
        </div>
      )}
    </div>
  );
}
