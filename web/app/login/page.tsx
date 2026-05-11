"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { setToken } from "@/lib/auth";
import { api, ApiError, API_BASE } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [token, setTok] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    setToken(token);
    try {
      // Verify by calling a token-required endpoint.
      await api.stats();
      router.replace("/");
    } catch (err) {
      const status = err instanceof ApiError ? err.status : undefined;
      setError(
        status === 401 || status === 403
          ? "Token rejected. Mint one with `ckg token create …` and try again."
          : `Could not reach the API (${(err as Error).message}). Is ${API_BASE} up?`,
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <form
        onSubmit={onSubmit}
        className="w-full max-w-md space-y-5 rounded-2xl border border-slate-800 bg-slate-900 p-6 shadow-xl"
      >
        <div>
          <h1 className="text-xl font-semibold">Sign in to ckg</h1>
          <p className="mt-1 text-sm text-slate-400">
            Paste an API token (starts with <span className="font-mono">ckg_</span>). It is saved to
            this browser only.
          </p>
        </div>
        <input
          autoFocus
          type="password"
          placeholder="ckg_…"
          value={token}
          onChange={(e) => setTok(e.target.value)}
          className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-sm focus:border-violet-400 focus:outline-none"
        />
        {error && (
          <div className="rounded border border-red-800 bg-red-950/50 px-3 py-2 text-sm text-red-300">
            {error}
          </div>
        )}
        <button
          type="submit"
          disabled={busy || !token.trim()}
          className="w-full rounded-md bg-violet-500 px-3 py-2 font-medium text-violet-50 disabled:opacity-50 hover:bg-violet-400"
        >
          {busy ? "Checking…" : "Sign in"}
        </button>
        <p className="text-xs text-slate-500">
          API: <span className="font-mono">{API_BASE}</span>
        </p>
      </form>
    </div>
  );
}
