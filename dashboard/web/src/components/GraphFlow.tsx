import React, { useMemo } from 'react';
import { ReactFlow, MarkerType, type Node, type Edge } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import type { NodeFeed, NodeFeedItem } from '../api/types';

/* ───────── Pure model (unit-tested) ───────── */

export interface FlowEdge {
  source: string;
  target: string;
  count: number;
  inCycle: boolean;
  dashed?: boolean;
}

export interface FlowModel {
  nodes: string[];
  edges: FlowEdge[];
  loopLabel: string | null;
}

/** Distinct node names in order of first appearance (oldest event first). */
export function orderNodes(feed: NodeFeed): string[] {
  const seen: string[] = [];
  const add = (n: string | null | undefined) => {
    if (n && !seen.includes(n)) seen.push(n);
  };
  [...feed.items].sort((a, b) => a.ts - b.ts).forEach((it) => add(it.node));
  feed.edges.forEach((e) => {
    add(e.source);
    add(e.target);
  });
  add(feed.next_node);
  return seen;
}

/** An edge is in a cycle when its reverse edge (B→A for A→B) also exists. */
export function buildFlowModel(feed: NodeFeed): FlowModel {
  const nodes = orderNodes(feed);
  const key = (a: string, b: string) => `${a}\u0000${b}`;
  const counts = new Map(feed.edges.map((e) => [key(e.source, e.target), e.count]));
  const edges: FlowEdge[] = feed.edges.map((e) => ({
    source: e.source,
    target: e.target,
    count: e.count,
    inCycle: e.source !== e.target && counts.has(key(e.target, e.source)),
  }));

  // dashed edge to the next node when it is not already drawn
  if (feed.last_node && feed.next_node && !counts.has(key(feed.last_node, feed.next_node))) {
    edges.push({ source: feed.last_node, target: feed.next_node, count: 0, inCycle: false, dashed: true });
  }

  let loopLabel: string | null = null;
  for (const e of edges) {
    const back = counts.get(key(e.target, e.source));
    if (e.inCycle && back !== undefined && nodes.indexOf(e.source) < nodes.indexOf(e.target)) {
      loopLabel = `loop: ${e.source} ↔ ${e.target} ×${Math.min(e.count, back)}`;
      break;
    }
  }
  return { nodes, edges, loopLabel };
}

/** `changed` object → one `key: value` per line. */
export function changedLines(changed: Record<string, unknown>): string[] {
  return Object.entries(changed ?? {}).map(
    ([k, v]) => `${k}: ${typeof v === 'string' ? v : JSON.stringify(v)}`
  );
}

export function lastItems(items: NodeFeedItem[], n = 15): NodeFeedItem[] {
  return [...items].sort((a, b) => b.ts - a.ts).slice(0, n);
}

/* ───────── Component ───────── */

const COL_W = 190;

interface GraphFlowProps {
  feed: NodeFeed;
  paused: boolean;
}

export const GraphFlow: React.FC<GraphFlowProps> = ({ feed, paused }) => {
  const model = useMemo(() => buildFlowModel(feed), [feed]);
  const framework = feed.items[0]?.framework ?? 'unknown';

  // Positions depend only on first-appearance order, so the layout never jumps between refreshes
  const nodes: Node[] = useMemo(
    () =>
      model.nodes.map((name, i) => {
        const isLast = name === feed.last_node;
        return {
          id: name,
          position: { x: i * COL_W, y: i % 2 === 0 ? 0 : 36 },
          data: { label: name },
          draggable: false,
          selectable: false,
          style: {
            fontFamily: 'var(--font-mono)',
            fontSize: 12,
            fontWeight: 600,
            color: 'var(--color-text-primary)',
            background: isLast ? 'var(--color-state-probation-bg)' : 'var(--color-surface-elevated)',
            border: `1px solid ${isLast ? 'var(--color-accent)' : 'var(--color-border)'}`,
            borderRadius: 'var(--radius-sm)',
            padding: '6px 12px',
            width: 'auto',
            minWidth: 110,
          },
        } as Node;
      }),
    [model.nodes, feed.last_node]
  );

  const edges: Edge[] = useMemo(
    () =>
      model.edges.map((e) => {
        const color = e.inCycle ? 'var(--color-state-suspicious)' : 'var(--color-text-muted)';
        return {
          id: `${e.source}->${e.target}`,
          source: e.source,
          target: e.target,
          label: e.count > 0 ? String(e.count) : undefined,
          animated: e.inCycle && !paused,
          markerEnd: { type: MarkerType.ArrowClosed, color: e.inCycle ? '#f59e0b' : '#94a3b8' },
          style: {
            stroke: color,
            strokeWidth: e.inCycle ? 3 : 1 + Math.min(3, e.count / 4),
            strokeDasharray: e.dashed ? '5 4' : undefined,
          },
          labelStyle: { fill: 'var(--color-text-primary)', fontFamily: 'var(--font-mono)', fontSize: 11 },
          labelBgStyle: { fill: 'var(--color-canvas)' },
          type: 'default',
        } as Edge;
      }),
    [model.edges, paused]
  );

  const rows = lastItems(feed.items, 15);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
      <div
        data-testid="graph-flow-canvas"
        style={{
          height: 190,
          border: '1px solid var(--color-border)',
          borderRadius: 'var(--radius-md)',
          background: 'var(--color-canvas)',
        }}
      >
        <ReactFlow
          nodes={nodes}
          edges={edges}
          fitView
          fitViewOptions={{ padding: 0.2 }}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={false}
          zoomOnScroll={false}
          panOnDrag={false}
          proOptions={{ hideAttribution: true }}
        />
      </div>

      <div
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 'var(--type-micro-size)',
          color: 'var(--color-text-secondary)',
          display: 'flex',
          gap: 'var(--space-4)',
          flexWrap: 'wrap',
        }}
      >
        <span>framework: {framework}</span>
        {model.loopLabel && (
          <span data-testid="graph-loop-caption" style={{ color: 'var(--color-state-suspicious)', fontWeight: 700 }}>
            {model.loopLabel}
          </span>
        )}
      </div>

      <div style={{ overflowX: 'auto' }}>
        <table
          aria-label="State transitions"
          style={{ width: '100%', borderCollapse: 'collapse', fontSize: 'var(--type-micro-size)' }}
        >
          <caption
            style={{ textAlign: 'left', color: 'var(--color-text-muted)', paddingBottom: 'var(--space-1)' }}
          >
            State transitions (last {rows.length}, newest first)
          </caption>
          <thead>
            <tr style={{ color: 'var(--color-text-muted)', textAlign: 'left' }}>
              {['time', 'step', 'node', 'changed', 'next', 'status'].map((h) => (
                <th key={h} style={{ padding: 'var(--space-1) var(--space-2)', fontWeight: 600 }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((it, i) => (
              <tr key={`${it.trace_id}-${it.step}-${i}`} style={{ borderTop: '1px solid var(--color-border)' }}>
                <td className="tabular-nums" style={{ padding: 'var(--space-1) var(--space-2)' }}>
                  {new Date(it.ts * 1000).toLocaleTimeString()}
                </td>
                <td className="tabular-nums" style={{ padding: 'var(--space-1) var(--space-2)' }}>
                  {it.step}
                </td>
                <td style={{ padding: 'var(--space-1) var(--space-2)', fontFamily: 'var(--font-mono)' }}>
                  {it.node}
                </td>
                <td style={{ padding: 'var(--space-1) var(--space-2)', fontFamily: 'var(--font-mono)' }}>
                  {changedLines(it.changed).map((l) => (
                    <div key={l}>{l}</div>
                  ))}
                </td>
                <td style={{ padding: 'var(--space-1) var(--space-2)', fontFamily: 'var(--font-mono)' }}>{it.next}</td>
                <td
                  style={{
                    padding: 'var(--space-1) var(--space-2)',
                    fontWeight: 700,
                    color: it.status === 'error' ? 'var(--color-state-killed)' : 'var(--color-state-healthy)',
                  }}
                >
                  {it.status}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};
