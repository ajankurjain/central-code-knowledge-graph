"use client";

// Shared searchable repo combobox + refresh button.
//
// The native <select> falls over once you've registered hundreds of repos —
// no filter, no visual cue for which repos have ever been indexed. This
// component filters as you type, sorts indexed repos first, and tags each
// row with its index state. The companion `RefreshButton` re-fetches the
// repo list so freshly-indexed repos move from `NOT INDEXED` → `INDEXED`
// without a full page reload.

import { useEffect, useMemo, useRef, useState } from "react";
import type { Repo } from "@/lib/types";

export function RepoPicker({
  repos,
  value,
  onChange,
  placeholder = "— select repo —",
}: {
  repos: Repo[];
  value: string;
  onChange: (id: string) => void;
  placeholder?: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const wrapRef = useRef<HTMLDivElement | null>(null);

  // Close on outside click.
  useEffect(() => {
    function onDown(e: MouseEvent) {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);

  const indexed = repos.filter((r) => r.last_indexed_at);
  const sorted = useMemo(() => {
    // Indexed first (those are the ones with anything to render), then alpha.
    return [...repos].sort((a, b) => {
      const ai = a.last_indexed_at ? 0 : 1;
      const bi = b.last_indexed_at ? 0 : 1;
      if (ai !== bi) return ai - bi;
      return a.id.localeCompare(b.id);
    });
  }, [repos]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return sorted;
    return sorted.filter(
      (r) => r.id.toLowerCase().includes(q) || (r.url ?? "").toLowerCase().includes(q),
    );
  }, [sorted, query]);

  const current = repos.find((r) => r.id === value);

  return (
    <div ref={wrapRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between rounded border border-slate-700 bg-slate-950 px-3 py-2 text-left text-sm hover:border-slate-600"
      >
        <span className={current ? "font-mono text-violet-200" : "text-slate-500"}>
          {current ? current.id : placeholder}
        </span>
        <span className="ml-3 text-xs text-slate-500">
          {repos.length.toLocaleString()} total · {indexed.length.toLocaleString()} indexed
        </span>
      </button>
      {open && (
        <div className="absolute left-0 right-0 z-20 mt-1 max-h-80 overflow-hidden rounded border border-slate-700 bg-slate-950 shadow-xl">
          <input
            autoFocus
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="filter…"
            className="w-full border-b border-slate-800 bg-slate-950 px-3 py-2 text-sm placeholder:text-slate-500 focus:outline-none"
          />
          <ul className="max-h-64 overflow-y-auto py-1 text-sm">
            {value && (
              <li>
                <button
                  type="button"
                  onClick={() => {
                    onChange("");
                    setOpen(false);
                    setQuery("");
                  }}
                  className="w-full px-3 py-1.5 text-left text-slate-400 hover:bg-slate-900"
                >
                  — clear —
                </button>
              </li>
            )}
            {filtered.length === 0 && <li className="px-3 py-2 text-slate-500">no matches</li>}
            {filtered.slice(0, 200).map((r) => (
              <li key={r.id}>
                <button
                  type="button"
                  onClick={() => {
                    onChange(r.id);
                    setOpen(false);
                    setQuery("");
                  }}
                  className={`flex w-full items-center justify-between gap-3 px-3 py-1.5 text-left hover:bg-slate-900 ${
                    r.id === value ? "bg-slate-900" : ""
                  }`}
                >
                  <span className="truncate font-mono text-violet-200">{r.id}</span>
                  <span
                    className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wider ${
                      r.last_indexed_at
                        ? "bg-emerald-900/60 text-emerald-300"
                        : "bg-slate-800 text-slate-400"
                    }`}
                  >
                    {r.last_indexed_at ? "indexed" : "not indexed"}
                  </span>
                </button>
              </li>
            ))}
            {filtered.length > 200 && (
              <li className="px-3 py-1.5 text-xs text-slate-500">
                showing first 200 of {filtered.length.toLocaleString()} — refine the filter
              </li>
            )}
          </ul>
        </div>
      )}
    </div>
  );
}

// Spinner-on-click refresh button. Pair it with a useQuery call:
//   const repos = useQuery(...);
//   <RefreshButton onClick={() => repos.refetch()} isFetching={repos.isFetching}
//                  dataUpdatedAt={repos.dataUpdatedAt} />
export function RefreshButton({
  onClick,
  isFetching,
  dataUpdatedAt,
  title = "Refresh repos",
}: {
  onClick: () => void;
  isFetching: boolean;
  dataUpdatedAt: number;
  title?: string;
}) {
  const since = useRelativeTime(dataUpdatedAt);
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={isFetching}
      title={`${title}${dataUpdatedAt ? ` · last loaded ${since}` : ""}`}
      aria-label={title}
      className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200 hover:border-slate-600 hover:bg-slate-900 disabled:opacity-50"
    >
      <svg
        viewBox="0 0 24 24"
        width="16"
        height="16"
        aria-hidden="true"
        className={`inline-block ${isFetching ? "animate-spin" : ""}`}
      >
        <path
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M21 12a9 9 0 1 1-3.2-6.9M21 4v5h-5"
        />
      </svg>
    </button>
  );
}

function useRelativeTime(ts: number): string {
  const [, tick] = useState(0);
  useEffect(() => {
    const i = setInterval(() => tick((n) => n + 1), 15_000);
    return () => clearInterval(i);
  }, []);
  if (!ts) return "";
  const diff = Math.max(0, Date.now() - ts);
  if (diff < 60_000) return `${Math.round(diff / 1000)}s ago`;
  if (diff < 3_600_000) return `${Math.round(diff / 60_000)}m ago`;
  return `${Math.round(diff / 3_600_000)}h ago`;
}
