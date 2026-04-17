import { useState } from "react";
import { useDropzone } from "react-dropzone";
import { CheckCircle2, Sparkles, UploadCloud, X } from "lucide-react";

import { autoClassifyDocument, type AutoClassifyResult } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useAppStore } from "@/store/appStore";
import type { Classification } from "@/types";
import {
  VisibleToSelector,
  deriveBackendFields,
  type VisibleRole,
} from "./VisibleToSelector";

const LEVEL_TO_LABEL: Record<number, Classification> = {
  1: "PUBLIC",
  2: "INTERNAL",
  3: "CONFIDENTIAL",
  4: "RESTRICTED",
};

// Map a clearance level back into the exec's "Visible to" role set.
// L1 PUBLIC = everyone. L2 INTERNAL = employee+ (no guest).
// L3 CONFIDENTIAL = manager+. L4 RESTRICTED = exec only.
function levelToVisibleRoles(level: number): Set<VisibleRole> {
  if (level <= 1) return new Set<VisibleRole>(["guest", "employee", "manager", "executive"]);
  if (level === 2) return new Set<VisibleRole>(["employee", "manager", "executive"]);
  if (level === 3) return new Set<VisibleRole>(["manager", "executive"]);
  return new Set<VisibleRole>(["executive"]);
}

export interface UploadOptions {
  classification: number;
  disabled_for_roles?: string[];
}

interface StagedFile {
  file: File;
  suggestion: AutoClassifyResult | null;
  classifying: boolean;
}

export function UploadDropzone({
  onFiles,
  uploading,
}: {
  onFiles: (files: File[], options: UploadOptions) => void;
  uploading: boolean;
}) {
  const user = useAppStore((s) => s.user);
  const isExec = user?.role === "executive";
  const maxLevel = user?.level ?? 1;

  const [level, setLevel] = useState<number>(maxLevel);
  const [visible, setVisible] = useState<Set<VisibleRole>>(
    new Set<VisibleRole>(["executive"])
  );
  const [staged, setStaged] = useState<StagedFile[]>([]);
  const [acceptedSuggestion, setAcceptedSuggestion] = useState<boolean>(false);

  const handleDrop = async (accepted: File[]) => {
    if (!accepted.length) return;
    // Stage files + kick off auto-classify in parallel for each.
    // We use the FIRST file's suggestion to drive the picker — multi-file
    // uploads are rare and usually share the same classification.
    const initial: StagedFile[] = accepted.map((f) => ({
      file: f,
      suggestion: null,
      classifying: true,
    }));
    setStaged(initial);
    setAcceptedSuggestion(false);
    const results = await Promise.all(
      accepted.map((f) => autoClassifyDocument(f).catch(() => null))
    );
    setStaged(
      accepted.map((f, i) => ({
        file: f,
        suggestion: results[i],
        classifying: false,
      }))
    );
  };

  const acceptSuggestion = () => {
    const first = staged[0]?.suggestion;
    if (!first) return;
    const lv = Math.max(1, Math.min(maxLevel, first.suggested_level));
    if (isExec) {
      setVisible(levelToVisibleRoles(lv));
    } else {
      setLevel(lv);
    }
    setAcceptedSuggestion(true);
  };

  const submitUpload = () => {
    if (!staged.length) return;
    const files = staged.map((s) => s.file);
    if (isExec) {
      const { doc_level, disabled_for_roles } = deriveBackendFields(visible);
      onFiles(files, { classification: doc_level, disabled_for_roles });
    } else {
      onFiles(files, { classification: level });
    }
    setStaged([]);
    setAcceptedSuggestion(false);
  };

  const cancelStaged = () => {
    setStaged([]);
    setAcceptedSuggestion(false);
  };

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop: handleDrop,
    accept: {
      "application/pdf": [".pdf"],
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [".docx"],
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
      "application/vnd.ms-excel": [".xls"],
      "text/csv": [".csv"],
      "text/plain": [".txt"],
      "text/markdown": [".md", ".markdown"],
    },
    multiple: true,
    disabled: uploading || staged.length > 0,
  });

  const previewLevel = isExec ? deriveBackendFields(visible).doc_level : level;
  const firstSuggestion = staged[0]?.suggestion;
  const anyClassifying = staged.some((s) => s.classifying);

  return (
    <div className="space-y-2">
      {isExec ? (
        <div className="space-y-1.5">
          <div className="text-[10.5px] uppercase tracking-wider text-fg-subtle">
            Visible to
          </div>
          <div className="rounded-md border border-border bg-bg-elevated">
            <VisibleToSelector value={visible} onChange={setVisible} disabled={uploading} />
          </div>
          <div className="text-[10px] text-fg-subtle leading-relaxed">
            Will be uploaded as{" "}
            <span className="font-semibold text-fg">
              {LEVEL_TO_LABEL[previewLevel]}
            </span>{" "}
            (L{previewLevel}). Change anytime from the gear icon on the card.
          </div>
        </div>
      ) : (
        <>
          <div className="rounded-md border border-accent/25 bg-accent-soft px-3 py-2 text-[11.5px] leading-relaxed text-fg-muted">
            <span className="font-semibold text-accent">Review-first upload.</span>{" "}
            {user?.role === "employee" ? (
              <>Your document will be visible to <b className="text-fg">Manager + Executive</b> for review. Executive can share it wider after reviewing.</>
            ) : (
              <>Your document will be visible to <b className="text-fg">Executive only</b> for review. Executive can share it with other roles after reviewing.</>
            )}
          </div>
        </>
      )}

      {staged.length === 0 ? (
        <div
          {...getRootProps()}
          className={cn(
            "cursor-pointer group rounded-md border border-dashed border-border",
            "p-3 text-center transition-colors bg-bg-elevated hover:border-accent/40 hover:bg-surface-hover",
            isDragActive && "border-accent/70 bg-accent-soft",
            uploading && "opacity-50 pointer-events-none"
          )}
        >
          <input {...getInputProps()} />
          <div className="flex flex-col items-center gap-2">
            <div className="w-8 h-8 rounded-md bg-bg border border-border flex items-center justify-center">
              <UploadCloud className="w-4 h-4 text-fg-muted" strokeWidth={1.5} />
            </div>
            <div className="text-xs leading-tight">
              <div className="font-medium text-fg">
                {uploading ? "Indexing…" : "Upload a document"}
              </div>
              <div className="text-fg-subtle mt-0.5">PDF · DOCX · XLSX · CSV · TXT · MD (up to 25 MB)</div>
            </div>
          </div>
        </div>
      ) : (
        <div className="space-y-2 rounded-md border border-border bg-bg-elevated p-2.5">
          <div className="flex items-center justify-between">
            <div className="text-[10.5px] uppercase tracking-wider text-fg-subtle font-semibold">
              Ready to upload ({staged.length})
            </div>
            <button
              onClick={cancelStaged}
              className="text-fg-subtle hover:text-fg transition-colors"
              title="Cancel"
              disabled={uploading}
            >
              <X className="w-3 h-3" strokeWidth={2.25} />
            </button>
          </div>

          {staged.map((s, i) => (
            <div key={i} className="text-[11.5px] text-fg truncate">
              · {s.file.name}
            </div>
          ))}

          {/* AI suggestion banner */}
          {anyClassifying && (
            <div className="flex items-center gap-2 text-[11px] text-fg-muted">
              <span className="w-3 h-3 rounded-full border-2 border-accent/30 border-t-accent animate-spin" />
              AI is suggesting a clearance level…
            </div>
          )}
          {!anyClassifying && firstSuggestion && (
            <div
              className={cn(
                "rounded border px-2.5 py-2 text-[11.5px] leading-snug",
                acceptedSuggestion
                  ? "border-clearance-public/40 bg-clearance-public/5"
                  : "border-accent/30 bg-accent-soft"
              )}
            >
              <div className="flex items-center gap-1.5 mb-1">
                {acceptedSuggestion ? (
                  <CheckCircle2 className="w-3 h-3 text-clearance-public" strokeWidth={2.25} />
                ) : (
                  <Sparkles className="w-3 h-3 text-accent" strokeWidth={2.25} />
                )}
                <span
                  className={cn(
                    "font-semibold uppercase tracking-wider text-[10px]",
                    acceptedSuggestion ? "text-clearance-public" : "text-accent"
                  )}
                >
                  {acceptedSuggestion ? "AI suggestion applied" : "AI suggests"}
                </span>
                <span className="text-fg-subtle text-[10px]">
                  {Math.round(firstSuggestion.confidence * 100)}% confidence
                </span>
              </div>
              <div className="text-fg">
                <span className="font-semibold">
                  L{firstSuggestion.suggested_level} · {firstSuggestion.suggested_label}
                </span>
                {firstSuggestion.capped_to_user_level && (
                  <span className="text-fg-subtle ml-1">(capped to your clearance)</span>
                )}
              </div>
              <div className="text-fg-muted mt-0.5">{firstSuggestion.reason}</div>
              {!acceptedSuggestion && (
                <button
                  onClick={acceptSuggestion}
                  className="mt-1.5 text-[10.5px] font-semibold text-accent hover:underline"
                >
                  Use this →
                </button>
              )}
            </div>
          )}

          <button
            onClick={submitUpload}
            disabled={uploading || anyClassifying}
            className={cn(
              "w-full rounded-md px-3 py-1.5 text-[12px] font-semibold transition-colors",
              "bg-accent text-white hover:bg-accent/90",
              "disabled:opacity-50 disabled:cursor-not-allowed"
            )}
          >
            {uploading
              ? "Indexing…"
              : `Upload ${staged.length} file${staged.length === 1 ? "" : "s"} as ${LEVEL_TO_LABEL[previewLevel]}`}
          </button>
        </div>
      )}
    </div>
  );
}
