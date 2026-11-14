import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { GraphFlow, buildFlowModel, orderNodes, lastItems, changedLines } from '../GraphFlow';
import type { NodeFeed, NodeFeedItem } from '../../api/types';

const item = (ts: number, node: string, next: string, step: number): NodeFeedItem => ({
  ts,
  node,
  next,
  step,
  framework: 'langgraph',
  changed: { order: 'x' },
  status: 'ok',
  duration_ms: 5,
  trace_id: 't1',
});

const refundFeed: NodeFeed = {
  items: [
    item(1, 'classify', 'lookup_order', 1),
    item(2, 'lookup_order', 'decide', 2),
    item(3, 'decide', 'refund', 3),
  ],
  edges: [
    { source: 'classify', target: 'lookup_order', count: 4 },
    { source: 'lookup_order', target: 'decide', count: 4 },
    { source: 'decide', target: 'refund', count: 3 },
  ],
  last_node: 'decide',
  next_node: 'refund',
};

const loopFeed: NodeFeed = {
  items: [item(1, 'lookup_order', 'retry', 1), item(2, 'retry', 'lookup_order', 2)],
  edges: [
    { source: 'lookup_order', target: 'retry', count: 9 },
    { source: 'retry', target: 'lookup_order', count: 8 },
  ],
  last_node: 'retry',
  next_node: 'lookup_order',
};

describe('GraphFlow model', () => {
  it('orders nodes by first appearance', () => {
    expect(orderNodes(refundFeed)).toEqual(['classify', 'lookup_order', 'decide', 'refund']);
  });

  it('does not flag a straight line as a cycle and caption is empty', () => {
    const m = buildFlowModel(refundFeed);
    expect(m.edges.every((e) => !e.inCycle)).toBe(true);
    expect(m.loopLabel).toBeNull();
  });

  it('detects A↔B cycles and builds the loop caption', () => {
    const m = buildFlowModel(loopFeed);
    expect(m.edges.filter((e) => e.inCycle)).toHaveLength(2);
    expect(m.loopLabel).toBe('loop: lookup_order ↔ retry ×8');
  });

  it('adds a dashed edge to next_node when it is not drawn yet', () => {
    const m = buildFlowModel(refundFeed);
    const dashed = m.edges.find((e) => e.dashed);
    expect(dashed).toBeUndefined(); // decide→refund already exists
    const m2 = buildFlowModel({ ...refundFeed, last_node: 'refund', next_node: 'classify' });
    expect(m2.edges.find((e) => e.dashed)).toMatchObject({ source: 'refund', target: 'classify' });
  });

  it('keeps newest 15 items, newest first, and formats changed lines', () => {
    const many = Array.from({ length: 20 }, (_, i) => item(i, 'a', 'b', i));
    const rows = lastItems(many);
    expect(rows).toHaveLength(15);
    expect(rows[0].step).toBe(19);
    expect(changedLines({ a: 'x', b: 2 })).toEqual(['a: x', 'b: 2']);
  });
});

describe('GraphFlow component', () => {
  it('renders framework, loop caption and the transitions table', () => {
    render(<GraphFlow feed={loopFeed} paused={false} />);
    expect(screen.getByText('framework: langgraph')).toBeInTheDocument();
    expect(screen.getByTestId('graph-loop-caption')).toHaveTextContent('lookup_order ↔ retry');
    expect(screen.getByRole('table', { name: /state transitions/i })).toBeInTheDocument();
  });
});
