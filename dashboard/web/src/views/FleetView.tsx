import React, { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { DollarSign, Activity, ShieldAlert, Coins, Cpu, ArrowRight, AlertTriangle, Wallet, Clock } from 'lucide-react';
import { api } from '../api/client';
import type { AgentState, AgentView } from '../api/types';
import { Panel } from '../components/Panel';
import { StateBadge } from '../components/StateBadge';
import { MiniSpark, fmtCompact } from '../components/charts';
import { CardHeader, HeroCard, KpiCard, PageHeader, Segmented, deltaPct, greeting, ago } from '../components/ui';
import { Lollipop, StageBars, TickGauge, downsample } from '../components/vizExtra';
import { aggregateField } from '../utils/burn';
import { livePoll } from '../utils/live';
import { groupByNode, hasNodes } from '../utils/nodes';
import { useCountUp } from '../utils/useCountUp';

export function sortFleetAgents(agents: AgentView[]): AgentView[] {
  return [...agents].sort((a, b) => {
    const aHalted = a.state === 'killed' || a.state === 'paused' ? 0 : 1;
    const bHalted = b.state === 'killed' || b.state === 'paused' ? 0 : 1;
    if (aHalted !== bHalted) {
      return aHalted - bHalted;
    }
    return b.usd_per_min - a.usd_per_min;
  });
}

/** Fleet-wide token limit: the sum of each selected agent's learned soft limit (null if any is still warming up). */
export function fleetLimit(agents: AgentView[]): number | null {
  if (agents.length === 0) return null;
  let sum = 0;
  for (const a of agents) {
    const l = a.baseline?.tokens_per_min?.limit;
    if (!l) return null;
    sum += l;
  }
  return sum;
}

const money2 = (v: number) => `$${v.toFixed(2)}`;
const tok = (v: number) => (v >= 1000 ? fmtCompact(v) : String(Math.round(v)));
const fmtRoi = (x: number) => (x >= 1000 ? `${(x / 1000).toFixed(1)}k` : x.toFixed(1));
const WINDOWS = [
  { value: 2, label: '2 min' },
  { value: 5, label: '5 min' },
  { value: 15, label: '15 min' },
];

const STATE_COLORS: Record<string, string> = {
  healthy: 'var(--color-state-healthy)',
  probation: 'var(--color-state-probation)',
  suspicious: 'var(--chart-amber)',
  paused: 'var(--chart-violet)',
  killed: 'var(--chart-red)',
};

export const FleetView: React.FC = () => {
  const navigate = useNavigate();
  const [filterState, setFilterState] = useState<AgentState | 'all'>('all');
  const [byNode, setByNode] = useState(false);
  const [minutes, setMinutes] = useState(5);
  const [focus, setFocus] = useState<string>('all');

  const fleetQ = useQuery({ queryKey: ['fleet'], queryFn: api.getFleet, refetchInterval: livePoll });
  const roiQ = useQuery({ queryKey: ['roi'], queryFn: api.getRoi, refetchInterval: livePoll });
  const { data: metricsData } = useQuery({ queryKey: ['metrics', minutes], queryFn: () => api.getMetrics(minutes), refetchInterval: livePoll });
  const { data: calls } = useQuery({ queryKey: ['tool-calls', 'pending'], queryFn: () => api.getToolCalls('pending'), refetchInterval: livePoll });
  const { data: heals } = useQuery({ queryKey: ['heal-proposals', 'pending'], queryFn: () => api.getHealProposals('pending'), refetchInterval: livePoll });

  const agents = fleetQ.data?.agents || [];
  const roi = roiQ.data;
  const totalBurnRate = agents.reduce((sum, a) => sum + (a.usd_per_min || 0), 0);
  const totalSpend = roi?.total_spend_usd ?? agents.reduce((sum, a) => sum + (a.spend_usd || 0), 0);
  const totalSaved = roi?.saved_usd ?? 0;
  const interventions = roi?.interventions ?? 0;
  const savedShown = useCountUp(totalSaved);

  const metrics = metricsData?.metrics ?? [];
  const focusMetrics = useMemo(() => (focus === 'all' ? metrics : metrics.filter((m) => m.agent_id === focus)), [metrics, focus]);
  const burn = useMemo(() => aggregateField(focusMetrics, 'tokens_per_min'), [focusMetrics]);
  const spendSeries = useMemo(() => aggregateField(metrics, 'spend_usd').values, [metrics]);
  const usdSeries = useMemo(() => aggregateField(metrics, 'usd_per_min').values, [metrics]);
  const points = useMemo(() => {
    const p = downsample(burn.values, burn.labels, 14);
    if (p.length) p[p.length - 1] = { ...p[p.length - 1], label: 'Now' };
    return p.map((x, i) => (i === p.length - 1 ? x : { ...x, label: x.label.replace(/:\d\d(\s?[AP]M)?$/, '$1') }));
  }, [burn]);
  const limit = fleetLimit(focus === 'all' ? agents : agents.filter((a) => a.agent_id === focus));
  const peak = points.reduce((m, p) => (p.value > m.value ? p : m), { value: 0, label: '' });
  const above = limit ? points.filter((p) => p.value > limit).length : 0;

  const stateCounts = agents.reduce<Record<string, number>>((acc, a) => {
    acc[a.state] = (acc[a.state] || 0) + 1;
    return acc;
  }, {});
  const sortedAgents = sortFleetAgents(agents);
  const displayedAgents = filterState === 'all' ? sortedAgents : sortedAgents.filter((a) => a.state === filterState);
  const pending = [...(calls?.items ?? []).map((c) => ({ kind: 'tool' as const, id: c.id, agent: c.agent_id, title: c.tool_name, sub: c.value_usd > 0 ? `$${c.value_usd.toFixed(0)} at stake` : c.reason, at: c.created_at })), ...(heals?.items ?? []).map((h) => ({ kind: 'heal' as const, id: h.id, agent: h.agent_id, title: 'Memory fix proposed', sub: `${Math.round(h.confidence * 100)}% confidence`, at: h.created_at }))];
  const budgetLeft = agents.reduce((s, a) => s + Math.max(0, a.budget_usd - a.spend_usd), 0);
  const overBudget = agents.filter((a) => a.budget_usd > 0 && a.spend_usd / a.budget_usd >= 0.8);
  const watch = sortedAgents.filter((a) => a.state !== 'healthy' || (a.budget_usd > 0 && a.spend_usd / a.budget_usd >= 0.8)).slice(0, 4);
  const spenders = [...agents].sort((a, b) => b.spend_usd - a.spend_usd).slice(0, 5);
  const maxSpend = Math.max(1e-9, ...spenders.map((a) => a.spend_usd));
  const tasksTotal = roi?.tasks_total ?? 0;
  const tasksOk = roi?.tasks_succeeded ?? 0;
  const running = agents.filter((a) => a.state !== 'killed' && a.state !== 'paused').length;

  const refreshAll = () => {
    fleetQ.refetch();
    roiQ.refetch();
  };

  const row = (agent: AgentView) => {
    const ratio = agent.budget_usd > 0 ? agent.spend_usd / agent.budget_usd : 0;
    const median = agent.baseline?.tokens_per_min?.median;
    const last = agent.last_verdict ? `[${agent.last_verdict.action}] ${agent.last_verdict.reason}` : 'Operating within baseline limits';
    const open = () => navigate(`/agents/${agent.agent_id}`);
    return (
      <tr
        key={agent.agent_id}
        data-testid={`agent-card-${agent.agent_id}`}
        tabIndex={0}
        aria-label={`Inspect agent ${agent.agent_id}, state ${agent.state}`}
        onClick={open}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            open();
          }
        }}
      >
        <td style={{ maxWidth: 240 }}>
          <span>{agent.agent_id}</span>
          <span className="sub" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={last}>
            {agent.runtime} · {ago(agent.updated_at)} · {last}
          </span>
        </td>
        <td className="num">
          {tok(agent.tokens_per_min)}
          {median ? <span className="sub">{(agent.tokens_per_min / median).toFixed(1)}× normal</span> : null}
        </td>
        <td style={{ minWidth: 150 }}>
          ${agent.spend_usd.toFixed(2)} <span className="muted">/ ${agent.budget_usd.toFixed(2)}</span>
          <span style={{ display: 'block', height: 4, borderRadius: 2, background: 'var(--color-fill)', marginTop: 6 }}>
            <span className="meter-fill" style={{ display: 'block', height: '100%', borderRadius: 2, width: `${Math.min(100, ratio * 100)}%`, background: ratio >= 0.8 ? 'var(--chart-red)' : 'var(--chart-violet)' }} />
          </span>
        </td>
        <td className="num" style={{ color: agent.loop_score >= 0.4 ? 'var(--color-state-killed)' : undefined }}>
          {agent.loop_score.toFixed(2)}
        </td>
        <td>
          <StateBadge state={agent.state} />
        </td>
        <td className="num">
          <span className="btn btn-sm" aria-hidden="true">
            Inspect <ArrowRight size={13} />
          </span>
        </td>
      </tr>
    );
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 22, width: '100%' }}>
      <PageHeader
        eyebrow={`${greeting()}, operator`}
        title="Fleet Telemetry Control"
        summary={`${money2(totalSaved)} saved by ${interventions} interventions · ${running} of ${agents.length} agents running · ${pending.length} waiting for a human.`}
        actions={
          <>
            <button type="button" className="btn" onClick={refreshAll} aria-label="Refresh telemetry data">
              Refresh
            </button>
            <Link to="/approvals" className="btn-primary">
              <ShieldAlert size={15} /> Approvals
            </Link>
          </>
        }
      />

      <div className="bento" style={{ alignItems: 'start' }}>
        {/* ── left column ── */}
        <div className="col-span-8" style={{ display: 'flex', flexDirection: 'column', gap: 18, minWidth: 0 }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1.25fr 1fr 1fr 1fr', gap: 18 }}>
            <HeroCard
              testId="kpi-saved"
              label="Total $ saved"
              icon={<DollarSign size={15} />}
              value={`$${savedShown.toFixed(4)}`}
              foot={`${fmtRoi(totalSpend > 0 ? totalSaved / totalSpend : 0)}× return on ${money2(totalSpend)} spent`}
              progress={totalSaved + totalSpend > 0 ? totalSaved / (totalSaved + totalSpend) : 0}
            />
            <KpiCard label="Fleet spend" icon={<Coins size={15} />} value={`$${totalSpend.toFixed(4)}`} spark={spendSeries} delta={deltaPct(spendSeries)} goodWhenUp={false} />
            <KpiCard label="Burn rate" icon={<Activity size={15} />} value={`$${totalBurnRate.toFixed(4)}/min`} spark={usdSeries} delta={deltaPct(usdSeries)} goodWhenUp={false} />
            <KpiCard
              label="Interventions"
              icon={<ShieldAlert size={15} />}
              value={interventions}
              foot={<span className="chip" style={{ background: 'var(--color-fill)', color: 'var(--color-text-secondary)' }}>{roi?.tool_calls_held || 0} held at the gate</span>}
            />
          </div>

          <section className="card card-pad" aria-label="Token burn against the limit">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap' }}>
              <div>
                <h2 className="card-title">Token burn against the limit</h2>
                <p className="card-sub">Tokens per minute across the fleet — red means a sample went over the learned limit</p>
              </div>
              <Segmented label="Time window" options={WINDOWS} value={minutes} onChange={setMinutes} />
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: 16, flexWrap: 'wrap', margin: '18px 0 8px' }}>
              <div style={{ display: 'flex', gap: 28, alignItems: 'flex-end', flexWrap: 'wrap' }}>
                <div>
                  <div className="stat-label">Now</div>
                  <div style={{ fontSize: 34, fontWeight: 600, letterSpacing: '-0.02em', lineHeight: 1.05 }}>{fmtCompact(burn.values[burn.values.length - 1] ?? 0)}<span className="muted" style={{ fontSize: 15 }}>/min</span></div>
                </div>
                <div>
                  <div className="stat-label">Over the limit</div>
                  <div className="stat-value">{limit ? `${above} of ${points.length}` : '—'} <span className="muted" style={{ fontSize: 12.5 }}>samples</span></div>
                </div>
                <div>
                  <div className="stat-label"><span style={{ color: 'var(--color-state-killed)' }}>- -</span> Limit</div>
                  <div className="stat-value">{limit ? `${fmtCompact(limit)}/min` : 'learning'}</div>
                </div>
                <div>
                  <div className="stat-label">Peak</div>
                  <div className="stat-value">{fmtCompact(peak.value)} <span className="muted" style={{ fontSize: 12.5 }}>{peak.label}</span></div>
                </div>
              </div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {['all', ...agents.map((a) => a.agent_id)].map((id) => (
                  <button key={id} type="button" className="filter-chip" aria-pressed={focus === id} aria-label={`Show ${id === 'all' ? 'all agents' : id}`} onClick={() => setFocus(id)}>
                    {id === 'all' ? 'All' : <><span style={{ width: 8, height: 8, borderRadius: 3, background: STATE_COLORS[agents.find((a) => a.agent_id === id)?.state ?? 'healthy'] }} />{id.toUpperCase()}</>}
                  </button>
                ))}
              </div>
            </div>
            {points.length >= 2 && Math.max(...points.map((p) => p.value)) > 0 ? (
              <Lollipop testId="fleet-burn-chart" points={points} limit={limit} format={(v) => fmtCompact(v)} />
            ) : (
              <p className="muted" style={{ padding: '48px 0' }}>No token flow to chart yet: it appears once running agents report a few samples.</p>
            )}
          </section>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 18 }}>
            <section className="card card-pad" aria-label="Agent states">
              <CardHeader title="Agent states" sub="Where every agent is in the circuit breaker" to="/incidents" toLabel="Open incidents" />
              <StageBars
                stages={[
                  { label: 'Healthy', value: stateCounts.healthy || 0, color: 'var(--color-state-healthy)' },
                  { label: 'Probation', value: stateCounts.probation || 0, color: 'var(--chart-cyan)' },
                  { label: 'Suspicious', value: stateCounts.suspicious || 0, color: 'var(--chart-amber)' },
                  { label: 'Paused', value: stateCounts.paused || 0, color: 'var(--chart-violet)' },
                  { label: 'Killed', value: stateCounts.killed || 0, color: 'var(--chart-red)' },
                ]}
              />
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 20, paddingTop: 14, borderTop: '1px solid var(--color-border)' }}>
                <span className="muted" style={{ fontSize: 12.5, display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                  <Clock size={13} /> {agents.length} Total · polled every second
                </span>
                <Link to="/incidents" className="btn btn-sm">Open incidents</Link>
              </div>
            </section>

            <section className="card card-pad" aria-label="Top spenders">
              <CardHeader title="Top spenders" sub="Agents ranked by spend so far" to="/cost" toLabel="Open cost and ROI" />
              <ol style={{ listStyle: 'none', display: 'flex', flexDirection: 'column' }}>
                {spenders.map((a, i) => (
                  <li key={a.agent_id} style={{ display: 'grid', gridTemplateColumns: '16px 32px 1fr auto', alignItems: 'center', gap: 12, padding: '10px 0', borderTop: i ? '1px solid var(--color-border)' : undefined }}>
                    <span className="muted" style={{ fontSize: 12 }}>{i + 1}</span>
                    <span className="icon-tile"><Cpu size={15} /></span>
                    <span style={{ minWidth: 0 }}>
                      <span style={{ fontWeight: 600 }}>{a.agent_id.toUpperCase()}</span>
                      <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span className="muted" style={{ fontSize: 12 }}>{tok(a.tokens_per_min)} tokens/min</span>
                        <span style={{ width: 56, height: 3, borderRadius: 2, background: 'var(--color-fill)' }}>
                          <span className="meter-fill" style={{ display: 'block', height: '100%', borderRadius: 2, width: `${(a.spend_usd / maxSpend) * 100}%`, background: 'var(--chart-violet)' }} />
                        </span>
                      </span>
                    </span>
                    <span style={{ fontWeight: 700 }}>{money2(a.spend_usd)}</span>
                  </li>
                ))}
              </ol>
            </section>
          </div>

          <div id="agents-table">
            <Panel
              title="Fleet Node Telemetry"
              subtitle="Every monitored agent — halted first, then by burn rate"
              loading={fleetQ.isLoading || roiQ.isLoading}
              error={fleetQ.error || roiQ.error}
              empty={agents.length === 0}
              emptyTitle="No Agents Running"
              emptyMessage="No agents yet: start one with python -m brain --fake"
              onRetry={refreshAll}
              actions={
                <>
                  {hasNodes(agents) && (
                    <button type="button" className="filter-chip" aria-label="Group agents by node" aria-pressed={byNode} onClick={() => setByNode((v) => !v)}>
                      BY NODE
                    </button>
                  )}
                  {(['all', 'healthy', 'suspicious', 'paused', 'killed'] as const).map((st) => {
                    const count = st === 'all' ? agents.length : stateCounts[st] || 0;
                    return (
                      <button key={st} type="button" className="filter-chip" aria-pressed={filterState === st} onClick={() => setFilterState(st)} aria-label={`Filter by ${st}`} style={{ textTransform: 'capitalize' }}>
                        {st} ({count})
                      </button>
                    );
                  })}
                </>
              }
            >
              <div data-testid="fleet-agent-grid" style={{ overflowX: 'auto', margin: '0 -8px' }}>
                <table className="ui-table" aria-label="Agents">
                  <thead>
                    <tr>
                      <th>Agent</th>
                      <th className="num">Tokens/min</th>
                      <th>Spend / budget</th>
                      <th className="num">Loop</th>
                      <th>State</th>
                      <th className="num" aria-label="Action" />
                    </tr>
                  </thead>
                  <tbody>
                    {byNode && hasNodes(agents)
                      ? groupByNode(displayedAgents).flatMap((g) => [
                          <tr key={`node-${g.node}`} aria-label={`Node ${g.node}`}>
                            <td colSpan={6} className="muted" style={{ background: 'var(--color-fill)', fontSize: 12 }}>
                              node: {g.node} · {g.agents.length} agent{g.agents.length === 1 ? '' : 's'}
                            </td>
                          </tr>,
                          ...g.agents.map(row),
                        ])
                      : displayedAgents.map(row)}
                  </tbody>
                </table>
              </div>
            </Panel>
          </div>
        </div>

        {/* ── right column ── */}
        <div className="col-span-4" style={{ display: 'flex', flexDirection: 'column', gap: 18, minWidth: 0 }}>
          <section className="card card-pad" aria-label="Budget">
            <CardHeader title={<span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}><Wallet size={16} color="var(--color-accent-text)" /> Budget</span>} to="/cost" toLabel="Open cost and ROI" />
            <div className="stat-label">Left to spend across the fleet</div>
            <div style={{ fontSize: 32, fontWeight: 600, letterSpacing: '-0.02em', margin: '2px 0 10px' }}>{money2(budgetLeft)}</div>
            {spendSeries.length > 1 && <MiniSpark data={spendSeries} color="var(--chart-violet)" id="budget-spend" height={56} />}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, margin: '14px 0 16px' }}>
              <div>
                <div className="stat-label">Spent</div>
                <div style={{ fontWeight: 700 }}>{money2(agents.reduce((s, a) => s + a.spend_usd, 0))}</div>
              </div>
              <div>
                <div className="stat-label">Wasted in loops</div>
                <div style={{ fontWeight: 700 }}>{money2(roi?.wasted_usd ?? 0)}</div>
              </div>
            </div>
            <Link to="/cost" className="btn-primary btn-block">
              <DollarSign size={15} /> Open cost report
            </Link>
            {overBudget.length > 0 ? (
              <button type="button" className="btn-warn btn-block" style={{ marginTop: 8 }} onClick={() => document.getElementById('agents-table')?.scrollIntoView({ behavior: 'smooth' })}>
                <AlertTriangle size={14} /> {overBudget.length} agent{overBudget.length === 1 ? '' : 's'} over 80% of budget
              </button>
            ) : (
              <p className="muted" style={{ fontSize: 12.5, textAlign: 'center', marginTop: 10 }}>Every agent is under 80% of its budget</p>
            )}
          </section>

          <section className="card card-pad" aria-label="Task success">
            <CardHeader title="Task success" sub="Tasks resolved in the ROI window" />
            <div style={{ display: 'flex', alignItems: 'center', gap: 18 }}>
              <TickGauge value={tasksTotal > 0 ? tasksOk / tasksTotal : 0} center={`${tasksTotal > 0 ? Math.round((tasksOk / tasksTotal) * 100) : 0}%`} caption={`${tasksOk} of ${tasksTotal}`} label="Task success rate" />
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                <div>
                  <div className="stat-label">Resolved</div>
                  <div style={{ fontWeight: 700, color: 'var(--color-state-healthy)' }}>{tasksOk}</div>
                </div>
                <div>
                  <div className="stat-label">Not resolved</div>
                  <div style={{ fontWeight: 700 }}>{Math.max(0, tasksTotal - tasksOk)}</div>
                </div>
                <div>
                  <div className="stat-label">Cost per success</div>
                  <div style={{ fontWeight: 700 }}>${(roi?.cost_per_successful_task_usd ?? 0).toFixed(4)}</div>
                </div>
              </div>
            </div>
          </section>

          <section className="card card-pad" aria-label="Needs a human">
            <CardHeader title="Needs a human" sub="Tool calls and memory fixes held for a decision" right={<Link to="/approvals" style={{ color: 'var(--color-accent-text)', fontWeight: 600, fontSize: 13 }}>Approvals</Link>} />
            {pending.length === 0 ? (
              <p className="muted" style={{ fontSize: 13 }}>Nothing waiting for a human right now.</p>
            ) : (
              <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 12 }}>
                {pending.slice(0, 4).map((p) => {
                  const d = new Date(p.at);
                  return (
                    <li key={`${p.kind}-${p.id}`} style={{ display: 'grid', gridTemplateColumns: '44px 1fr auto', alignItems: 'center', gap: 12 }}>
                      <span style={{ width: 44, height: 48, borderRadius: 12, boxShadow: 'var(--ring)', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', borderLeft: '3px solid var(--color-accent)' }}>
                        <strong style={{ fontSize: 14 }}>{Number.isFinite(d.getTime()) ? d.getHours().toString().padStart(2, '0') : '--'}</strong>
                        <span className="muted" style={{ fontSize: 10.5 }}>{Number.isFinite(d.getTime()) ? `:${d.getMinutes().toString().padStart(2, '0')}` : ''}</span>
                      </span>
                      <span style={{ minWidth: 0 }}>
                        <span style={{ fontWeight: 600, display: 'block' }}>{p.title}</span>
                        <span className="sub" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.sub}</span>
                      </span>
                      <span className="avatar" title={p.agent}>{p.agent.slice(0, 2).toUpperCase()}</span>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>

          <section className="card card-pad" aria-label="Watch list">
            <CardHeader title="Watch list" sub="Halted, suspicious, or near the budget" />
            {watch.length === 0 ? (
              <p className="muted" style={{ fontSize: 13 }}>Every agent is healthy and under budget.</p>
            ) : (
              <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column' }}>
                {watch.map((a, i) => (
                  <li key={a.agent_id} style={{ display: 'grid', gridTemplateColumns: '32px 1fr auto', alignItems: 'center', gap: 12, padding: '10px 0', borderTop: i ? '1px solid var(--color-border)' : undefined }}>
                    <span className="icon-tile" style={{ color: a.state === 'killed' ? 'var(--color-state-killed)' : 'var(--color-accent-text)' }}><Cpu size={15} /></span>
                    <span style={{ minWidth: 0 }}>
                      <span style={{ fontWeight: 600 }}>{a.agent_id.toUpperCase()}</span>
                      <span className="sub">
                        {a.state !== 'healthy' ? `${a.state} · loop ${a.loop_score.toFixed(2)}` : `${Math.round((a.spend_usd / a.budget_usd) * 100)}% of budget`}
                      </span>
                    </span>
                    <Link to={`/agents/${a.agent_id}`} className="btn btn-sm">Inspect</Link>
                  </li>
                ))}
              </ul>
            )}
            <p className="muted" style={{ fontSize: 12, marginTop: 12 }}>Updated {new Date().toLocaleTimeString()}</p>
          </section>
        </div>
      </div>
    </div>
  );
};
