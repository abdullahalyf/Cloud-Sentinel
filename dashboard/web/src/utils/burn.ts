import type { MetricRow } from '../api/types';

/**
 * Fleet burn velocity from real metric rows: per agent sort by time, align the series from the
 * newest sample backwards, and add the agents up (tokens per minute). Nothing is invented: if there
 * are fewer than two samples the caller shows an empty state.
 */
export interface BurnSeries {
  values: number[];
  labels: string[];
}

export function aggregateBurn(metrics: MetricRow[], max = 40): BurnSeries {
  const byAgent = new Map<string, MetricRow[]>();
  metrics.forEach((m) => byAgent.set(m.agent_id, [...(byAgent.get(m.agent_id) ?? []), m]));
  const lists = [...byAgent.values()].map((rows) =>
    [...rows].sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime())
  );
  const len = Math.min(max, Math.max(0, ...lists.map((l) => l.length)));
  const values: number[] = [];
  const labels: string[] = [];
  for (let k = len; k >= 1; k--) {
    let sum = 0;
    let label = '';
    lists.forEach((l) => {
      const row = l[l.length - k];
      if (row) {
        sum += row.tokens_per_min || 0;
        label = label || new Date(row.created_at).toLocaleTimeString();
      }
    });
    values.push(sum);
    labels.push(label);
  }
  return { values, labels };
}
