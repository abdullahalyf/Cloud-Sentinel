import { describe, it, expect } from 'vitest';
import { buildIncidents, stateAt } from '../incidents';
import type { ActionRow, AlertRow, MemoryRow, MetricRow, VerdictRow } from '../../api/types';

const iso = (s: number) => new Date(Date.UTC(2026, 10, 8, 3, 0, s)).toISOString();
const t = (s: number) => Date.UTC(2026, 10, 8, 3, 0, s);

const alert = (s: number, agent = 'beta'): AlertRow => ({ id: s, agent_id: agent, severity: 'warning', rule: 'loop', message: 'looping', created_at: iso(s) });
const verdict = (s: number, agent = 'beta'): VerdictRow => ({ agent_id: agent, source: 'claude', action: 'PAUSE', confidence: 0.9, pattern: 'p', reason: 'r', created_at: iso(s) });
const action = (s: number, name: string, agent = 'beta', usd = 0): ActionRow => ({ id: s, agent_id: agent, action: name, actor: 'x', reason: '', usd_saved_estimate: usd, created_at: iso(s) });
const mem = (s: number, version: number): MemoryRow => ({ agent_id: 'beta', version, content: {}, edited_by: 'human', reason: 'fix', created_at: iso(s) });
const metric = (s: number, state: string, loop: number): MetricRow =>
  ({ agent_id: 'beta', state, tokens_per_min: 0, usd_per_min: s / 100, calls_per_sec: 0, total_tokens: 0, spend_usd: 0, budget_usd: 1, exact_repeats: 0, loop_score: loop, tool_cycle: false, memory_mb: 0, memory_pct: 0, created_at: iso(s) }) as MetricRow;

describe('buildIncidents', () => {
  it('groups events of one agent with gaps up to 60 s into one incident', () => {
    const inc = buildIncidents([action(20, 'PAUSE')], [verdict(10)], [alert(0)]);
    expect(inc).toHaveLength(1);
    expect(inc[0].events.map((e) => e.kind)).toEqual(['alert', 'verdict', 'action']);
    expect(inc[0].start).toBe(t(0));
    expect(inc[0].end).toBe(t(20));
  });

  it('splits on a gap longer than 60 s and keeps agents apart; newest first', () => {
    const inc = buildIncidents([action(200, 'KILL', 'gamma', 5)], [], [alert(0), alert(30), alert(100)]);
    const beta = inc.filter((i) => i.agent_id === 'beta');
    expect(beta).toHaveLength(2); // 0..30, then 100 (gap 70 s)
    expect(inc.some((i) => i.agent_id === 'gamma')).toBe(true);
    expect(inc[0].start).toBeGreaterThan(inc[inc.length - 1].start);
  });

  it('derives outcome and saved $', () => {
    expect(buildIncidents([action(0, 'KILL', 'gamma', 129.6)], [], [])[0]).toMatchObject({ outcome: 'killed', saved_usd: 129.6 });
    expect(buildIncidents([action(0, 'PAUSE', 'beta', 2.52)], [], [])[0]).toMatchObject({ outcome: 'paused', saved_usd: 2.52 });
    expect(buildIncidents([action(0, 'PAUSE'), action(30, 'RESUME')], [], [])[0].outcome).toBe('healed');
  });

  it('puts memory edits on the timeline', () => {
    const inc = buildIncidents([action(0, 'PAUSE')], [], [], { beta: [mem(15, 2)] });
    expect(inc[0].events.map((e) => e.kind)).toEqual(['action', 'memory']);
  });
});

describe('stateAt', () => {
  const metrics = [metric(0, 'healthy', 0.1), metric(20, 'suspicious', 0.6), metric(40, 'paused', 0.9), metric(60, 'probation', 0.2)];
  const verdicts = [verdict(30)];
  const memory = [mem(0, 1), mem(50, 2)];

  it('returns the newest sample at or before t', () => {
    expect(stateAt(t(25), 'beta', metrics, verdicts, memory)).toMatchObject({ state: 'suspicious', loop_score: 0.6 });
    expect(stateAt(t(45), 'beta', metrics, verdicts, memory).state).toBe('paused');
    expect(stateAt(t(60), 'beta', metrics, verdicts, memory).state).toBe('probation');
  });

  it('shows the verdict and memory version only after they existed', () => {
    const early = stateAt(t(10), 'beta', metrics, verdicts, memory);
    expect(early.verdict).toBeNull();
    expect(early.memory_version).toBe(1);
    const late = stateAt(t(55), 'beta', metrics, verdicts, memory);
    expect(late.verdict?.action).toBe('PAUSE');
    expect(late.memory_version).toBe(2);
  });

  it('falls back to the first sample before data starts and handles no data', () => {
    expect(stateAt(t(-100), 'beta', metrics, verdicts, memory).state).toBe('healthy');
    expect(stateAt(t(0), 'beta', [], [], [])).toMatchObject({ state: 'unknown', usd_per_min: null, verdict: null, memory_version: null });
  });
});
