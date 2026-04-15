import { useState } from "react";
import { useDropzone } from "react-dropzone";
import { UploadCloud } from "lucide-react";

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

export interface UploadOptions {
  classification: number;
  disabled_for_roles?: string[];
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

  // Non-exec path: classic classification dropdown (they can only upload
  // at or below their own clearance). Exec path: the richer "Visible to"
  // picker that derives both classification + hide-list in one step.
  const [level, setLevel] = useState<number>(maxLevel);
  const [visible, setVisible] = useState<Set<VisibleRole>>(
    new Set<VisibleRole>(["executive"])
  );

  const handleDrop = (accepted: File[]) => {
    if (!accepted.length) return;
    if (isExec) {
      const { doc_level, disabled_for_roles } = deriveBackendFields(visible);
      onFiles(accepted, {
        classification: doc_level,
        disabled_for_roles,
      });
    } else {
      onFiles(accepted, { classification: level });
    }
  };

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop: handleDrop,
    accept: {
      "application/pdf": [".pdf"],
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [".docx"],
      "text/plain": [".txt"],
      "text/markdown": [".md", ".markdown"],
    },
    multiple: true,
    disabled: uploading,
  });

  const previewLevel = isExec ? deriveBackendFields(visible).doc_level : level;

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
          <div className="flex items-center justify-between">
            <label className="text-[10.5px] uppercase tracking-wider text-fg-subtle">
              Classify as
            </label>
            <select
              className="bg-bg-elevated border border-border rounded px-1.5 py-0.5 text-[11px] text-fg focus:outline-none focus:border-accent/60"
              value={level}
              onChange={(e) => setLevel(Number(e.target.value))}
              disabled={uploading}
            >
              {Array.from({ length: maxLevel }, (_, i) => i + 1).map((lv) => (
                <option key={lv} value={lv}>
                  L{lv} · {LEVEL_TO_LABEL[lv]}
                </option>
              ))}
            </select>
          </div>
          <div className="text-[10.5px] text-fg-subtle leading-relaxed">
            You can upload up to your own clearance. Others only see it if their level is ≥ this.
          </div>
        </>
      )}

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
            <div className="text-fg-subtle mt-0.5">PDF · DOCX · TXT · MD (up to 25 MB)</div>
          </div>
        </div>
      </div>
    </div>
  );
}
