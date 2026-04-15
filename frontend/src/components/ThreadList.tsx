import { useMemo, useState } from "react";
import { NavLink, useNavigate, useParams } from "react-router-dom";
import { Check, MessageSquare, MoreHorizontal, Pencil, Plus, Trash2, X } from "lucide-react";

import { useThreads } from "@/hooks/useThreads";
import { createThread } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { ThreadSummary } from "@/types";

function groupByRecency(threads: ThreadSummary[]) {
  const now = Date.now();
  const day = 24 * 60 * 60 * 1000;
  const groups: Record<string, ThreadSummary[]> = {
    Today: [],
    Yesterday: [],
    "Last 7 days": [],
    Older: [],
  };
  for (const t of threads) {
    const age = now - new Date(t.updated_at).getTime();
    if (age < day) groups.Today.push(t);
    else if (age < 2 * day) groups.Yesterday.push(t);
    else if (age < 7 * day) groups["Last 7 days"].push(t);
    else groups.Older.push(t);
  }
  return groups;
}

export function ThreadList() {
  const { threadId: activeId } = useParams<{ threadId?: string }>();
  const { threads, loading, rename, remove } = useThreads();
  const navigate = useNavigate();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [menuOpenId, setMenuOpenId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const groups = useMemo(() => groupByRecency(threads), [threads]);

  const startEdit = (t: ThreadSummary) => {
    setEditingId(t.id);
    setDraft(t.title || "New chat");
    setMenuOpenId(null);
  };

  const saveEdit = async () => {
    if (!editingId) return;
    const title = draft.trim();
    if (title) await rename(editingId, title);
    setEditingId(null);
    setDraft("");
  };

  const onNew = async () => {
    setCreating(true);
    try {
      const t = await createThread();
      navigate(`/app/t/${t.id}`);
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="flex flex-col h-full">
      <button
        onClick={onNew}
        disabled={creating}
        className="mx-3 my-3 inline-flex items-center justify-center gap-2 rounded-md bg-accent-soft border border-accent/30 text-accent hover:bg-accent/15 transition-colors text-[12.5px] font-medium py-2 disabled:opacity-60"
      >
        <Plus className="w-3.5 h-3.5" strokeWidth={2} /> New chat
      </button>

      <div className="flex-1 overflow-y-auto scrollbar-thin px-1.5 pb-3 space-y-3">
        {loading && threads.length === 0 && (
          <div className="text-center text-fg-subtle text-xs py-6">Loading threads…</div>
        )}
        {!loading && threads.length === 0 && (
          <div className="text-center text-fg-subtle text-xs py-6 px-4 leading-relaxed">
            No threads yet. Start a new chat to begin.
          </div>
        )}
        {Object.entries(groups).map(([label, list]) =>
          list.length === 0 ? null : (
            <section key={label}>
              <div className="text-[10px] uppercase tracking-wider text-fg-subtle px-2.5 mb-1">
                {label}
              </div>
              <div className="space-y-0.5">
                {list.map((t) => {
                  const isActive = t.id === activeId;
                  const isEditing = editingId === t.id;
                  return (
                    <div
                      key={`${t.id}-${t.updated_at}`}
                      className={cn(
                        "group relative rounded-md transition-colors",
                        isActive ? "bg-accent-soft border border-accent/30" : "hover:bg-surface-hover border border-transparent"
                      )}
                    >
                      {isEditing ? (
                        <div className="flex items-center gap-1 px-2 py-1.5">
                          <input
                            autoFocus
                            value={draft}
                            onChange={(e) => setDraft(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === "Enter") saveEdit();
                              if (e.key === "Escape") {
                                setEditingId(null);
                                setDraft("");
                              }
                            }}
                            className="flex-1 bg-bg-elevated border border-border rounded px-2 py-1 text-[12.5px] text-fg outline-none focus:border-accent/60"
                          />
                          <button onClick={saveEdit} className="p-1 text-accent hover:bg-accent/10 rounded">
                            <Check className="w-3.5 h-3.5" />
                          </button>
                          <button onClick={() => setEditingId(null)} className="p-1 text-fg-subtle hover:bg-surface-hover rounded">
                            <X className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      ) : (
                        <NavLink
                          to={`/app/t/${t.id}`}
                          onDoubleClick={() => startEdit(t)}
                          className="flex items-center gap-2 px-2.5 py-1.5"
                        >
                          <MessageSquare className="w-3.5 h-3.5 text-fg-subtle shrink-0" strokeWidth={1.5} />
                          <span
                            className={cn(
                              "truncate text-[13px] flex-1",
                              isActive ? "text-fg font-medium" : "text-fg-muted"
                            )}
                            title={t.title || "New chat"}
                          >
                            {t.title || "New chat"}
                          </span>
                          <button
                            onClick={(e) => {
                              e.preventDefault();
                              setMenuOpenId(menuOpenId === t.id ? null : t.id);
                            }}
                            className="opacity-0 group-hover:opacity-100 p-0.5 rounded text-fg-subtle hover:text-fg hover:bg-surface-active transition"
                          >
                            <MoreHorizontal className="w-3.5 h-3.5" />
                          </button>
                        </NavLink>
                      )}
                      {menuOpenId === t.id && (
                        <div className="absolute right-1 top-full mt-0.5 z-10 bg-bg-elevated border border-border rounded-md shadow-pop py-0.5 min-w-[140px]">
                          <button
                            onClick={() => startEdit(t)}
                            className="w-full flex items-center gap-2 px-2.5 py-1.5 text-[12.5px] text-fg hover:bg-surface-hover text-left"
                          >
                            <Pencil className="w-3.5 h-3.5" /> Rename
                          </button>
                          <button
                            onClick={async () => {
                              setMenuOpenId(null);
                              await remove(t.id);
                              if (activeId === t.id) navigate("/app");
                            }}
                            className="w-full flex items-center gap-2 px-2.5 py-1.5 text-[12.5px] text-clearance-restricted hover:bg-clearance-restricted/10 text-left"
                          >
                            <Trash2 className="w-3.5 h-3.5" /> Delete
                          </button>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </section>
          )
        )}
      </div>
    </div>
  );
}
