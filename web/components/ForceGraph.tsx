"use client";

import dynamic from "next/dynamic";
import type { ComponentType } from "react";

// react-force-graph-2d uses canvas + DOM APIs — must be browser-only.
const ForceGraph2D = dynamic(
  () => import("react-force-graph-2d").then((m) => m.default as ComponentType<ForceGraphProps>),
  { ssr: false, loading: () => <div className="text-slate-400">Loading graph engine…</div> },
);

export type GraphNode = { id: string; kind?: "fn" | "file" | "cls" | "self"; label?: string };
export type GraphLink = { source: string; target: string };
export type ForceGraphProps = {
  graphData: { nodes: GraphNode[]; links: GraphLink[] };
  width?: number;
  height?: number;
  nodeRelSize?: number;
  nodeCanvasObject?: (node: GraphNode, ctx: CanvasRenderingContext2D, globalScale: number) => void;
  nodePointerAreaPaint?: (node: GraphNode, color: string, ctx: CanvasRenderingContext2D) => void;
  linkColor?: () => string;
  linkDirectionalArrowLength?: number;
  linkDirectionalArrowRelPos?: number;
  cooldownTicks?: number;
};

export function FunctionGraph({
  data,
  height = 540,
}: {
  data: { nodes: GraphNode[]; links: GraphLink[] };
  height?: number;
}) {
  return (
    <div className="relative overflow-hidden rounded-lg border border-slate-800 bg-slate-950">
      <ForceGraph2D
        graphData={data}
        height={height}
        nodeRelSize={5}
        linkColor={() => "rgba(148,163,184,0.3)"}
        linkDirectionalArrowLength={4}
        linkDirectionalArrowRelPos={0.95}
        cooldownTicks={120}
        nodeCanvasObject={(node, ctx, scale) => {
          const n = node as GraphNode & { x?: number; y?: number };
          const color =
            n.kind === "self"
              ? "#a78bfa"
              : n.kind === "file"
                ? "#60a5fa"
                : n.kind === "cls"
                  ? "#f59e0b"
                  : "#34d399";
          ctx.fillStyle = color;
          ctx.beginPath();
          ctx.arc(n.x ?? 0, n.y ?? 0, 5, 0, 2 * Math.PI);
          ctx.fill();
          if (scale >= 1.5 && n.label) {
            ctx.font = `${12 / scale}px ui-monospace`;
            ctx.fillStyle = "#e2e8f0";
            ctx.fillText(n.label, (n.x ?? 0) + 7, (n.y ?? 0) + 4);
          }
        }}
        nodePointerAreaPaint={(node, color, ctx) => {
          const n = node as GraphNode & { x?: number; y?: number };
          ctx.fillStyle = color;
          ctx.beginPath();
          ctx.arc(n.x ?? 0, n.y ?? 0, 8, 0, 2 * Math.PI);
          ctx.fill();
        }}
      />
    </div>
  );
}
