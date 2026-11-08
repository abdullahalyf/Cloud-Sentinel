import { livePoll } from '../lib/live';
import React, { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  DollarSign,
  Activity,
  ShieldAlert,
  Cpu,
  RefreshCw,
  Filter,
  BarChart2,
  Terminal,
  TrendingUp,
} from 'lucide-react';
import { api } from '../api/client';
import type { AgentState, AgentView } from '../api/types';
import { Panel } from '../components/Panel';
import { AgentCard } from '../components/AgentCard';
import { useCountUp } from '../lib/useCountUp';
import { areaFromLine, fmtCompact, smoothPath, useRollingSeries } from '../components/charts';

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

/* ───────── Live multi-series chart: token burn velocity (area) vs circuit-breaker savings (bars) ───────── */
const HERO_W = 640;
const HERO_H = 340;
const HERO_PAD = { l: 8, r: 14, t: 14, b: 22 };

const HeroChart = React.memo<{ burn: number[]; saves: number[] }>(({ burn, saves }) => {
  const innerW = HERO_W - HERO_PAD.l - HERO_PAD.r;
  const innerH = HERO_H - HERO_PAD.t - HERO_PAD.b;
  const baseY = HERO_PAD.t + innerH;
  const n = burn.length;
  if (n < 2) return <div style={{ height: HERO_H }} />;

  const burnMax = Math.max(1, ...burn) * 1.15;
  const saveMax = Math.max(1e-9, ...saves);
  const xAt = (i: number) => HERO_PAD.l + (i / (n - 1)) * innerW;
  const pts = burn.map((v, i) => ({ x: xAt(i), y: baseY - (v / burnMax) * innerH }));
  const line = smoothPath(pts);
  const last = pts[pts.length - 1];
  const barW = Math.max(4, innerW / n - 4);

  return (
    <svg
      viewBox={`0 0 ${HERO_W} ${HERO_H}`}
      role="img"
      aria-label="Fleet token burn velocity versus circuit-breaker savings"
      data-testid="fleet-hero-chart"
      style={{ width: '100%', height: 'auto', display: 'block', overflow: 'visible' }}
    >
      <defs>
        <linearGradient id="heroBurn" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#06B6D4" stopOpacity="0.42" />
          <stop offset="100%" stopColor="#06B6D4" stopOpacity="0" />
        </linearGradient>
        <linearGradient id="heroSave" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#34D399" />
          <stop offset="100%" stopColor="#10B981" stopOpacity="0.35" />
        </linearGradient>
      </defs>
      {[0, 0.25, 0.5, 0.75, 1].map((f) => (
        <line
          key={f}
          x1={HERO_PAD.l}
          x2={HERO_W - HERO_PAD.r}
          y1={baseY - f * innerH}
          y2={baseY - f * innerH}
          stroke="rgba(255,255,255,0.07)"
          strokeDasharray={f === 0 ? undefined : '3 5'}
        />
      ))}
      {saves.map((v, i) => {
        if (v <= 0) return null;
        const h = Math.max(6, (v / saveMax) * innerH * 0.8);
        return (
          <rect
            key={i}
            className="bar-rise"
            x={xAt(i) - barW / 2}
            y={baseY - h}
            width={barW}
            height={h}
            rx={2}
            fill="url(#heroSave)"
          />
        );
      })}
      <path d={areaFromLine(line, last, pts[0], baseY)} fill="url(#heroBurn)" />
      <path
        d={line}
        fill="none"
        stroke="#22D3EE"
        strokeWidth="2.4"
        strokeLinecap="round"
      />
      <circle className="live-dot" cx={last.x} cy={last.y} r="4" fill="#22D3EE" opacity="0.6" />
      <circle cx={last.x} cy={last.y} r="4.5" fill="#22D3EE" stroke="#05070B" strokeWidth="2" />
      <text x={HERO_PAD.l} y={HERO_H - 4} fontSize="10" fontFamily="var(--font-mono)" fill="#94A3B8">
        −{n}s
      </text>
      <text
        x={HERO_W - HERO_PAD.r}
        y={HERO_H - 4}
        fontSize="10"
        textAnchor="end"
        fontFamily="var(--font-mono)"
        fill="#94A3B8"
      >
        NOW
      </text>
      <text
        x={last.x - 10}
        y={Math.max(11, last.y - 10)}
        fontSize="11"
        textAnchor="end"
        fontWeight="700"
        fontFamily="var(--font-mono)"
        fill="#67E8F9"
      >
        {fmtCompact(burn[n - 1])} tok/min
      </text>
    </svg>
  );
});

/* ───────── Live node comparison: Tokens/min vs Loop Score per agent ───────── */
const NodeComparison = React.memo<{ agents: AgentView[] }>(({ agents }) => {
  const W = 520;
  const H = 190;
  const padB = 26;
  const padT = 20;
  const innerH = H - padB - padT;
  const list = agents.slice(0, 4);
  const maxTokens = Math.max(1, ...list.map((a) => a.tokens_per_min));
  const slot = W / Math.max(1, list.length);
  const barW = Math.min(30, slot / 3.2);

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      aria-label="Tokens per minute and loop score by agent"
      data-testid="node-comparison-chart"
      style={{ width: '100%', height: 'auto', display: 'block' }}
    >
      {[0, 0.5, 1].map((f) => (
        <line
          key={f}
          x1={0}
          x2={W}
          y1={padT + innerH - f * innerH}
          y2={padT + innerH - f * innerH}
          stroke="rgba(255,255,255,0.07)"
          strokeDasharray={f === 0 ? undefined : '3 5'}
        />
      ))}
      {list.map((a, i) => {
        const cx = slot * i + slot / 2;
        const halted = a.state === 'killed' || a.state === 'paused';
        const tokH = Math.max(3, (a.tokens_per_min / maxTokens) * innerH);
        const loop = Math.max(0, Math.min(1, a.loop_score));
        const loopH = Math.max(3, loop * innerH);
        const tokColor = halted ? '#F43F5E' : '#06B6D4';
        const loopColor = loop >= 0.6 ? '#F43F5E' : loop >= 0.4 ? '#F59E0B' : '#818CF8';
        return (
          <g key={a.agent_id}>
            <rect
              className="bar-rise"
              style={{ animationDelay: `${i * 110}ms` }}
              x={cx - barW - 2}
              y={padT + innerH - tokH}
              width={barW}
              height={tokH}
              rx={3}
              fill={tokColor}
              fillOpacity={0.9}
            />
            <rect
              className="bar-rise"
              style={{ animationDelay: `${i * 110 + 60}ms` }}
              x={cx + 2}
              y={padT + innerH - loopH}
              width={barW}
              height={loopH}
              rx={3}
              fill={loopColor}
              fillOpacity={0.9}
            />
            <text
              x={cx - barW / 2 - 2}
              y={padT + innerH - tokH - 5}
              fontSize="10"
              fontWeight="700"
              textAnchor="middle"
              fontFamily="var(--font-mono)"
              fill={tokColor}
            >
              {fmtCompact(a.tokens_per_min)}
            </text>
            <text
              x={cx + barW / 2 + 2}
              y={padT + innerH - loopH - 5}
              fontSize="10"
              fontWeight="700"
              textAnchor="middle"
              fontFamily="var(--font-mono)"
              fill={loopColor}
            >
              {loop.toFixed(2)}
            </text>
            <text
              x={cx}
              y={H - 8}
              fontSize="11"
              fontWeight="600"
              textAnchor="middle"
              fontFamily="var(--font-mono)"
              fill="#E2E8F0"
            >
              {a.agent_id.toUpperCase()}
            </text>
          </g>
        );
      })}
    </svg>
  );
});

const Legend: React.FC<{ items: { color: string; label: string }[] }> = ({ items }) => (
  <div style={{ display: 'flex', gap: 'var(--space-3)', flexWrap: 'wrap' }}>
    {items.map((it) => (
      <span
        key={it.label}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 6,
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          color: 'var(--color-text-secondary)',
        }}
      >
        <span style={{ width: 10, height: 10, borderRadius: 2, background: it.color }} />
        {it.label}
      </span>
    ))}
  </div>
);

export const FleetView: React.FC = () => {
  const navigate = useNavigate();
  const [filterState, setFilterState] = useState<AgentState | 'all'>('all');

  // Fetch live fleet data
  const {
    data: fleetData,
    isLoading: loadingFleet,
    error: errorFleet,
    refetch: refetchFleet,
    dataUpdatedAt: fleetStamp,
  } = useQuery({
    queryKey: ['fleet'],
    queryFn: api.getFleet,
    refetchInterval: livePoll,
  });

  // Fetch live ROI telemetry
  const {
    data: roiData,
    isLoading: loadingRoi,
    error: errorRoi,
    refetch: refetchRoi,
  } = useQuery({
    queryKey: ['roi'],
    queryFn: api.getRoi,
    refetchInterval: livePoll,
  });

  const agents = fleetData?.agents || [];
  const totalBurnRate = agents.reduce((sum, a) => sum + (a.usd_per_min || 0), 0);
  const totalTokensPerMin = agents.reduce((sum, a) => sum + (a.tokens_per_min || 0), 0);
  const totalSpend =
    roiData?.total_spend_usd ?? agents.reduce((sum, a) => sum + (a.spend_usd || 0), 0);
  const totalSaved = roiData?.saved_usd ?? 0;
  const interventions = roiData?.interventions ?? 0;

  // Live rolling telemetry: seeded history, then one real sample per refresh
  const burnSeries = useRollingSeries(
    agents.length ? totalTokensPerMin : undefined,
    fleetStamp,
    'fleet-burn'
  );
  const prevSaved = useRef<number | undefined>(undefined);
  const savedDelta = prevSaved.current === undefined ? 0 : Math.max(0, totalSaved - prevSaved.current);
  const saveSeries = useRollingSeries(
    roiData ? savedDelta : undefined,
    fleetStamp,
    'fleet-saves',
    36,
    'spikes'
  );
  useEffect(() => {
    if (roiData) prevSaved.current = totalSaved;
  }, [fleetStamp, roiData, totalSaved]);

  // Breakdown by state
  const stateCounts = agents.reduce<Record<string, number>>((acc, a) => {
    acc[a.state] = (acc[a.state] || 0) + 1;
    return acc;
  }, {});

  const sortedAgents = sortFleetAgents(agents);
  const displayedAgents =
    filterState === 'all' ? sortedAgents : sortedAgents.filter((a) => a.state === filterState);

  const handleRefreshAll = () => {
    refetchFleet();
    refetchRoi();
  };

  const lastUpdated = agents[0]?.updated_at
    ? new Date(agents[0].updated_at).toLocaleTimeString()
    : new Date().toLocaleTimeString();

  const savedShown = useCountUp(totalSaved);
  const hot = totalBurnRate > 0.05;
  const segs: { key: string; color: string }[] = [
    { key: 'healthy', color: 'var(--color-state-healthy)' },
    { key: 'probation', color: 'var(--color-state-probation)' },
    { key: 'suspicious', color: 'var(--color-state-suspicious)' },
    { key: 'paused', color: 'var(--color-state-paused)' },
    { key: 'killed', color: 'var(--color-state-killed)' },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)', width: '100%' }}>
      {/* Header */}
      <div
        className="glass"
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 'var(--space-4)',
          padding: 'var(--space-4) var(--space-6)',
        }}
      >
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
            <h1
              style={{
                fontSize: 'var(--type-title-sm-size)',
                lineHeight: 'var(--type-title-sm-lh)',
                fontWeight: 600,
                letterSpacing: '-0.01em',
                color: 'var(--color-text-primary)',
              }}
            >
              Fleet Telemetry Control
            </h1>
            <span
              className="chip"
              style={{
                backgroundColor: 'var(--color-state-healthy-bg)',
                color: 'var(--color-state-healthy)',
                border: '1px solid var(--color-state-healthy-border)',
              }}
            >
              <span
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: '50%',
                  backgroundColor: 'var(--color-state-healthy)',
                  boxShadow: '0 0 6px var(--color-state-healthy)',
                }}
              />
              LIVE POLLING (1 HZ)
            </span>
          </div>
          <p style={{ color: 'var(--color-text-secondary)', marginTop: 'var(--space-1)' }}>
            Autonomous circuit breaker monitoring, real-time token burn attribution, and incident
            quarantine.
          </p>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-4)' }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 'var(--space-2)',
              fontSize: 'var(--type-micro-size)',
              fontFamily: 'var(--font-mono)',
              color: 'var(--color-text-muted)',
            }}
          >
            <span>
              <span style={{ color: 'var(--color-accent)' }}>API:</span> :8000
            </span>
            <span>·</span>
            <span>
              Updated: <span style={{ color: 'var(--color-text-primary)' }}>{lastUpdated}</span>
            </span>
          </div>
          <button
            type="button"
            onClick={handleRefreshAll}
            aria-label="Refresh telemetry data"
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 'var(--space-2)',
              padding: 'var(--space-2) var(--space-4)',
              backgroundColor: 'rgba(255,255,255,0.05)',
              border: '1px solid rgba(255,255,255,0.1)',
              borderRadius: 'var(--radius-md)',
              color: 'var(--color-text-primary)',
              fontSize: 'var(--type-body-sm-size)',
              fontWeight: 600,
            }}
          >
            <RefreshCw size={13} />
            Refresh
          </button>
        </div>
      </div>

      {/* Asymmetric telemetry deck */}
      <div className="bento">
        {/* Hero (col-span-5): the three headline KPIs + live multi-series graph */}
        <div
          className="glass col-span-5"
          style={{
            padding: 'var(--space-5)',
            display: 'flex',
            flexDirection: 'column',
            gap: 'var(--space-4)',
            overflow: 'hidden',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <div>
              <div className="kpi-label" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                TOTAL $ SAVED <DollarSign size={13} color="var(--color-state-healthy)" />
              </div>
              <div
                className="kpi-value"
                style={{
                  fontSize: 38,
                  lineHeight: 1.15,
                  color: 'var(--color-state-healthy)',
                  textShadow: '0 0 24px rgba(16, 185, 129, 0.35)',
                }}
              >
                ${savedShown.toFixed(4)}
              </div>
              <div style={{ fontSize: 'var(--type-micro-size)', color: 'var(--color-text-secondary)' }}>
                Saved via {interventions} automated stops
              </div>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)', textAlign: 'right' }}>
              <div>
                <div className="kpi-label">TOTAL FLEET SPEND</div>
                <div className="kpi-value" style={{ fontSize: 20 }}>
                  ${totalSpend.toFixed(4)}
                </div>
              </div>
              <div>
                <div className="kpi-label" style={{ display: 'flex', justifyContent: 'flex-end', gap: 6 }}>
                  FLEET BURN RATE
                  <Activity size={13} color={hot ? 'var(--color-state-suspicious)' : 'var(--color-text-muted)'} />
                </div>
                <div
                  className="kpi-value"
                  style={{ fontSize: 20, color: hot ? 'var(--color-state-suspicious)' : 'var(--color-cyan)' }}
                >
                  ${totalBurnRate.toFixed(4)}/min
                </div>
              </div>
            </div>
          </div>

          <div style={{ marginTop: 'auto' }}>
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                marginBottom: 6,
                flexWrap: 'wrap',
                gap: 8,
              }}
            >
              <span className="kpi-label" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <TrendingUp size={13} color="var(--color-cyan)" /> Token Burn Velocity vs Circuit-Breaker Savings
              </span>
              <Legend
                items={[
                  { color: '#06B6D4', label: 'Burn velocity' },
                  { color: '#10B981', label: 'Savings' },
                ]}
              />
            </div>
            <HeroChart burn={burnSeries} saves={saveSeries} />
          </div>
        </div>

        {/* Right staggered stack (col-span-7) */}
        <div className="col-span-7 bento" style={{ gridTemplateRows: 'auto 1fr', alignContent: 'stretch' }}>
          {/* Interventions */}
          <div
            className="glass col-span-5"
            style={{ padding: 'var(--space-4) var(--space-5)', display: 'flex', flexDirection: 'column', gap: 6 }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span className="kpi-label">INTERVENTIONS</span>
              <ShieldAlert size={16} color="var(--color-telemetry-cyan)" />
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
              <div className="kpi-value" style={{ fontSize: 34, color: 'var(--color-telemetry-cyan)' }}>
                {interventions}
              </div>
              <span
                className="chip"
                style={{ backgroundColor: 'rgba(6,182,212,0.14)', color: 'var(--color-telemetry-cyan)' }}
              >
                CIRCUIT TRIPPED
              </span>
            </div>
            <div style={{ fontSize: 'var(--type-micro-size)', color: 'var(--color-text-secondary)' }}>
              {roiData?.tool_calls_held || 0} tool calls held at gate
            </div>
          </div>

          {/* Agents by state */}
          <div
            className="glass col-span-7"
            style={{ padding: 'var(--space-4) var(--space-5)', display: 'flex', flexDirection: 'column', gap: 8 }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span className="kpi-label">AGENTS BY STATE</span>
              <Cpu size={16} color="var(--color-text-secondary)" />
            </div>
            <div className="kpi-value" style={{ fontSize: 34 }}>
              {agents.length} Total
            </div>
            <div
              style={{
                height: 8,
                width: '100%',
                display: 'flex',
                borderRadius: 4,
                overflow: 'hidden',
                backgroundColor: 'rgba(255,255,255,0.07)',
                gap: 2,
              }}
            >
              {segs.map((s) => (
                <div
                  key={s.key}
                  className="meter-fill"
                  style={{
                    width: `${((stateCounts[s.key] || 0) / (agents.length || 1)) * 100}%`,
                    backgroundColor: s.color,
                  }}
                />
              ))}
            </div>
            <div
              style={{
                fontSize: 11,
                fontFamily: 'var(--font-mono)',
                display: 'flex',
                justifyContent: 'space-between',
                flexWrap: 'wrap',
                gap: 8,
              }}
            >
              <span style={{ color: 'var(--color-state-healthy)' }}>{stateCounts.healthy || 0} healthy</span>
              <span style={{ color: 'var(--color-state-suspicious)' }}>
                {stateCounts.suspicious || 0} suspicious
              </span>
              <span style={{ color: 'var(--color-state-paused)' }}>{stateCounts.paused || 0} paused</span>
              <span style={{ color: 'var(--color-state-killed)' }}>{stateCounts.killed || 0} killed</span>
            </div>
          </div>

          {/* Live node comparison */}
          <div
            className="glass col-span-12"
            style={{ padding: 'var(--space-4) var(--space-5)', display: 'flex', flexDirection: 'column', gap: 8 }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
              <span className="kpi-label" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <BarChart2 size={14} color="var(--color-accent)" /> Node Burn &amp; Loop Comparison
              </span>
              <Legend
                items={[
                  { color: '#06B6D4', label: 'Tokens/min' },
                  { color: '#818CF8', label: 'Loop Score' },
                  { color: '#F43F5E', label: 'Paused / runaway' },
                ]}
              />
            </div>
            <NodeComparison agents={agents} />
          </div>
        </div>
      </div>

      {/* Fleet matrix (col-span-8) + quarantine rail (col-span-4) */}
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
                <Filter size={14} color="var(--color-text-muted)" />
                <div style={{ display: 'flex', gap: 'var(--space-1)', flexWrap: 'wrap' }}>
                  {(['all', 'healthy', 'suspicious', 'paused', 'killed'] as const).map((st) => {
                    const count = st === 'all' ? agents.length : stateCounts[st] || 0;
                    const isSelected = filterState === st;
                    return (
                      <button
                        key={st}
                        type="button"
                        onClick={() => setFilterState(st)}
                        aria-label={`Filter by ${st}`}
                        style={{
                          padding: '2px 8px',
                          borderRadius: 'var(--radius-sm)',
                          fontSize: 'var(--type-micro-size)',
                          fontFamily: 'var(--font-mono)',
                          fontWeight: isSelected ? 700 : 500,
                          backgroundColor: isSelected ? 'rgba(6,182,212,0.14)' : 'transparent',
                          color: isSelected ? 'var(--color-text-primary)' : 'var(--color-text-muted)',
                          border: isSelected
                            ? '1px solid var(--color-border-accent)'
                            : '1px solid transparent',
                          textTransform: 'uppercase',
                        }}
                      >
                        {st} ({count})
                      </button>
                    );
                  })}
                </div>
              </div>
            }
          >
            <div
              data-testid="fleet-agent-grid"
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
                gap: 'var(--space-4)',
              }}
            >
              {displayedAgents.map((agent) => (
                <AgentCard
                  key={agent.agent_id}
                  agent={agent}
                  onClick={() => navigate(`/agents/${agent.agent_id}`)}
                />
              ))}
            </div>
          </Panel>
        </div>

        {/* Quarantine & decision feed */}
        <div
          className="glass col-span-4"
          style={{ padding: 'var(--space-4) var(--space-5)', display: 'flex', flexDirection: 'column' }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', marginBottom: 'var(--space-3)' }}>
            <Terminal size={15} color="var(--color-telemetry-cyan)" />
            <span className="kpi-label" style={{ color: 'var(--color-text-primary)' }}>
              Quarantine &amp; Decision Feed
            </span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)', fontFamily: 'var(--font-mono)', flex: 1 }}>
            {displayedAgents.map((ag) => {
              let badgeText = 'NOMINAL';
              let badgeColor = 'var(--color-state-healthy)';
              let msg = 'Operating within baseline limits';

              if (ag.last_verdict) {
                badgeText = ag.last_verdict.action;
                badgeColor =
                  ag.last_verdict.action === 'KILL'
                    ? 'var(--color-state-killed)'
                    : 'var(--color-state-paused)';
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
                <div
                  key={ag.agent_id}
                  style={{
                    flex: 1,
                    justifyContent: 'center',
                    padding: 'var(--space-2) var(--space-3)',
                    backgroundColor: 'rgba(5,7,11,0.55)',
                    border: '1px solid rgba(255,255,255,0.07)',
                    borderRadius: 8,
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 2,
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontWeight: 700, fontSize: 12, color: 'var(--color-text-primary)' }}>
                      Node: {ag.agent_id.toUpperCase()}
                    </span>
                    <span
                      style={{
                        fontSize: 10,
                        padding: '1px 6px',
                        borderRadius: 3,
                        fontWeight: 700,
                        backgroundColor: `color-mix(in srgb, ${badgeColor} 14%, transparent)`,
                        color: badgeColor,
                        border: `1px solid color-mix(in srgb, ${badgeColor} 40%, transparent)`,
                      }}
                    >
                      {badgeText}
                    </span>
                  </div>
                  <div
                    style={{
                      color: 'var(--color-text-secondary)',
                      fontSize: 11,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                    title={msg}
                  >
                    {msg}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
};
