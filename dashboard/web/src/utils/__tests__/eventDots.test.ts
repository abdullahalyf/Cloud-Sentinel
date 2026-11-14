import { describe, it, expect } from 'vitest';
import { buildEventDots, dotCard, legendFor, valueAt, styleOf, type Point } from '../eventDots';
import type { ActionRow } from '../../api/types';

const MIN = 60_000;
const iso = (m: number) => new Date(Date.UTC(2026, 10, 13, 9, 0, 0) + m * MIN).toISOString();
const act = (id: number, agent: string, action: string, m: number, extra: Partial<ActionRow> = {}): ActionRow => ({
  id,
  agent_id: agent,
  action,
  actor: 'rules',
  reason: 'because',
  usd_saved_estimate: 0,
  created_at: iso(m),
  ...extra,
});
const T0 = Date.UTC(2026, 10, 13, 9, 0, 0);
const line: Point[] = [[T0, 1], [T0 + 10 * MIN, 0.8], [T0 + 20 * MIN, 0.5]];

describe('event dots', () => {
  it('finds the line value at a time (newest sample at or before it)', () => {
    expect(valueAt(line, T0 + 5 * MIN)).toBe(1);
    expect(valueAt(line, T0 + 15 * MIN)).toBe(0.8);
    expect(valueAt(line, T0 - MIN)).toBe(1);
    expect(valueAt([], T0)).toBeNull();
  });

  it('puts one dot per event on that agent line, coloured by the kind', () => {
    const dots = buildEventDots([act(1, 'beta', 'PAUSE', 12), act(2, 'beta', 'KILL', 25)], { beta: line }, T0, T0 + 30 * MIN);
    expect(dots).toHaveLength(2);
    expect(dots[0]).toMatchObject({ agent_id: 'beta', kind: 'PAUSE', value: 0.8, color: styleOf('PAUSE')!.color, count: 1 });
    expect(dots[1]).toMatchObject({ kind: 'KILL', value: 0.5, color: styleOf('KILL')!.color });
  });

  it('merges events of one agent that are close together, keeping the most serious colour; agents stay apart', () => {
    const dots = buildEventDots(
      [act(1, 'beta', 'RESTART', 5), act(2, 'beta', 'KILL', 5.3), act(3, 'beta', 'MEMORY_EDIT', 5.5), act(4, 'gamma', 'KILL', 5.3)],
      { beta: line, gamma: line },
      T0,
      T0 + 30 * MIN
    );
    const beta = dots.find((d) => d.agent_id === 'beta')!;
    expect(beta.count).toBe(3);
    expect(beta.kind).toBe('KILL');
    expect(dots.filter((d) => d.agent_id === 'gamma')).toHaveLength(1);
  });

  it('skips system actions, unknown kinds, events outside the window and agents with no line', () => {
    const dots = buildEventDots(
      [act(1, '', 'POLICY_RELOAD', 5), act(2, 'beta', 'SOMETHING_NEW', 5), act(3, 'beta', 'KILL', 500), act(4, 'ghost', 'KILL', 5)],
      { beta: line },
      T0,
      T0 + 30 * MIN
    );
    expect(dots).toEqual([]);
  });

  it('describes a dot in plain language, with saved $ and the reason', () => {
    const d = buildEventDots([act(1, 'beta', 'KILL', 5, { usd_saved_estimate: 2.5, reason: 'Hard limit: spent $0.50 of $0.50 budget' })], { beta: line }, T0, T0 + 30 * MIN)[0];
    const card = dotCard(d);
    expect(card.title).toBe('beta: Kill');
    expect(card.meaning).toMatch(/stopped this agent for good/);
    expect(card.lines[0]).toMatch(/Kill · saved \$2\.50 — Hard limit/);
  });

  it('caps the card lines and builds a colour legend most serious first', () => {
    const many = Array.from({ length: 7 }, (_, i) => act(i, 'beta', i === 0 ? 'KILL' : 'RESTART', 5 + i * 0.01));
    const d = buildEventDots(many, { beta: line }, T0, T0 + 30 * MIN)[0];
    expect(d.count).toBe(7);
    const card = dotCard(d, 3);
    expect(card.lines).toHaveLength(4);
    expect(card.lines[3]).toBe('+4 more');
    expect(card.meaning).toMatch(/Several things happened/);
    expect(legendFor([d]).map((l) => l.name)).toEqual(['Kill', 'Restart']);
  });
});
