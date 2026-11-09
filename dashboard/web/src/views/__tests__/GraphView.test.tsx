import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { GraphView } from '../GraphView';
import { layoutGraph, cyclicEdges, edgeWidth, COL_W } from '../../utils/fleetGraph';
import { api } from '../../api/client';
import type { GraphResponse } from '../../api/types';

const graph: GraphResponse = {
  nodes: [
    { id: 'beta', kind: 'agent', label: 'beta' },
    { id: 'alpha', kind: 'agent', label: 'alpha' },
    { id: 'tool:orders_api', kind: 'tool', label: 'orders_api' },
    { id: 'model:sim', kind: 'model', label: 'sim' },
  ],
  edges: [
    { source: 'alpha', target: 'model:sim', count: 20, in_cycle: false },
    { source: 'beta', target: 'tool:orders_api', count: 40, in_cycle: true },
  ],
};

describe('fleet graph layout', () => {
  it('puts agents, tools and models in their own columns, sorted by id', () => {
    const placed = layoutGraph(graph);
    const byId = Object.fromEntries(placed.map((n) => [n.id, n]));
    expect(byId.alpha.x).toBe(0);
    expect(byId['tool:orders_api'].x).toBe(COL_W);
    expect(byId['model:sim'].x).toBe(COL_W * 2);
    expect(byId.alpha.y).toBeLessThan(byId.beta.y);
  });

  it('finds cyclic edges and makes them thicker', () => {
    expect(cyclicEdges(graph.edges).map((e) => e.source)).toEqual(['beta']);
    expect(edgeWidth(graph.edges[1])).toBe(3);
    expect(edgeWidth(graph.edges[0])).toBeLessThan(3.5);
    expect(edgeWidth({ ...graph.edges[0], count: 1 })).toBeCloseTo(1.1);
  });
});

describe('GraphView', () => {
  const wrap = () =>
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <GraphView />
      </QueryClientProvider>
    );

  it('reports the cyclic edge', async () => {
    vi.spyOn(api, 'getGraph').mockResolvedValue(graph);
    wrap();
    expect(await screen.findByTestId('fleet-graph-cycles')).toHaveTextContent('1 cyclic edge: beta → tool:orders_api');
  });

  it('shows the empty state', async () => {
    vi.spyOn(api, 'getGraph').mockResolvedValue({ nodes: [], edges: [] });
    wrap();
    expect(await screen.findByText('No Graph Yet')).toBeInTheDocument();
  });
});
