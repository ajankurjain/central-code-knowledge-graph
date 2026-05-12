"use client";

// Minimal client-side pagination + search helper used by the Dashboard preview
// and the full /repos table. Filtering happens before pagination so the count
// shown reflects the filtered set, not the raw total.

import { useMemo, useState } from "react";

export function usePaginatedList<T>(
  items: readonly T[] | undefined,
  match: (item: T, q: string) => boolean,
  pageSize = 25,
) {
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!items) return [];
    if (!q) return items;
    return items.filter((it) => match(it, q));
  }, [items, match, query]);

  const total = filtered.length;
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const safePage = Math.min(page, pageCount - 1);
  const start = safePage * pageSize;
  const slice = filtered.slice(start, start + pageSize);

  function setQueryAndReset(q: string) {
    setQuery(q);
    setPage(0);
  }

  return {
    query,
    setQuery: setQueryAndReset,
    page: safePage,
    setPage,
    pageCount,
    pageSize,
    total,
    rawTotal: items?.length ?? 0,
    slice,
    rangeStart: total === 0 ? 0 : start + 1,
    rangeEnd: Math.min(start + pageSize, total),
  };
}

export function PaginationBar({
  page,
  pageCount,
  total,
  rawTotal,
  rangeStart,
  rangeEnd,
  onPage,
}: {
  page: number;
  pageCount: number;
  total: number;
  rawTotal: number;
  rangeStart: number;
  rangeEnd: number;
  onPage: (n: number) => void;
}) {
  const filtered = total !== rawTotal;
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-800 bg-slate-900/40 px-3 py-2 text-xs text-slate-400">
      <span>
        {total === 0
          ? "0 of 0"
          : `${rangeStart.toLocaleString()}–${rangeEnd.toLocaleString()} of ${total.toLocaleString()}`}
        {filtered && (
          <span className="ml-1 text-slate-500">
            (filtered from {rawTotal.toLocaleString()})
          </span>
        )}
      </span>
      <div className="flex items-center gap-1">
        <button
          onClick={() => onPage(0)}
          disabled={page === 0}
          className="rounded border border-slate-700 px-2 py-0.5 disabled:opacity-40 hover:bg-slate-800"
          aria-label="First page"
        >
          «
        </button>
        <button
          onClick={() => onPage(page - 1)}
          disabled={page === 0}
          className="rounded border border-slate-700 px-2 py-0.5 disabled:opacity-40 hover:bg-slate-800"
          aria-label="Previous page"
        >
          ‹
        </button>
        <span className="px-1 tabular-nums">
          {page + 1} / {pageCount}
        </span>
        <button
          onClick={() => onPage(page + 1)}
          disabled={page >= pageCount - 1}
          className="rounded border border-slate-700 px-2 py-0.5 disabled:opacity-40 hover:bg-slate-800"
          aria-label="Next page"
        >
          ›
        </button>
        <button
          onClick={() => onPage(pageCount - 1)}
          disabled={page >= pageCount - 1}
          className="rounded border border-slate-700 px-2 py-0.5 disabled:opacity-40 hover:bg-slate-800"
          aria-label="Last page"
        >
          »
        </button>
      </div>
    </div>
  );
}

export function SearchBox({
  value,
  onChange,
  placeholder = "filter…",
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <input
      type="search"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      className="w-full max-w-xs rounded border border-slate-700 bg-slate-950 px-3 py-1.5 text-sm placeholder:text-slate-500 focus:border-violet-500 focus:outline-none"
    />
  );
}
