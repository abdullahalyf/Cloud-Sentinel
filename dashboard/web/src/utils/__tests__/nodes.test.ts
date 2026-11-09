import { describe, it, expect } from 'vitest';
import { nodeOf, groupByNode, hasNodes } from '../nodes';
import type { AgentView } from '../../api/types';

const a = (id: string, runtime: string) => ({ agent_id: id, runtime }) as AgentView;

describe('node grouping (D15)', () => {
  it('reads the node from docker@<node>', () => {
    expect(nodeOf('docker@node-2')).toBe('node-2');
    expect(nodeOf('docker')).toBeNull();
    expect(nodeOf('docker@')).toBeNull();
  });

  it('groups agents by node, sorted, with unassigned last', () => {
    const groups = groupByNode([a('x', 'docker'), a('b', 'docker@n2'), a('a', 'docker@n1'), a('c', 'k8s@n1')]);
    expect(groups.map((g) => g.node)).toEqual(['n1', 'n2', 'unassigned']);
    expect(groups[0].agents.map((g) => g.agent_id)).toEqual(['a', 'c']);
  });

  it('hasNodes is false on a single-node fleet', () => {
    expect(hasNodes([a('x', 'docker'), a('y', 'mock')])).toBe(false);
    expect(hasNodes([a('x', 'docker@n1')])).toBe(true);
  });
});
