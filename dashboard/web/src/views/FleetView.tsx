import React, { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { RefreshCw, Filter, Terminal, Cpu } from 'lucide-react';
import { api } from '../api/client';
import type { AgentState, AgentView } from '../api/types';
import { Panel } from '../components/Panel';
import { AgentCard } from '../components/AgentCard';
import { GroupedBars, LineAreaChart } from '../components/viz';
import { fmtCompact } from '../components/charts';
import { aggregateBurn } from '../utils/burn';
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

const STATE_SEGMENTS: { key: string; color: string }[] = [
  { key: 'healthy', color: 'var(--color-state-healthy)' },
  { key: 'probation', color: 'var(--color-state-probation)' },
  { key: 'suspicious', color: 'var(--color-state-suspicious)' },
  { key: 'paused', color: 'var(--color-state-paused)' },
  { key: 'killed', color: 'var(--color-state-killed)' },
];

const money = (v: number) => `$${v < 1 ? v.toFixed(4) : v.toFixed(2)}`;

export const FleetView: React.FC = () => {
  const navigate = useNavigate();
  const [filterState, setFilterState] = useState<AgentState | 'all'>('all');
  const [byNode, setByNode] = useState(false);

  const {
    data: fleetData,
    isLoading: loadingFleet,
    error: errorFleet,
    refetch: refetchFleet,
  } = useQuery({ queryKey: ['fleet'], queryFn: api.getFleet, refetchInterval: livePoll });

  const {
    data: roiData,
    isLoading: loadingRoi,
    error: errorRoi,
    refetch: refetchRoi,
  } = useQuery({ queryKey: ['roi'], queryFn: api.getRoi, refetchInterval: livePoll });

  const { data: metricsData } = useQuery({
    queryKey: ['metrics', 5],
    queryFn: () => api.getMetrics(5),
    refetchInterval: livePoll,
  });

  const agents = fleetData?.agents || [];
  const totalBurnRate = agents.reduce((sum, a) => sum + (a.usd_per_min || 0), 0);
  const totalSpend = roiData?.total_spend_usd ?? agents.reduce((sum, a) => sum + (a.spend_usd || 0), 0);
  const totalSaved = roiData?.saved_usd ?? 0;
  const interventions = roiData?.interventions ?? 0;
  const savedShown = useCountUp(totalSaved);

  const burn = useMemo(() => aggregateBurn(metricsData?.metrics ?? []), [metricsData]);

  const stateCounts = agents.reduce<Record<string, number>>((acc, a) => {
    acc[a.state] = (acc[a.state] || 0) + 1;
    return acc;
  }, {});

  const sortedAgents = sortFleetAgents(agents);
  const displayedAgents = filterState === 'all' ? sortedAgents : sortedAgents.filter((a) => a.state === filterState);

  const handleRefreshAll = () => {
    refetchFleet();
    refetchRoi();
  };

  const lastUpdated = agents[0]?.updated_at
    ? new Date(agents[0].updated_at).toLocaleTimeString()
    : new Date().toLocaleTimeString();

  const hot = totalBurnRate > 0.05;
  const spendBars = agents.map((a) => ({
    label: a.agent_id.toUpperCase(),
    note: `${fmtCompact(a.tokens_per_min)} tokens/min · loop ${a.loop_score.toFixed(2)}`,
    bars: [
      { name: 'Spend', color: 'var(--chart-violet)', value: a.spend_usd },
      { name: 'Budget', color: 'var(--chart-cyan)', value: a.budget_usd },
    ],
  }));

  const grid = (list: AgentView[]) => (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 'var(--space-5)' }}>
      {list.map((agent) => (
        <AgentCard key={agent.agent_id} agent={agent} onClick={() => navigate(`/agents/${agent.agent_id}`)} />
      ))}
    </div>
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-6)', width: '100%' }}>
      <header style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-end', justifyContent: 'space-between', gap: 'var(--space-4)' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
            <h1 style={{ fontSize: 'var(--type-title-md-size)', lineHeight: 'var(--type-title-md-lh)' }}>
              Fleet Telemetry Control
            </h1>
            <span className="chip" style={{ background: 'var(--color-state-healthy-bg)', color: 'var(--color-state-healthy)' }}>
              <span className="pulse-dot" style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--color-state-healthy)', color: 'var(--color-state-healthy)' }} />
              LIVE POLLING (1 HZ)
            </span>
          </div>
          <p style={{ color: 'var(--color-text-secondary)', marginTop: 4 }}>
            Autonomous circuit breaker monitoring, real-time token burn attribution, and incident quarantine.
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-4)' }}>
          <span className="tabular-nums" style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
            API :8000 · Updated {lastUpdated}
          </span>
          <button type="button" className="btn-navy" onClick={handleRefreshAll} aria-label="Refresh telemetry data" style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
            <RefreshCw size={13} /> Refresh
          </button>
        </div>
      </header>

      <div className="bento">
        {/* Hero: the three headline numbers + real fleet burn velocity */}
        <section className="card col-span-7" aria-label="Fleet economics" style={{ padding: 'var(--space-6)', display: 'flex', flexDirection: 'column', gap: 'var(--space-5)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 'var(--space-6)', flexWrap: 'wrap' }}>
            <div>
              <div className="kpi-label">TOTAL $ SAVED</div>
              <div className="kpi-value" style={{ fontSize: 44, lineHeight: 1.1, color: 'var(--color-state-healthy)' }}>
                ${savedShown.toFixed(4)}
              </div>
              <div style={{ fontSize: 13, color: 'var(--color-text-secondary)' }}>Saved via {interventions} automated stops</div>
            </div>
            <div style={{ display: 'flex', gap: 'var(--space-8)' }}>
              <div>
                <div className="kpi-label">TOTAL FLEET SPEND</div>
                <div className="kpi-value" style={{ fontSize: 24 }}>${totalSpend.toFixed(4)}</div>
              </div>
              <div>
                <div className="kpi-label">FLEET BURN RATE</div>
                <div className="kpi-value" style={{ fontSize: 24, color: hot ? 'var(--color-state-suspicious)' : 'var(--color-text-primary)' }}>
                  ${totalBurnRate.toFixed(4)}/min
                </div>
              </div>
            </div>
          </div>
          {burn.values.length >= 2 && Math.max(...burn.values) > 0 ? (
            <LineAreaChart
              testId="fleet-burn-chart"
              title="Token burn velocity"
              series={[{ name: 'Tokens per minute (all agents)', color: 'var(--chart-indigo)', values: burn.values }]}
              xLabels={burn.labels}
              format={(v) => `${fmtCompact(v)}/min`}
              height={250}
            />
          ) : (
            <p style={{ color: 'var(--color-text-muted)', padding: 'var(--space-8) 0' }}>
              No token flow to chart yet: it appears once running agents report a few samples.
            </p>
          )}
        </section>

        <div className="col-span-5" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-5)', minWidth: 0 }}>
          <div className="bento" style={{ gap: 'var(--space-5)' }}>
            <section className="card col-span-6" aria-label="Interventions" style={{ padding: 'var(--space-5)' }}>
              <div className="kpi-label">INTERVENTIONS</div>
              <div className="kpi-value" style={{ fontSize: 34, marginTop: 4 }}>{interventions}</div>
              <div style={{ fontSize: 13, color: 'var(--color-text-secondary)' }}>
                {roiData?.tool_calls_held || 0} tool calls held at gate
              </div>
            </section>
            <section className="card col-span-6" aria-label="Agents by state" style={{ padding: 'var(--space-5)' }}>
              <div className="kpi-label">AGENTS BY STATE</div>
              <div className="kpi-value" style={{ fontSize: 34, marginTop: 4 }}>{agents.length} Total</div>
              <div style={{ display: 'flex', height: 6, borderRadius: 3, overflow: 'hidden', background: 'var(--color-fill)', gap: 2, marginTop: 8 }}>
                {STATE_SEGMENTS.map((s) => (
                  <div key={s.key} className="meter-fill" style={{ width: `${((stateCounts[s.key] || 0) / (agents.length || 1)) * 100}%`, background: s.color }} />
                ))}
              </div>
              <div style={{ fontSize: 12, color: 'var(--color-text-secondary)', marginTop: 8, display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                <span style={{ color: 'var(--color-state-healthy)' }}>{stateCounts.healthy || 0} healthy</span>
                <span style={{ color: 'var(--color-state-suspicious)' }}>{stateCounts.suspicious || 0} suspicious</span>
                <span style={{ color: 'var(--color-state-paused)' }}>{stateCounts.paused || 0} paused</span>
                <span style={{ color: 'var(--color-state-killed)' }}>{stateCounts.killed || 0} killed</span>
              </div>
            </section>
          </div>
          <section className="card" aria-label="Spend against budget" style={{ padding: 'var(--space-5) var(--space-6)', flex: 1 }}>
            <GroupedBars testId="node-comparison-chart" title="Spend against budget" groups={spendBars} format={money} height={230} />
          </section>
        </div>
      </div>

      <div className="bento" style={{ alignItems: 'stretch' }}>
        <div className="col-span-8" style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          <Panel
            title="Fleet Node Telemetry"
            icon={<Cpu size={18} />}
            loading={loadingFleet || loadingRoi}
            error={errorFleet || errorRoi}
            empty={agents.length === 0}
            emptyTitle="No Agents Running"
            emptyMessage="No agents yet: start one with python -m brain --fake"
            onRetry={handleRefreshAll}
            actions={
              <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
                {hasNodes(agents) && (
                  <button
                    type="button"
                    aria-label="Group agents by node"
                    aria-pressed={byNode}
                    onClick={() => setByNode((v) => !v)}
                    style={{ padding: '3px 10px', borderRadius: 999, fontSize: 12, fontWeight: 600, color: byNode ? '#fff' : 'var(--color-text-secondary)', background: byNode ? 'var(--color-accent)' : 'var(--color-fill)' }}
                  >
                    BY NODE
                  </button>
                )}
                <Filter size={14} color="var(--color-text-muted)" />
                <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                  {(['all', 'healthy', 'suspicious', 'paused', 'killed'] as const).map((st) => {
                    const count = st === 'all' ? agents.length : stateCounts[st] || 0;
                    const isSelected = filterState === st;
                    return (
                      <button
                        key={st}
                        type="button"
                        onClick={() => setFilterState(st)}
                        aria-label={`Filter by ${st}`}
                        style={{ padding: '3px 10px', borderRadius: 999, fontSize: 12, fontWeight: isSelected ? 700 : 500, background: isSelected ? 'var(--color-navy)' : 'transparent', color: isSelected ? '#fff' : 'var(--color-text-secondary)', textTransform: 'uppercase' }}
                      >
                        {st} ({count})
                      </button>
                    );
                  })}
                </div>
              </div>
            }
          >
            {byNode && hasNodes(agents) ? (
              <div data-testid="fleet-agent-grid" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-5)' }}>
                {groupByNode(displayedAgents).map((g) => (
                  <section key={g.node} aria-label={`Node ${g.node}`}>
                    <h3 style={{ fontSize: 12, color: 'var(--color-text-secondary)', marginBottom: 'var(--space-2)' }}>
                      node: {g.node} · {g.agents.length} agent{g.agents.length === 1 ? '' : 's'}
                    </h3>
                    {grid(g.agents)}
                  </section>
                ))}
              </div>
            ) : (
              <div data-testid="fleet-agent-grid">{grid(displayedAgents)}</div>
            )}
          </Panel>
        </div>

        <section className="card col-span-4" aria-label="Quarantine and decision feed" style={{ padding: 'var(--space-5) var(--space-6)', display: 'flex', flexDirection: 'column' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 'var(--space-3)', fontWeight: 600, fontSize: 15 }}>
            <Terminal size={15} color="var(--color-accent)" /> Quarantine &amp; Decision Feed
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)', flex: 1 }}>
            {displayedAgents.map((ag) => {
              let badgeText = 'NOMINAL';
              let badgeColor = 'var(--color-state-healthy)';
              let msg = 'Operating within baseline limits';
              if (ag.last_verdict) {
                badgeText = ag.last_verdict.action;
                badgeColor = ag.last_verdict.action === 'KILL' ? 'var(--color-state-killed)' : 'var(--color-state-paused)';
                msg = ag.last_verdict.reason;
              } else if (ag.state === 'paused') {
                badgeText = 'PAUSED';
                badgeColor = 'var(--color-state-paused)';
                msg = 'Circuit breaker quarantine active';
              } else if (ag.state === 'killed') {
                badgeText = 'KILLED';
                badgeColor = 'var(--color-state-killed)';
                msg = 'Terminated by hard limit policy';
              }
              return (
                <div key={ag.agent_id} style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 2, padding: 'var(--space-3)', borderRadius: 12, background: 'var(--color-fill)' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontWeight: 600, fontSize: 13 }}>Node: {ag.agent_id.toUpperCase()}</span>
                    <span style={{ fontSize: 11, fontWeight: 700, padding: '1px 8px', borderRadius: 999, color: badgeColor, background: `color-mix(in srgb, ${badgeColor} 12%, transparent)` }}>
                      {badgeText}
                    </span>
                  </div>
                  <div style={{ color: 'var(--color-text-secondary)', fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={msg}>
                    {msg}
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      </div>
    </div>
  );
};
