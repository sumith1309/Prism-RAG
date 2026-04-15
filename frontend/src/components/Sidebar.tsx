import { useMemo } from "react";
import { LibraryBig, MessagesSquare } from "lucide-react";

import { useDocuments } from "@/hooks/useDocuments";
import { useAppStore } from "@/store/appStore";
import { DocumentCard } from "./DocumentCard";
import { ThreadList } from "./ThreadList";
import { UploadDropzone } from "./UploadDropzone";
import type { Classification, DocumentMeta } from "@/types";
import { cn } from "@/lib/utils";

const ORDER: Classification[] = ["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"];

export function Sidebar() {
  const { documents, upload, remove, uploading } = useDocuments();
  const { user, sidebarTab, setSidebarTab } = useAppStore();
  const canDelete = (user?.level ?? 0) >= 3;

  const grouped = useMemo(() => {
    const g: Record<Classification, DocumentMeta[]> = {
      PUBLIC: [],
      INTERNAL: [],
      CONFIDENTIAL: [],
      RESTRICTED: [],
    };
    for (const d of documents) g[d.classification].push(d);
    return g;
  }, [documents]);

  return (
    <aside className="w-[300px] shrink-0 flex flex-col border-r border-border bg-bg-subtle">
      {/* Tab switcher */}
      <div className="p-3 border-b border-border">
        <div className="flex items-center gap-0.5 bg-bg-elevated border border-border rounded-md p-0.5">
          <TabButton
            active={sidebarTab === "threads"}
            onClick={() => setSidebarTab("threads")}
            icon={<MessagesSquare className="w-3.5 h-3.5" strokeWidth={1.75} />}
            label="Threads"
          />
          <TabButton
            active={sidebarTab === "knowledge"}
            onClick={() => setSidebarTab("knowledge")}
            icon={<LibraryBig className="w-3.5 h-3.5" strokeWidth={1.75} />}
            label="Knowledge"
          />
        </div>
      </div>

      {sidebarTab === "threads" ? (
        <ThreadList />
      ) : (
        <div className="flex-1 flex flex-col min-h-0">
          <div className="p-3 border-b border-border">
            <UploadDropzone onFiles={upload} uploading={uploading} />
          </div>
          <div className="flex-1 overflow-y-auto scrollbar-thin p-3 space-y-4">
            {documents.length === 0 ? (
              <div className="text-center text-fg-subtle text-xs py-6 px-4 leading-relaxed">
                No documents accessible to your role.
              </div>
            ) : (
              ORDER.map((cls) =>
                grouped[cls].length === 0 ? null : (
                  <section key={cls}>
                    <div className="text-[10px] uppercase tracking-wider text-fg-subtle mb-1.5 px-0.5">
                      {cls}
                    </div>
                    <div className="space-y-1.5">
                      {grouped[cls].map((doc) => (
                        <DocumentCard
                          key={doc.doc_id}
                          doc={doc}
                          onDelete={() => remove(doc.doc_id, doc.filename)}
                          canDelete={canDelete}
                        />
                      ))}
                    </div>
                  </section>
                )
              )
            )}
          </div>
        </div>
      )}
    </aside>
  );
}

function TabButton({
  active,
  onClick,
  icon,
  label,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "flex-1 flex items-center justify-center gap-1.5 px-2.5 py-1.5 text-[12px] rounded-sm transition-colors",
        active
          ? "bg-surface-active text-fg font-medium"
          : "text-fg-muted hover:text-fg"
      )}
    >
      {icon}
      {label}
    </button>
  );
}
