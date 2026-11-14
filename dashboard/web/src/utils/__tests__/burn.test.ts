import { describe, it, expect } from 'vitest';
import { aggregateBurn, aggregateField, burnHeatmap } from '../burn';
import type { MetricRow } from '../../api/types';

const m = (agent: string, s: number, tokens: number, spend = 0): MetricRow =>
  ({ agent_id: agent, state: 'healthy', tokens_per_min: tokens, usd_per_min: tokens / 1000, calls_per_sec: 0, total_tokens: 0, spend_usd: spend, budget_usd: 1, exact_repeats: 0, loop_score: 0, tool_cycle: false, memory_mb: 0, memory_pct: 0, created_at: new Date(Date.UTC(2026, 10, 10, 9, 0, s)).toISOString() }) as MetricRow;

describe('burn aggregation', () => {
  const rows = [m('a', 0, 100, 0.1), m('a', 1, 200, 0.2), m('b', 0, 10, 0.01), m('b', 1, 20, 0.02)];
  it('sums agents per aligned sample, oldest first', () => {
    expect(aggregateBurn(rows).values).toEqual([110, 220]);
  });
  it('works for any numeric field', () => {
    expect(aggregateField(rows, 'spend_usd').values.map((v) => Math.round(v * 100) / 100)).toEqual([0.11, 0.22]);
  });
  it('builds an agents x buckets heatmap of average tokens/min', () => {
    const h = burnHeatmap([m('b', 0, 10), m('b', 1, 30), m('a', 0, 100), m('a', 1, 300)], 2);
    expect(h.rows).toEqual(['a', 'b']);
    expect(h.values).toEqual([[100, 300], [10, 30]]);
    expect(h.cols).toHaveLength(2);
  });
  it('handles no data', () => {
    expect(burnHeatmap([])).toEqual({ rows: [], cols: [], values: [] });
    expect(aggregateBurn([]).values).toEqual([]);
  });
});
