import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import {
  deleteThread as apiDelete,
  listThreads,
  renameThread as apiRename,
} from "@/lib/api";
import { useAppStore } from "@/store/appStore";
import type { ThreadSummary } from "@/types";

export function useThreads() {
  const user = useAppStore((s) => s.user);
  const [threads, setThreads] = useState<ThreadSummary[]>([]);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    if (!user) return;
    setLoading(true);
    try {
      const data = await listThreads();
      setThreads(data);
    } catch (e: any) {
      toast.error(e.message || "Failed to load threads");
    } finally {
      setLoading(false);
    }
  }, [user]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Bump list whenever a thread's updated_at changes remotely (listen to global event).
  useEffect(() => {
    const handler = () => refresh();
    window.addEventListener("technova:threads-changed", handler);
    return () => window.removeEventListener("technova:threads-changed", handler);
  }, [refresh]);

  const rename = useCallback(
    async (id: string, title: string) => {
      try {
        const updated = await apiRename(id, title);
        setThreads((prev) => prev.map((t) => (t.id === id ? updated : t)));
      } catch (e: any) {
        toast.error(e.message || "Rename failed");
      }
    },
    []
  );

  const remove = useCallback(async (id: string) => {
    try {
      await apiDelete(id);
      setThreads((prev) => prev.filter((t) => t.id !== id));
    } catch (e: any) {
      toast.error(e.message || "Delete failed");
    }
  }, []);

  return { threads, loading, refresh, rename, remove };
}

/** Fire-and-forget signal to every subscriber that the thread list changed. */
export function pingThreadsChanged() {
  window.dispatchEvent(new Event("technova:threads-changed"));
}
