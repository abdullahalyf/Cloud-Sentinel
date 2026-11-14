import { describe, it, expect } from 'vitest';
import { budgetLeftSeries, projectToZero, actionMarkers, taskRowsByWasted, clusterMarkers, viewWindow, clipProjection } from '../burndown';
import type { ActionRow, MetricRow, TaskStats } from '../../api/types';

const m = (agent: string, iso: string, spend: number, budget = 1): MetricRow => ({
  agent_id: agent,
  state: 'healthy',
  tokens_per_min: 0,
  usd_per_min: 0,
  calls_per_sec: 0,
  total_tokens: 0,
  spend_usd: spend,
  budget_usd: budget,
  exact_repeats: 0,
  loop_score: 0,
  tool_cycle: false,
  memory_mb: 0,
  memory_pct: 0,
  created_at: iso,
});

describe('burn-down math', () => {
  it('budget left = budget − spend, per agent, oldest first', () => {
    const s = budgetLeftSeries(
      [m('a', '2026-11-08T10:01:00Z', 0.4), m('b', '2026-11-08T10:00:00Z', 0.9), m('a', '2026-11-08T10:00:00Z', 0.2)],
      'a'
    );
    expect(s.map((p) => Math.round(p[1] * 100) / 100)).toEqual([0.8, 0.6]);
    expect(s[0][0]).toBeLessThan(s[1][0]);
  });

  it('projects to zero at the current $/min', () => {
    const t = Date.parse('2026-11-08T10:00:00Z');
    const proj = projectToZero([[t, 0.5]], 0.1);
    expect(proj).not.toBeNull();
    expect(proj![0]).toEqual([t, 0.5]);
    expect(proj![1][0]).toBe(t + 5 * 60_000); // 0.5 / 0.1 = 5 minutes
    expect(proj![1][1]).toBe(0);
  });

  it('no projection for a flat (paused) agent, empty data, or an empty budget', () => {
    const t = Date.now();
    expect(projectToZero([[t, 0.5]], 0)).toBeNull();
    expect(projectToZero([], 0.1)).toBeNull();
    expect(projectToZero([[t, 0]], 0.1)).toBeNull();
  });

  it('caps very slow burns at 120 minutes', () => {
    const t = 0;
    const proj = projectToZero([[t, 1]], 0.001)!;
    expect(proj[1][0]).toBe(120 * 60_000);
    expect(proj[1][1]).toBeGreaterThan(0);
  });

  it('markers keep only PAUSE and KILL', () => {
    const acts = [
      { id: 1, agent_id: 'beta', action: 'PAUSE', actor: 'claude', reason: '', usd_saved_estimate: 1, created_at: '2026-11-08T10:00:00Z' },
      { id: 2, agent_id: 'beta', action: 'RESUME', actor: 'human', reason: '', usd_saved_estimate: 0, created_at: '2026-11-08T10:01:00Z' },
      { id: 3, agent_id: 'gamma', action: 'KILL', actor: 'rules', reason: '', usd_saved_estimate: 1, created_at: '2026-11-08T10:02:00Z' },
    ] as ActionRow[];
    expect(actionMarkers(acts).map((x) => x.label)).toEqual(['PAUSE beta', 'KILL gamma']);
  });

  it('sorts task rows by wasted $ and handles missing data', () => {
    const base = { tasks: 1, succeeded: 1, failed: 0, abandoned: 0, success_rate: 1, spend_usd: 0, unattributed_usd: 0, cost_per_success_usd: 0 };
    const rows = taskRowsByWasted({
      alpha: { ...base, wasted_usd: 0 },
      beta: { ...base, wasted_usd: 0.011 },
      delta: { ...base, wasted_usd: 0.002 },
    } as Record<string, TaskStats>);
    expect(rows.map((r) => r.agent)).toEqual(['beta', 'delta', 'alpha']);
    expect(taskRowsByWasted(undefined)).toEqual([]);
  });

  it('merges markers that are close together into one labelled marker and drops those outside the window', () => {
    const min = 60_000;
    const m = (t: number, label: string) => ({ ts: t * min, label });
    const out = clusterMarkers([m(1, 'KILL a'), m(1.2, 'KILL b'), m(1.4, 'PAUSE c'), m(20, 'KILL d'), m(500, 'KILL far')], 0, 30 * min);
    expect(out).toEqual([
      { ts: 1 * min, label: '3 stops', count: 3 },
      { ts: 20 * min, label: 'KILL d', count: 1 },
    ]);
  });

  it('builds the view window with room on the right, and clips a projection at its edge', () => {
    const t0 = 0;
    const t1 = 30 * 60_000;
    const win = viewWindow([[[t0, 1], [t1, 0.5]], []])!;
    expect(win.from).toBe(t0);
    expect(win.to).toBe(t1);
    expect(win.max).toBeGreaterThan(win.to);
    expect(viewWindow([[]])).toBeNull();

    const proj: [[number, number], [number, number]] = [[t1, 1], [t1 + 120 * 60_000, 0]];
    const clipped = clipProjection(proj, win.max)!;
    expect(clipped[1][0]).toBe(win.max);
    expect(clipped[1][1]).toBeGreaterThan(0); // not at $0 yet: it runs past the edge
    expect(clipProjection(proj, t1 + 1)![1][0]).toBe(t1 + 1);
    expect(clipProjection(null, 5)).toBeNull();
    expect(clipProjection([[10, 1], [20, 0]], 5)).toBeNull();
  });
});
