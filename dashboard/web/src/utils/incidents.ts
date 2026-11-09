import type { ActionRow, AlertRow, MemoryRow, MetricRow, VerdictRow } from '../api/types';

/** Incident replay (D8): group events into incidents and rebuild an agent's state at time t. */

export const INCIDENT_GAP_MS = 60_000;

export type EventKind = 'alert' | 'verdict' | 'action' | 'memory';

export interface IncidentEvent {
  ts: number;
  kind: EventKind;
  agent_id: string;
  title: string;
  detail: string;
}

export type Outcome = 'killed' | 'paused' | 'healed' | 'open';

export interface Incident {
  id: string;
  agent_id: string;
  start: number;
  end: number;
  events: IncidentEvent[];
  outcome: Outcome;
  saved_usd: number;
}

const ms = (iso?: string): number => (iso ? new Date(iso).getTime() : NaN);

export function toEvents(
  actions: ActionRow[],
  verdicts: VerdictRow[],
  alerts: AlertRow[],
  memory: Record<string, MemoryRow[]> = {}
): IncidentEvent[] {
  const ev: IncidentEvent[] = [];
  alerts.forEach((a) =>
    ev.push({ ts: ms(a.created_at), kind: 'alert', agent_id: a.agent_id, title: a.rule, detail: a.message })
  );
  verdicts.forEach((v) =>
    ev.push({ ts: ms(v.created_at), kind: 'verdict', agent_id: v.agent_id, title: `${v.action} (${Math.round(v.confidence * 100)}%)`, detail: v.reason })
  );
  actions.forEach((a) =>
    ev.push({ ts: ms(a.created_at), kind: 'action', agent_id: a.agent_id, title: a.action, detail: a.reason })
  );
  Object.entries(memory).forEach(([agent, rows]) =>
    rows.forEach((m) =>
      ev.push({ ts: ms(m.created_at), kind: 'memory', agent_id: agent, title: `memory v${m.version}`, detail: `${m.edited_by}: ${m.reason}` })
    )
  );
  return ev.filter((e) => Number.isFinite(e.ts)).sort((a, b) => a.ts - b.ts);
}

function outcomeOf(events: IncidentEvent[]): Outcome {
  const acts = events.filter((e) => e.kind === 'action').map((e) => e.title);
  if (acts.includes('KILL')) return 'killed';
  const lastPause = acts.lastIndexOf('PAUSE');
  if (lastPause >= 0) {
    const after = acts.slice(lastPause + 1);
    return after.some((a) => a === 'RESUME' || a === 'AUTO_HEAL' || a === 'MEMORY_EDIT') ? 'healed' : 'paused';
  }
  return events.some((e) => e.kind === 'memory') && acts.includes('RESUME') ? 'healed' : 'open';
}

/** An incident = events of one agent with no gap longer than 60 s. Newest incident first. */
export function buildIncidents(
  actions: ActionRow[],
  verdicts: VerdictRow[],
  alerts: AlertRow[],
  memory: Record<string, MemoryRow[]> = {}
): Incident[] {
  const byAgent = new Map<string, IncidentEvent[]>();
  toEvents(actions, verdicts, alerts, memory).forEach((e) => {
    byAgent.set(e.agent_id, [...(byAgent.get(e.agent_id) ?? []), e]);
  });

  const out: Incident[] = [];
  byAgent.forEach((events, agent) => {
    let group: IncidentEvent[] = [];
    const flush = () => {
      if (group.length === 0) return;
      const saved = actions
        .filter((a) => a.agent_id === agent && group.some((g) => g.kind === 'action' && g.ts === ms(a.created_at) && g.title === a.action))
        .reduce((s, a) => s + (a.usd_saved_estimate || 0), 0);
      out.push({
        id: `${agent}-${group[0].ts}`,
        agent_id: agent,
        start: group[0].ts,
        end: group[group.length - 1].ts,
        events: group,
        outcome: outcomeOf(group),
        saved_usd: saved,
      });
      group = [];
    };
    events.forEach((e) => {
      if (group.length && e.ts - group[group.length - 1].ts > INCIDENT_GAP_MS) flush();
      group.push(e);
    });
    flush();
  });
  return out.sort((a, b) => b.start - a.start);
}

export interface Snapshot {
  state: string;
  usd_per_min: number | null;
  loop_score: number | null;
  verdict: VerdictRow | null;
  memory_version: number | null;
}

/** The agent's state at time t, rebuilt only from recorded data (nothing is invented). */
export function stateAt(
  t: number,
  agentId: string,
  metrics: MetricRow[],
  verdicts: VerdictRow[],
  memory: MemoryRow[]
): Snapshot {
  const rows = metrics
    .filter((m) => m.agent_id === agentId)
    .map((m) => ({ m, ts: ms(m.created_at) }))
    .filter((r) => Number.isFinite(r.ts))
    .sort((a, b) => a.ts - b.ts);
  // newest sample at or before t; before the first sample, use the first one
  const row = [...rows].reverse().find((r) => r.ts <= t) ?? rows[0];

  const verdict =
    verdicts
      .filter((v) => v.agent_id === agentId && ms(v.created_at) <= t)
      .sort((a, b) => ms(b.created_at) - ms(a.created_at))[0] ?? null;

  const versions = memory.filter((m) => ms(m.created_at) <= t).map((m) => m.version);

  return {
    state: row?.m.state ?? 'unknown',
    usd_per_min: row ? row.m.usd_per_min : null,
    loop_score: row ? row.m.loop_score : null,
    verdict,
    memory_version: versions.length ? Math.max(...versions) : null,
  };
}
