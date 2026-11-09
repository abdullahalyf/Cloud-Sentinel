import React, { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ReactFlow, MarkerType, Position, type Edge, type Node } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { Network } from 'lucide-react';
import { api } from '../api/client';
import { Panel } from '../components/Panel';
import { livePoll } from '../utils/live';
import { cyclicEdges, edgeWidth, layoutGraph } from '../utils/fleetGraph';

const KIND_BORDER: Record<string, string> = {
  agent: 'var(--color-accent)',
  tool: 'var(--color-state-paused)',
  model: 'var(--color-state-healthy)',
};

export const GraphView: React.FC = () => {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['graph', 2],
    queryFn: () => api.getGraph(2),
    refetchInterval: livePoll,
  });

  const nodes: Node[] = useMemo(
    () =>
      layoutGraph(data ?? { nodes: [], edges: [] }).map((n) => ({
        id: n.id,
        position: { x: n.x, y: n.y },
        data: { label: `${n.kind}: ${n.label}` },
        draggable: false,
        selectable: false,
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
        style: {
          fontFamily: 'var(--font-mono)',
          fontSize: 12,
          fontWeight: 600,
          color: 'var(--color-text-primary)',
          background: 'var(--color-surface-elevated)',
          border: `1px solid ${KIND_BORDER[n.kind] ?? 'var(--color-border)'}`,
          borderRadius: 'var(--radius-sm)',
          padding: '8px 14px',
          minWidth: 150,
        },
      })) as Node[],
    [data]
  );

  const edges: Edge[] = useMemo(
    () =>
      (data?.edges ?? []).map((e) => ({
        id: `${e.source}->${e.target}`,
        source: e.source,
        target: e.target,
        label: String(e.count),
        animated: e.in_cycle,
        markerEnd: { type: MarkerType.ArrowClosed, color: e.in_cycle ? '#f59e0b' : '#94a3b8' },
        style: {
          stroke: e.in_cycle ? 'var(--color-state-suspicious)' : 'var(--color-text-muted)',
          strokeWidth: edgeWidth(e),
        },
        labelStyle: { fill: 'var(--color-text-primary)', fontFamily: 'var(--font-mono)', fontSize: 11 },
        labelBgStyle: { fill: 'var(--color-canvas)' },
      })) as Edge[],
    [data]
  );

  const cycles = cyclicEdges(data?.edges ?? []);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-6)', width: '100%' }}>
      <header>
        <h1 style={{ fontSize: 'var(--type-title-sm-size)', fontWeight: 700, color: 'var(--color-text-primary)' }}>
          Fleet Graph
        </h1>
        <p style={{ fontSize: 'var(--type-body-sm-size)', color: 'var(--color-text-secondary)', marginTop: 'var(--space-1)' }}>
          Which agents call which tools and models, over the last 2 minutes. Cycles are highlighted.
        </p>
      </header>

      <Panel
        title="Agents, Tools & Models"
        icon={<Network size={18} />}
        loading={isLoading}
        error={error}
        empty={!data || data.nodes.length === 0}
        emptyTitle="No Graph Yet"
        emptyMessage="Agents, tools and models appear here once spans arrive from the collector."
        onRetry={() => refetch()}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
          <div
            data-testid="fleet-graph-canvas"
            style={{ height: 460, border: '1px solid var(--color-border)', borderRadius: 'var(--radius-md)', background: 'var(--color-canvas)' }}
          >
            <ReactFlow
              nodes={nodes}
              edges={edges}
              fitView
              fitViewOptions={{ padding: 0.15 }}
              nodesDraggable={false}
              nodesConnectable={false}
              elementsSelectable={false}
              zoomOnScroll={false}
              panOnDrag={false}
              proOptions={{ hideAttribution: true }}
            />
          </div>
          <div style={{ display: 'flex', gap: 'var(--space-4)', flexWrap: 'wrap', fontFamily: 'var(--font-mono)', fontSize: 'var(--type-micro-size)', color: 'var(--color-text-secondary)' }}>
            <span>agents → tools / models</span>
            <span data-testid="fleet-graph-cycles" style={{ color: cycles.length ? 'var(--color-state-suspicious)' : undefined, fontWeight: cycles.length ? 700 : 400 }}>
              {cycles.length === 0
                ? 'no cycles'
                : `${cycles.length} cyclic edge${cycles.length === 1 ? '' : 's'}: ${cycles.map((c) => `${c.source} → ${c.target}`).join(', ')}`}
            </span>
          </div>
        </div>
      </Panel>
    </div>
  );
};
