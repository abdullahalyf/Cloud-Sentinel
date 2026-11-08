import { describe, it, expect } from 'vitest';
import { budgetLeftSeries, projectToZero, actionMarkers, taskRowsByWasted } from '../burndown';
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
});
