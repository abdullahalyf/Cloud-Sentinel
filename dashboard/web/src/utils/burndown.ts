import type { ActionRow, MetricRow, TaskStats } from '../api/types';

/** Pure math for the /cost burn-down chart (D7). Unit-tested in lib/__tests__. */

export type Point = [number, number]; // [epoch ms, dollars left]

const MAX_PROJECTION_MIN = 120;

/** Budget left over time for one agent: budget_usd minus cumulative spend_usd, oldest first. */
export function budgetLeftSeries(metrics: MetricRow[], agentId: string): Point[] {
  return metrics
    .filter((m) => m.agent_id === agentId)
    .map((m) => [new Date(m.created_at).getTime(), m.budget_usd - m.spend_usd] as Point)
    .filter(([t]) => Number.isFinite(t))
    .sort((a, b) => a[0] - b[0]);
}

/**
 * Dashed projection from the newest point to the moment the budget hits 0 at the current $/min.
 * Returns null when nothing is burning (paused/flat agents) or the budget is already gone.
 */
export function projectToZero(series: Point[], usdPerMin: number): [Point, Point] | null {
  if (series.length === 0) return null;
  const [t, left] = series[series.length - 1];
  if (!(usdPerMin > 0) || !(left > 0)) return null;
  const minutes = Math.min(left / usdPerMin, MAX_PROJECTION_MIN);
  const endLeft = Math.max(0, left - minutes * usdPerMin);
  return [
    [t, left],
    [t + minutes * 60_000, endLeft],
  ];
}

/** Vertical markers for PAUSE / KILL actions. */
export function actionMarkers(actions: ActionRow[]): { ts: number; label: string }[] {
  return actions
    .filter((a) => a.action === 'PAUSE' || a.action === 'KILL')
    .map((a) => ({ ts: new Date(a.created_at).getTime(), label: `${a.action} ${a.agent_id}` }))
    .filter((m) => Number.isFinite(m.ts));
}

export interface TaskRow extends TaskStats {
  agent: string;
}

/** Table rows sorted by wasted $ (highest first), then agent name. */
export function taskRowsByWasted(tasks: Record<string, TaskStats> | undefined): TaskRow[] {
  return Object.entries(tasks ?? {})
    .map(([agent, s]) => ({ agent, ...s }))
    .sort((a, b) => b.wasted_usd - a.wasted_usd || a.agent.localeCompare(b.agent));
}
