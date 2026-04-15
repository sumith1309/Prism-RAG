import { create } from "zustand";
import type { ChatSettings, DocumentMeta, User } from "@/types";
import { clearToken, getCachedUser, setCachedUser, setToken } from "@/lib/auth";

export type SidebarTab = "threads" | "knowledge";

interface AppState {
  // auth
  user: User | null;
  setAuth: (user: User, token: string) => void;
  logout: () => void;

  // documents
  documents: DocumentMeta[];
  activeDocIds: Set<string>;
  setDocuments: (docs: DocumentMeta[]) => void;
  toggleActive: (docId: string) => void;
  setAllActive: (on: boolean) => void;

  // chat settings
  settings: ChatSettings;
  updateSettings: (patch: Partial<ChatSettings>) => void;

  // thread state
  currentThreadId: string | null;
  pendingThreadId: string | null;
  setCurrentThreadId: (id: string | null) => void;
  setPendingThreadId: (id: string | null) => void;

  // UI
  sidebarTab: SidebarTab;
  setSidebarTab: (t: SidebarTab) => void;
}

export const useAppStore = create<AppState>((set) => ({
  user: getCachedUser(),

  setAuth: (user, token) => {
    setToken(token);
    setCachedUser(user);
    set({ user });
  },

  logout: () => {
    clearToken();
    set({
      user: null,
      documents: [],
      activeDocIds: new Set(),
      currentThreadId: null,
      pendingThreadId: null,
    });
  },

  documents: [],
  activeDocIds: new Set(),

  setDocuments: (docs) =>
    set((s) => {
      const existing = s.activeDocIds;
      const knownIds = new Set(s.documents.map((d) => d.doc_id));
      const next = new Set<string>();
      docs.forEach((d) => {
        if (existing.has(d.doc_id)) next.add(d.doc_id);
        else if (!knownIds.has(d.doc_id)) next.add(d.doc_id);
      });
      if (s.documents.length === 0 && next.size === 0) docs.forEach((d) => next.add(d.doc_id));
      return { documents: docs, activeDocIds: next };
    }),

  toggleActive: (docId) =>
    set((s) => {
      const next = new Set(s.activeDocIds);
      if (next.has(docId)) next.delete(docId);
      else next.add(docId);
      return { activeDocIds: next };
    }),

  setAllActive: (on) =>
    set((s) => ({
      activeDocIds: on ? new Set(s.documents.map((d) => d.doc_id)) : new Set(),
    })),

  settings: {
    useHyde: false,
    useRerank: true,
    useMultiQuery: false,
    useCorrective: true,
    useFaithfulness: true,
    topK: 5,
    sectionFilter: [],
  },
  updateSettings: (patch) => set((s) => ({ settings: { ...s.settings, ...patch } })),

  currentThreadId: null,
  pendingThreadId: null,
  setCurrentThreadId: (id) => set({ currentThreadId: id }),
  setPendingThreadId: (id) => set({ pendingThreadId: id }),

  sidebarTab: "threads",
  setSidebarTab: (t) => set({ sidebarTab: t }),
}));
