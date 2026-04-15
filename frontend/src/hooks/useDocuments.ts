import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { deleteDocument, listDocuments, uploadDocuments } from "@/lib/api";
import { useAppStore } from "@/store/appStore";

export function useDocuments() {
  const { documents, setDocuments } = useAppStore();
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const docs = await listDocuments();
      setDocuments(docs);
    } catch (e: any) {
      toast.error(`Could not load documents: ${e.message}`);
    } finally {
      setLoading(false);
    }
  }, [setDocuments]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const upload = useCallback(
    async (
      files: File[],
      options?: { classification?: number; disabled_for_roles?: string[] }
    ) => {
      if (!files.length) return;
      setUploading(true);
      const names = files.map((f) => f.name).join(", ");
      const toastId = toast.loading(`Uploading & indexing: ${names}`);
      try {
        const results = await uploadDocuments(
          files,
          options?.classification,
          options?.disabled_for_roles
        );
        const okCount = results.filter((r) => r.status === "ok").length;
        const failures = results.filter((r) => r.status !== "ok");
        if (okCount > 0) toast.success(`Indexed ${okCount} document${okCount > 1 ? "s" : ""}`, { id: toastId });
        else toast.error("No documents were indexed", { id: toastId });
        failures.forEach((f) =>
          toast.error(`${f.filename}: ${f.error || "failed"}`)
        );
        await refresh();
      } catch (e: any) {
        toast.error(`Upload failed: ${e.message}`, { id: toastId });
      } finally {
        setUploading(false);
      }
    },
    [refresh]
  );

  const remove = useCallback(
    async (docId: string, filename: string) => {
      try {
        await deleteDocument(docId);
        toast.success(`Removed ${filename}`);
        await refresh();
      } catch (e: any) {
        toast.error(`Could not delete: ${e.message}`);
      }
    },
    [refresh]
  );

  return { documents, loading, uploading, refresh, upload, remove };
}
