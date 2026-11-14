import type { GraphEdge, GraphNode, GraphResponse } from '../api/types';

/** Layout for the fleet graph (D13): agents | tools | models, one column each, stable by id. */

export interface PlacedNode extends GraphNode {
  x: number;
  y: number;
}

const COLUMN: Record<GraphNode['kind'], number> = { agent: 0, tool: 1, model: 2 };
export const COL_W = 300;
export const ROW_H = 84;

export function layoutGraph(g: GraphResponse): PlacedNode[] {
  const cols: Record<number, GraphNode[]> = { 0: [], 1: [], 2: [] };
  g.nodes.forEach((n) => cols[COLUMN[n.kind] ?? 1].push(n));
  const tallest = Math.max(1, ...Object.values(cols).map((c) => c.length));
  const out: PlacedNode[] = [];
  Object.entries(cols).forEach(([c, nodes]) => {
    const sorted = [...nodes].sort((a, b) => a.id.localeCompare(b.id));
    const offset = ((tallest - sorted.length) * ROW_H) / 2; // centre short columns
    sorted.forEach((n, i) => out.push({ ...n, x: Number(c) * COL_W, y: offset + i * ROW_H }));
  });
  return out;
}

export function cyclicEdges(edges: GraphEdge[]): GraphEdge[] {
  return edges.filter((e) => e.in_cycle);
}

export function edgeWidth(e: GraphEdge): number {
  return e.in_cycle ? 3 : 1 + Math.min(3, e.count / 10);
}
