import type { ReactNode } from "react";

export function StatsCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: number | string;
  // Optional secondary line under the headline — pass a string for plain
  // muted text, or a React node when you need inline colour (e.g. the
  // dashboard's success-rate tone).
  hint?: ReactNode;
}) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
      <div className="text-xs uppercase tracking-wider text-slate-400">{label}</div>
      <div className="mt-1 text-2xl font-semibold">{value}</div>
      {hint !== undefined && hint !== null && (
        <div className="mt-1 text-xs text-slate-400">{hint}</div>
      )}
    </div>
  );
}
