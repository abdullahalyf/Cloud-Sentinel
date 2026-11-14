import type { ActionRow } from '../api/types';

/**
 * Event dots for the burn-down charts: every circuit-breaker action becomes a coloured dot that sits on
 * the agent's own line, with a plain-language "what this means" for the hover card.
 */

export type Point = [number, number];

export interface EventStyle {
  color: string;
  name: string;
  /** higher wins when several events share one dot */
  rank: number;
  meaning: string;
}

// The colours mirror the --chart-* tokens (ECharts cannot read CSS variables).
export const EVENT_STYLES: Record<string, EventStyle> = {
  KILL: { color: '#d92d20', name: 'Kill', rank: 9, meaning: 'The circuit breaker stopped this agent for good.' },
  PAUSE: { color: '#f59e0b', name: 'Pause', rank: 8, meaning: 'Paused: spending stops until a human resumes it.' },
  TOOL_DENY: { color: '#b944db', name: 'Tool denied', rank: 7, meaning: 'A risky tool call was blocked before it ran.' },
  TOOL_REWRITE: { color: '#b944db', name: 'Tool rewritten', rank: 6, meaning: 'A risky tool call was changed to a safer one.' },
  AUTO_HEAL: { color: '#3b1fe8', name: 'Memory fix', rank: 5, meaning: "The agent's memory was repaired so it stops looping." },
  MEMORY_EDIT: { color: '#3b1fe8', name: 'Memory edit', rank: 5, meaning: "The agent's memory was edited." },
  RESTART: { color: '#12a150', name: 'Restart', rank: 4, meaning: 'The agent was started again (on probation).' },
  RESUME: { color: '#12a150', name: 'Resume', rank: 4, meaning: 'The agent was resumed (on probation).' },
  SET_BUDGET: { color: '#12a8c8', name: 'Budget change', rank: 2, meaning: "The agent's budget was changed." },
  WARN: { color: '#8a97ab', name: 'Warning', rank: 1, meaning: 'A warning was raised; nothing was stopped.' },
};

export const styleOf = (action: string): EventStyle | null => EVENT_STYLES[action] ?? null;

export interface EventDot {
  ts: number;
  agent_id: string;
  /** y value on the agent's line at that time */
  value: number;
  kind: string;
  color: string;
  count: number;
  events: ActionRow[];
}

/** The line's value at time `ts` (the newest sample at or before it, else the first sample). */
export function valueAt(series: Point[], ts: number): number | null {
  if (series.length === 0) return null;
  let v = series[0][1];
  for (const [t, val] of series) {
    if (t <= ts) v = val;
    else break;
  }
  return v;
}

/**
 * Builds the dots: only known event kinds with an agent, inside [from, to]; events of one agent closer
 * than `minGapFrac` of the visible span share one dot (coloured by the most serious of them).
 */
export function buildEventDots(
  actions: ActionRow[],
  seriesByAgent: Record<string, Point[]>,
  from: number,
  to: number,
  minGapFrac = 0.03
): EventDot[] {
  const span = Math.max(1, to - from);
  const byAgent = new Map<string, ActionRow[]>();
  actions.forEach((a) => {
    const t = new Date(a.created_at).getTime();
    if (!a.agent_id || !styleOf(a.action) || !Number.isFinite(t) || t < from || t > to) return;
    byAgent.set(a.agent_id, [...(byAgent.get(a.agent_id) ?? []), a]);
  });

  const dots: EventDot[] = [];
  byAgent.forEach((list, agent) => {
    const sorted = [...list].sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());
    const groups: ActionRow[][] = [];
    sorted.forEach((a) => {
      const g = groups[groups.length - 1];
      const t = new Date(a.created_at).getTime();
      if (g && t - new Date(g[g.length - 1].created_at).getTime() < span * minGapFrac) g.push(a);
      else groups.push([a]);
    });
    groups.forEach((g) => {
      const ts = new Date(g[0].created_at).getTime();
      const value = valueAt(seriesByAgent[agent] ?? [], ts);
      if (value === null) return;
      const top = g.reduce((best, a) => ((styleOf(a.action)?.rank ?? 0) > (styleOf(best.action)?.rank ?? 0) ? a : best), g[0]);
      dots.push({ ts, agent_id: agent, value, kind: top.action, color: styleOf(top.action)!.color, count: g.length, events: g });
    });
  });
  return dots.sort((a, b) => a.ts - b.ts);
}

export interface DotCard {
  title: string;
  meaning: string;
  lines: string[];
}

const clip = (s: string, n: number) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);

/** What the hover card says. */
export function dotCard(d: EventDot, maxLines = 4): DotCard {
  const st = styleOf(d.kind)!;
  const title = d.count > 1 ? `${d.agent_id}: ${d.count} events` : `${d.agent_id}: ${st.name}`;
  const meaning = d.count > 1 ? `Several things happened close together. The most serious was a ${st.name.toLowerCase()}.` : st.meaning;
  const lines = d.events.slice(0, maxLines).map((e) => {
    const time = new Date(e.created_at).toLocaleTimeString();
    const saved = e.usd_saved_estimate > 0 ? ` · saved $${e.usd_saved_estimate.toFixed(2)}` : '';
    const why = e.reason ? ` — ${clip(e.reason, 80)}` : '';
    return `${time} ${styleOf(e.action)?.name ?? e.action}${saved}${why}`;
  });
  if (d.events.length > maxLines) lines.push(`+${d.events.length - maxLines} more`);
  return { title, meaning, lines };
}

/** The kinds present in a set of dots, for the legend (most serious first, merged by colour). */
export function legendFor(dots: EventDot[]): { color: string; name: string }[] {
  const seen = new Map<string, { color: string; name: string; rank: number }>();
  dots.forEach((d) => d.events.forEach((e) => {
    const st = styleOf(e.action);
    if (st && !seen.has(st.color)) seen.set(st.color, { color: st.color, name: st.name, rank: st.rank });
  }));
  return [...seen.values()].sort((a, b) => b.rank - a.rank).map(({ color, name }) => ({ color, name }));
}
