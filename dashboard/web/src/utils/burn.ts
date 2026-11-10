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
  return aggregateField(metrics, 'tokens_per_min', max);
}

type NumericField = 'tokens_per_min' | 'usd_per_min' | 'spend_usd' | 'loop_score' | 'calls_per_sec';

/** Same alignment as aggregateBurn, for any numeric metric field. */
export function aggregateField(metrics: MetricRow[], field: NumericField, max = 40): BurnSeries {
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
        sum += (row[field] as number) || 0;
        label = label || new Date(row.created_at).toLocaleTimeString();
      }
    });
    values.push(sum);
    labels.push(label);
  }
  return { values, labels };
}

/** Agents x time buckets of average tokens/min, for the "when agents burn" heatmap. */
export function burnHeatmap(metrics: MetricRow[], cols = 8): { rows: string[]; cols: string[]; values: number[][] } {
  const byAgent = new Map<string, MetricRow[]>();
  metrics.forEach((m) => byAgent.set(m.agent_id, [...(byAgent.get(m.agent_id) ?? []), m]));
  const rows = [...byAgent.keys()].sort();
  const longest = Math.max(0, ...[...byAgent.values()].map((l) => l.length));
  const n = Math.min(cols, longest);
  const labels: string[] = Array.from({ length: n }, () => '');
  const values = rows.map((id) => {
    const list = [...(byAgent.get(id) ?? [])].sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());
    const out: number[] = [];
    for (let c = 0; c < n; c++) {
      const from = Math.floor((c * list.length) / n);
      const to = Math.max(from + 1, Math.floor(((c + 1) * list.length) / n));
      const slice = list.slice(from, to);
      out.push(slice.length ? slice.reduce((s, m) => s + (m.tokens_per_min || 0), 0) / slice.length : 0);
      const lastRow = slice[slice.length - 1];
      if (lastRow && !labels[c]) labels[c] = new Date(lastRow.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }
    return out;
  });
  return { rows, cols: labels, values };
}
