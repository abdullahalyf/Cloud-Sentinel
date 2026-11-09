import { livePoll } from '../utils/live';
import React, { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useParams, useSearchParams } from 'react-router-dom';
import { AlertTriangle, Link2, Play, Pause, ShieldCheck } from 'lucide-react';
import { api } from '../api/client';
import type { AgentState } from '../api/types';
import { Panel } from '../components/Panel';
import { StateBadge } from '../components/StateBadge';
import { buildIncidents, stateAt, type EventKind, type Outcome } from '../utils/incidents';

const KIND_COLOR: Record<EventKind, string> = {
  alert: 'var(--color-state-suspicious)',
  verdict: 'var(--color-state-paused)',
  action: 'var(--color-state-killed)',
  memory: 'var(--color-state-probation)',
};

const OUTCOME_COLOR: Record<Outcome, string> = {
  killed: 'var(--color-state-killed-text)',
  paused: 'var(--color-state-paused-text)',
  healed: 'var(--color-state-healthy)',
  open: 'var(--color-state-suspicious)',
};

const KNOWN_STATES = ['healthy', 'suspicious', 'paused', 'probation', 'killed'];
const fmtTime = (ts: number) => new Date(ts).toLocaleTimeString();
const SPEED = 4; // replay at 4x
const TICK_MS = 100;
const TAIL_MS = 30_000; // keep replaying a little past the last event to see the aftermath

export const IncidentsView: React.FC = () => {
  const poll = { refetchInterval: livePoll };
  const alertsQ = useQuery({ queryKey: ['alerts', 100], queryFn: () => api.getAlerts(100), ...poll });
  const actionsQ = useQuery({ queryKey: ['actions', 200], queryFn: () => api.getActions(200), ...poll });
  const verdictsQ = useQuery({ queryKey: ['verdicts', 100], queryFn: () => api.getVerdicts(100), ...poll });
  const metricsQ = useQuery({ queryKey: ['metrics', 60], queryFn: () => api.getMetrics(60), ...poll });

  // D16: /incidents/:incidentId?t=<epoch ms> opens the replay at that moment
  const { incidentId } = useParams();
  const [search] = useSearchParams();
  const [selectedId, setSelectedId] = useState<string | null>(incidentId ?? null);
  const [t, setT] = useState(() => Number(search.get('t')) || 0);
  const [copied, setCopied] = useState(false);
  const [playing, setPlaying] = useState(false);

  const alerts = alertsQ.data?.items ?? [];
  const actions = actionsQ.data?.items ?? [];
  const verdicts = verdictsQ.data?.items ?? [];
  const metrics = metricsQ.data?.metrics ?? [];

  // first pass picks the selected agent; the memory edits of that agent are then added to its timeline
  const baseIncidents = useMemo(() => buildIncidents(actions, verdicts, alerts), [actions, verdicts, alerts]);
  const selectedAgent = (baseIncidents.find((i) => i.id === selectedId) ?? baseIncidents[0])?.agent_id;
  const memoryQ = useQuery({
    queryKey: ['memory-history', selectedAgent],
    queryFn: () => api.getMemoryHistory(selectedAgent as string, 20),
    enabled: !!selectedAgent,
    refetchInterval: livePoll,
  });
  const memoryRows = useMemo(() => memoryQ.data?.items ?? [], [memoryQ.data]);

  const incidents = useMemo(
    () => buildIncidents(actions, verdicts, alerts, selectedAgent ? { [selectedAgent]: memoryRows } : {}),
    [actions, verdicts, alerts, selectedAgent, memoryRows]
  );
  const incident = incidents.find((i) => i.id === selectedId) ?? incidents[0];

  // jump to the start of an incident when it is selected
  useEffect(() => {
    if (incident && (selectedId !== incident.id)) {
      setSelectedId(incident.id);
      setT(incident.start);
      setPlaying(false);
    }
  }, [incident, selectedId]);

  // keep t inside the (possibly growing) incident window
  const start = incident?.start ?? 0;
  const end = incident ? incident.end + TAIL_MS : 1;
  const clamped = Math.min(Math.max(t, start), end);

  useEffect(() => {
    if (!playing) return;
    const h = setInterval(() => {
      setT((prev) => {
        const next = prev + TICK_MS * SPEED;
        if (next >= end) {
          setPlaying(false);
          return end;
        }
        return next;
      });
    }, TICK_MS);
    return () => clearInterval(h);
  }, [playing, end]);

  const snap = incident ? stateAt(clamped, incident.agent_id, metrics, verdicts, memoryRows) : null;
  const pct = (ts: number) => ((ts - start) / (end - start)) * 100;

  const copyLink = async () => {
    if (!incident) return;
    const url = `${window.location.origin}/incidents/${encodeURIComponent(incident.id)}?t=${Math.round(clamped)}`;
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      window.prompt('Copy this link', url);
    }
  };

  const onScrubKey = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
      e.preventDefault();
      setPlaying(false);
      setT(Math.min(end, Math.max(start, clamped + (e.key === 'ArrowRight' ? 1000 : -1000))));
    }
  };

  const loading = alertsQ.isLoading || actionsQ.isLoading || verdictsQ.isLoading || metricsQ.isLoading;
  const error = alertsQ.error || actionsQ.error || verdictsQ.error || metricsQ.error;
  const retry = () => {
    alertsQ.refetch();
    actionsQ.refetch();
    verdictsQ.refetch();
    metricsQ.refetch();
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-6)', width: '100%' }}>
      <header>
        <h1 style={{ fontSize: 'var(--type-title-sm-size)', fontWeight: 700, color: 'var(--color-text-primary)' }}>
          Incident Replay & Interventions Timeline
        </h1>
        <p style={{ fontSize: 'var(--type-body-sm-size)', color: 'var(--color-text-secondary)', marginTop: 'var(--space-1)' }}>
          Trace time-travel scrubber, root cause postmortems, and circuit-breaker trip records.
        </p>
      </header>

      <Panel
        title="Detected Incident Alerts"
        icon={<AlertTriangle size={18} />}
        loading={loading}
        error={error}
        empty={incidents.length === 0}
        emptyTitle="Zero Active Incidents"
        emptyMessage="No anomaly flags or semantic loop alerts have tripped the circuit breaker."
        onRetry={retry}
      >
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(240px, 1fr) minmax(0, 2.4fr)', gap: 'var(--space-4)' }}>
          {/* Incident list */}
          <div role="listbox" aria-label="Incidents" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
            {incidents.map((inc) => {
              const sel = inc.id === incident?.id;
              return (
                <button
                  key={inc.id}
                  type="button"
                  role="option"
                  aria-selected={sel}
                  aria-label={`Incident ${inc.agent_id} at ${fmtTime(inc.start)}`}
                  data-testid={`incident-${inc.id}`}
                  onClick={() => {
                    setSelectedId(inc.id);
                    setT(inc.start);
                    setPlaying(false);
                  }}
                  style={{
                    textAlign: 'left',
                    padding: 'var(--space-3)',
                    backgroundColor: sel ? 'var(--color-state-probation-bg)' : 'var(--color-surface-elevated)',
                    border: `1px solid ${sel ? 'var(--color-accent)' : 'var(--color-border)'}`,
                    borderRadius: 'var(--radius-sm)',
                    color: 'var(--color-text-primary)',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 'var(--space-2)' }}>
                    <strong style={{ fontFamily: 'var(--font-mono)' }}>{inc.agent_id}</strong>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--type-micro-size)', fontWeight: 700, textTransform: 'uppercase', color: OUTCOME_COLOR[inc.outcome] }}>
                      {inc.outcome}
                    </span>
                  </div>
                  <div className="tabular-nums" style={{ display: 'flex', justifyContent: 'space-between', fontSize: 'var(--type-micro-size)', color: 'var(--color-text-muted)', marginTop: 2 }}>
                    <span>{fmtTime(inc.start)} · {inc.events.length} events</span>
                    <span style={{ color: inc.saved_usd > 0 ? 'var(--color-state-healthy)' : undefined }}>
                      {inc.saved_usd > 0 ? `+$${inc.saved_usd.toFixed(2)} saved` : '$0.00 saved'}
                    </span>
                  </div>
                </button>
              );
            })}
          </div>

          {/* Replay */}
          {incident && snap && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)', minWidth: 0 }}>
              <div
                data-testid="incident-timeline"
                style={{ position: 'relative', height: 64, borderBottom: '1px solid var(--color-border)', margin: '0 110px' }}
              >
                {incident.events.map((e, i) => (
                  <div
                    key={i}
                    title={`${fmtTime(e.ts)} ${e.kind}: ${e.title}`}
                    data-testid={`event-${e.kind}`}
                    style={{ position: 'absolute', left: `${pct(e.ts)}%`, top: 8 + (i % 3) * 16, transform: 'translateX(-50%)', display: 'flex', alignItems: 'center', gap: 4, whiteSpace: 'nowrap' }}
                  >
                    <span style={{ width: 10, height: 10, borderRadius: '50%', backgroundColor: KIND_COLOR[e.kind], flexShrink: 0 }} />
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--color-text-secondary)' }}>{e.title}</span>
                  </div>
                ))}
                <div style={{ position: 'absolute', left: `${pct(clamped)}%`, top: 0, bottom: 0, width: 2, backgroundColor: 'var(--color-accent)' }} />
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
                <button
                  type="button"
                  aria-label={playing ? 'Pause replay' : 'Play replay at 4x'}
                  onClick={() => {
                    if (!playing && clamped >= end) setT(start);
                    setPlaying((p) => !p);
                  }}
                  style={{ display: 'flex', alignItems: 'center', gap: 6, padding: 'var(--space-2) var(--space-3)', backgroundColor: 'var(--color-accent)', color: 'var(--color-canvas)', borderRadius: 'var(--radius-sm)', fontWeight: 700, fontSize: 'var(--type-micro-size)' }}
                >
                  {playing ? <Pause size={13} /> : <Play size={13} fill="currentColor" />} {playing ? 'Pause' : 'Play 4×'}
                </button>
                <input
                  type="range"
                  aria-label="Replay scrubber"
                  min={start}
                  max={end}
                  step={50}
                  value={clamped}
                  onChange={(e) => {
                    setPlaying(false);
                    setT(Number(e.target.value));
                  }}
                  onKeyDown={onScrubKey}
                  style={{ flex: 1, accentColor: 'var(--color-accent)' }}
                />
                <span className="tabular-nums" style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--type-micro-size)', color: 'var(--color-text-secondary)' }}>
                  {fmtTime(clamped)}
                </span>
                <button
                  type="button"
                  aria-label="Copy share link"
                  onClick={copyLink}
                  style={{ display: 'flex', alignItems: 'center', gap: 6, padding: 'var(--space-2) var(--space-3)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-sm)', color: 'var(--color-text-primary)', fontSize: 'var(--type-micro-size)', fontWeight: 600 }}
                >
                  <Link2 size={13} /> {copied ? 'Link copied' : 'Share'}
                </button>
              </div>

              <div
                data-testid="incident-snapshot"
                style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 'var(--space-3)', backgroundColor: 'var(--color-canvas)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-sm)', padding: 'var(--space-3)' }}
              >
                <div>
                  <div className="kpi-label">STATE</div>
                  <div style={{ marginTop: 4 }}>
                    {KNOWN_STATES.includes(snap.state) ? <StateBadge state={snap.state as AgentState} /> : <span>{snap.state}</span>}
                  </div>
                </div>
                <div>
                  <div className="kpi-label">$/MIN</div>
                  <div className="tabular-nums" style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, marginTop: 4 }}>
                    {snap.usd_per_min === null ? '—' : `$${snap.usd_per_min.toFixed(4)}`}
                  </div>
                </div>
                <div>
                  <div className="kpi-label">LOOP SCORE</div>
                  <div className="tabular-nums" style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, marginTop: 4 }}>
                    {snap.loop_score === null ? '—' : snap.loop_score.toFixed(2)}
                  </div>
                </div>
                <div>
                  <div className="kpi-label">MEMORY</div>
                  <div className="tabular-nums" style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, marginTop: 4 }}>
                    {snap.memory_version === null ? '—' : `v${snap.memory_version}`}
                  </div>
                </div>
                <div style={{ gridColumn: '1 / -1' }}>
                  <div className="kpi-label">VERDICT AT THIS MOMENT</div>
                  <div style={{ marginTop: 4, fontSize: 'var(--type-body-sm-size)' }}>
                    {snap.verdict ? (
                      <>
                        <strong style={{ fontFamily: 'var(--font-mono)' }}>{snap.verdict.action}</strong>{' '}
                        <span style={{ color: 'var(--color-text-secondary)' }}>{snap.verdict.reason}</span>
                      </>
                    ) : (
                      <span style={{ color: 'var(--color-text-muted)' }}>No verdict yet at this moment.</span>
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </Panel>

      <Panel
        title="Automated Interventions Log"
        icon={<ShieldCheck size={18} />}
        loading={actionsQ.isLoading}
        error={actionsQ.error}
        empty={actions.length === 0}
        emptyTitle="No Actions Logged"
        emptyMessage="Circuit breaker has not intervened on any running agent containers."
        onRetry={() => actionsQ.refetch()}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
          {actions.slice(0, 20).map((act) => (
            <div
              key={act.id}
              style={{ backgroundColor: 'var(--color-surface-elevated)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-sm)', padding: 'var(--space-3) var(--space-4)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}
            >
              <div>
                <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: act.action === 'KILL' ? 'var(--color-state-killed-text)' : 'var(--color-state-paused-text)', marginRight: 'var(--space-2)' }}>
                  [{act.action}]
                </span>
                <span style={{ fontWeight: 600 }}>{act.agent_id}: </span>
                <span style={{ color: 'var(--color-text-secondary)' }}>{act.reason}</span>
              </div>
              {act.usd_saved_estimate > 0 && (
                <span className="tabular-nums" style={{ color: 'var(--color-state-healthy)', fontWeight: 600, fontSize: 'var(--type-micro-size)' }}>
                  +${act.usd_saved_estimate.toFixed(2)} Saved
                </span>
              )}
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
};
