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

export interface Marker {
  ts: number;
  label: string;
  count: number;
}

/**
 * Turns the raw PAUSE/KILL markers into something readable: keeps only those inside [from, to] and
 * merges markers closer than `minGapFrac` of the visible span into one ("3 stops"), so labels never
 * print on top of each other.
 */
export function clusterMarkers(markers: { ts: number; label: string }[], from: number, to: number, minGapFrac = 0.1): Marker[] {
  const span = Math.max(1, to - from);
  const inside = markers.filter((m) => m.ts >= from && m.ts <= to).sort((a, b) => a.ts - b.ts);
  const groups: { ts: number; label: string }[][] = [];
  inside.forEach((m) => {
    const g = groups[groups.length - 1];
    if (g && m.ts - g[g.length - 1].ts < span * minGapFrac) g.push(m);
    else groups.push([m]);
  });
  return groups.map((g) => ({ ts: g[0].ts, label: g.length === 1 ? g[0].label : `${g.length} stops`, count: g.length }));
}

/** The visible time window: from the first sample to the last, plus room on the right for the projection. */
export function viewWindow(series: Point[][]): { from: number; to: number; max: number } | null {
  const ts = series.flat().map((p) => p[0]);
  if (ts.length === 0) return null;
  const from = Math.min(...ts);
  const to = Math.max(...ts);
  const room = Math.max(5 * 60_000, (to - from) * 0.35);
  return { from, to, max: to + room };
}

/** Cuts a projection at the right edge of the view (the line is straight, so this is a simple interpolation). */
export function clipProjection(proj: [Point, Point] | null, maxTs: number): [Point, Point] | null {
  if (!proj) return null;
  const [a, b] = proj;
  if (b[0] <= maxTs) return proj;
  if (a[0] >= maxTs) return null;
  const k = (maxTs - a[0]) / (b[0] - a[0]);
  return [a, [maxTs, a[1] + (b[1] - a[1]) * k]];
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
