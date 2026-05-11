"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { clearToken } from "@/lib/auth";

const items = [
  { href: "/", label: "Dashboard" },
  { href: "/repos", label: "Repos" },
  { href: "/sources", label: "Sources" },
  { href: "/search", label: "Search" },
  { href: "/graph", label: "Graph" },
];

export function Navbar() {
  const path = usePathname();
  const router = useRouter();
  return (
    <nav className="border-b border-slate-800 bg-slate-900/60 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-5 py-3">
        <Link href="/" className="font-semibold tracking-tight">
          <span className="text-violet-300">ckg</span>
          <span className="text-slate-400"> · central code knowledge graph</span>
        </Link>
        <div className="flex items-center gap-4 text-sm">
          {items.map((it) => {
            const active = path === it.href || (it.href !== "/" && path.startsWith(it.href));
            return (
              <Link
                key={it.href}
                href={it.href}
                className={
                  "rounded px-2 py-1 transition " +
                  (active ? "bg-slate-800 text-white" : "text-slate-300 hover:text-white")
                }
              >
                {it.label}
              </Link>
            );
          })}
          <button
            onClick={() => {
              clearToken();
              router.replace("/login");
            }}
            className="rounded border border-slate-700 px-2 py-1 text-slate-300 hover:bg-slate-800"
            title="Forget token"
          >
            Sign out
          </button>
        </div>
      </div>
    </nav>
  );
}
