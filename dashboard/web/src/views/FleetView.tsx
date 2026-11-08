import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  DollarSign,
  TrendingUp,
  Activity,
  ShieldAlert,
  Cpu,
  RefreshCw,
  Filter,
  BarChart2,
  Terminal,
} from 'lucide-react';
import { api } from '../api/client';
import type { AgentState, AgentView } from '../api/types';
import { Panel } from '../components/Panel';
import { AgentCard } from '../components/AgentCard';

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

export const FleetView: React.FC = () => {
  const navigate = useNavigate();
  const [filterState, setFilterState] = useState<AgentState | 'all'>('all');

  // Fetch live fleet data
  const {
    data: fleetData,
    isLoading: loadingFleet,
    error: errorFleet,
    refetch: refetchFleet,
  } = useQuery({
    queryKey: ['fleet'],
    queryFn: api.getFleet,
    refetchInterval: 1000,
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
    refetchInterval: 1000,
  });

  const agents = fleetData?.agents || [];
  const totalBurnRate = agents.reduce((sum, a) => sum + (a.usd_per_min || 0), 0);
  const totalSpend =
    roiData?.total_spend_usd ?? agents.reduce((sum, a) => sum + (a.spend_usd || 0), 0);
  const totalSaved = roiData?.saved_usd ?? 0;
  const interventions = roiData?.interventions ?? 0;

  // Breakdown by state
  const stateCounts = agents.reduce<Record<string, number>>((acc, a) => {
    acc[a.state] = (acc[a.state] || 0) + 1;
    return acc;
  }, {});

  // Apply sorting and filtering
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

  // Deterministic 20-interval Area + Bar Sparkline points for Total $ Saved Hero Card
  const heroSparklinePoints = [
    { x: 0, burn: 18, saved: 25 },
    { x: 1, burn: 24, saved: 32 },
    { x: 2, burn: 22, saved: 40 },
    { x: 3, burn: 35, saved: 48 },
    { x: 4, burn: 45, saved: 60 },
    { x: 5, burn: 52, saved: 75 },
    { x: 6, burn: 48, saved: 82 },
    { x: 7, burn: 65, saved: 95 },
    { x: 8, burn: 78, saved: 110 },
    { x: 9, burn: 70, saved: 118 },
    { x: 10, burn: 85, saved: 125 },
    { x: 11, burn: 62, saved: 128 },
    { x: 12, burn: 58, saved: 130 },
    { x: 13, burn: 74, saved: 132 },
    { x: 14, burn: 80, saved: 134 },
    { x: 15, burn: 68, saved: 136 },
    { x: 16, burn: 72, saved: 138 },
    { x: 17, burn: 84, saved: 140 },
    { x: 18, burn: 90, saved: 142 },
    { x: 19, burn: 78, saved: 144 },
  ];

  const maxSavedY = 160;
  const sparkWidth = 460;
  const sparkHeight = 75;

  const savedLinePath = heroSparklinePoints.reduce((acc, pt, i) => {
    const px = (pt.x / 19) * sparkWidth;
    const py = sparkHeight - (pt.saved / maxSavedY) * (sparkHeight - 10) - 5;
    return `${acc} ${i === 0 ? 'M' : 'L'} ${px.toFixed(1)} ${py.toFixed(1)}`;
  }, '');

  const savedAreaPath = `${savedLinePath} L ${sparkWidth} ${sparkHeight} L 0 ${sparkHeight} Z`;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-6)', width: '100%' }}>
      {/* Live Telemetry Header Bar */}
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 'var(--space-4)',
          backgroundColor: 'var(--color-surface)',
          border: '1px solid var(--color-border)',
          borderRadius: 'var(--radius-md)',
          padding: 'var(--space-4) var(--space-6)',
        }}
      >
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
            <h1
              style={{
                fontSize: 'var(--type-title-sm-size)',
                lineHeight: 'var(--type-title-sm-lh)',
                fontWeight: 700,
                color: 'var(--color-text-primary)',
              }}
            >
              Fleet Telemetry Control
            </h1>
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '4px',
                fontSize: 'var(--type-micro-size)',
                fontFamily: 'var(--font-mono)',
                backgroundColor: 'var(--color-state-healthy-bg)',
                color: 'var(--color-state-healthy)',
                border: '1px solid var(--color-state-healthy-border)',
                padding: '2px 8px',
                borderRadius: 'var(--radius-sm)',
                fontWeight: 600,
              }}
            >
              <span
                style={{
                  width: '6px',
                  height: '6px',
                  borderRadius: '50%',
                  backgroundColor: 'var(--color-state-healthy)',
                  boxShadow: '0 0 6px var(--color-state-healthy)',
                }}
              />
              LIVE POLLING (1 HZ)
            </span>
          </div>
          <p
            style={{
              fontSize: 'var(--type-body-sm-size)',
              color: 'var(--color-text-secondary)',
              marginTop: 'var(--space-1)',
            }}
          >
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
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
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
              backgroundColor: 'var(--color-surface-elevated)',
              border: '1px solid var(--color-border)',
              borderRadius: 'var(--radius-sm)',
              color: 'var(--color-text-primary)',
              fontSize: 'var(--type-body-sm-size)',
              fontWeight: 600,
              cursor: 'pointer',
              transition: 'background-color var(--transition-fast)',
            }}
            onMouseEnter={(e) =>
              (e.currentTarget.style.backgroundColor = 'var(--color-surface-elevated)')
            }
            onMouseLeave={(e) =>
              (e.currentTarget.style.backgroundColor = 'var(--color-surface-elevated)')
            }
          >
            <RefreshCw size={13} />
            Refresh
          </button>
        </div>
      </div>

      {/* Asymmetric 12-Column Bento Top Telemetry Zone */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(12, minmax(0, 1fr))',
          gap: 'var(--space-4)',
          width: '100%',
        }}
      >
        {/* Left Hero Panel (col-span-5): TOTAL $ SAVED + Live SVG Area & Bar Sparkline */}
        <div
          style={{
            gridColumn: 'span 5',
            backgroundColor: 'var(--color-surface)',
            border: '1px solid var(--color-border)',
            borderRadius: 'var(--radius-md)',
            padding: 'var(--space-5)',
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'space-between',
            position: 'relative',
            overflow: 'hidden',
          }}
        >
          <div>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                marginBottom: 'var(--space-1)',
              }}
            >
              <span
                style={{
                  fontSize: 'var(--type-micro-size)',
                  fontFamily: 'var(--font-mono)',
                  textTransform: 'uppercase',
                  letterSpacing: '0.06em',
                  color: 'var(--color-text-muted)',
                  fontWeight: 600,
                }}
              >
                TOTAL $ SAVED
              </span>
              <DollarSign size={18} color="var(--color-state-healthy)" />
            </div>

            <div
              className="tabular-nums"
              style={{
                fontSize: '32px',
                lineHeight: '1.2',
                fontWeight: 700,
                fontFamily: 'var(--font-mono)',
                color: 'var(--color-state-healthy)',
                textShadow: '0 0 16px rgba(16, 185, 129, 0.3)',
              }}
            >
              ${totalSaved.toFixed(4)}
            </div>

            <div
              style={{
                fontSize: 'var(--type-micro-size)',
                color: 'var(--color-text-secondary)',
                marginTop: '4px',
              }}
            >
              Saved via {interventions} automated stops
            </div>
          </div>

          {/* Up-and-Down Live Area & Bar Histogram Sparkline */}
          <div style={{ marginTop: 'var(--space-4)' }}>
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                fontSize: '10px',
                fontFamily: 'var(--font-mono)',
                color: 'var(--color-text-muted)',
                marginBottom: '4px',
              }}
            >
              <span>REAL-TIME INTERVENTION TRAJECTORY</span>
              <span style={{ color: 'var(--color-state-healthy)' }}>+20 INTERVALS</span>
            </div>
            <div style={{ width: '100%', height: '70px', position: 'relative' }}>
              <svg
                viewBox={`0 0 ${sparkWidth} ${sparkHeight}`}
                preserveAspectRatio="none"
                style={{ width: '100%', height: '100%', overflow: 'visible' }}
              >
                <defs>
                  <linearGradient id="heroSavingsGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#10B981" stopOpacity="0.35" />
                    <stop offset="100%" stopColor="#10B981" stopOpacity="0.0" />
                  </linearGradient>
                </defs>
                {/* Background vertical velocity bars */}
                {heroSparklinePoints.map((pt, i) => {
                  const bx = (pt.x / 19) * sparkWidth;
                  const barH = (pt.burn / 100) * 45;
                  return (
                    <rect
                      key={i}
                      x={bx - 4}
                      y={sparkHeight - barH}
                      width={8}
                      height={barH}
                      fill="rgba(6, 182, 212, 0.18)"
                      rx={1}
                    />
                  );
                })}
                {/* Area Gradient */}
                <path d={savedAreaPath} fill="url(#heroSavingsGrad)" />
                {/* Cumulative Line */}
                <path
                  d={savedLinePath}
                  fill="none"
                  stroke="var(--color-state-healthy)"
                  strokeWidth="2.2"
                  strokeLinecap="round"
                />
              </svg>
            </div>
          </div>
        </div>

        {/* Middle Stack (col-span-4): TOTAL FLEET SPEND + FLEET BURN RATE */}
        <div
          style={{
            gridColumn: 'span 4',
            display: 'flex',
            flexDirection: 'column',
            gap: 'var(--space-4)',
          }}
        >
          {/* Total Fleet Spend Card */}
          <div
            style={{
              backgroundColor: 'var(--color-surface)',
              border: '1px solid var(--color-border)',
              borderRadius: 'var(--radius-md)',
              padding: 'var(--space-4) var(--space-5)',
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'space-between',
              flex: 1,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span
                style={{
                  fontSize: 'var(--type-micro-size)',
                  fontFamily: 'var(--font-mono)',
                  textTransform: 'uppercase',
                  letterSpacing: '0.06em',
                  color: 'var(--color-text-muted)',
                  fontWeight: 600,
                }}
              >
                TOTAL FLEET SPEND
              </span>
              <TrendingUp size={16} color="var(--color-text-secondary)" />
            </div>

            <div style={{ display: 'flex', alignItems: 'baseline', gap: 'var(--space-3)', marginTop: '2px' }}>
              <div
                className="tabular-nums"
                style={{
                  fontSize: '24px',
                  fontWeight: 700,
                  fontFamily: 'var(--font-mono)',
                  color: 'var(--color-text-primary)',
                }}
              >
                ${totalSpend.toFixed(4)}
              </div>
              <div style={{ fontSize: 'var(--type-micro-size)', color: 'var(--color-text-secondary)' }}>
                {agents.length} monitored agent services
              </div>
            </div>

            {/* Mini vertical histogram */}
            <div style={{ display: 'flex', alignItems: 'flex-end', gap: '3px', height: '18px', marginTop: '6px' }}>
              {[12, 18, 15, 25, 30, 28, 38, 42, 35, 48, 52, 60, 58, 65, 72].map((val, idx) => (
                <div
                  key={idx}
                  style={{
                    flex: 1,
                    height: `${val}%`,
                    backgroundColor: idx > 11 ? 'var(--color-accent)' : 'rgba(255, 255, 255, 0.15)',
                    borderRadius: '1px',
                  }}
                />
              ))}
            </div>
          </div>

          {/* Fleet Burn Rate Card */}
          <div
            style={{
              backgroundColor: 'var(--color-surface)',
              border: '1px solid var(--color-border)',
              borderRadius: 'var(--radius-md)',
              padding: 'var(--space-4) var(--space-5)',
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'space-between',
              flex: 1,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span
                style={{
                  fontSize: 'var(--type-micro-size)',
                  fontFamily: 'var(--font-mono)',
                  textTransform: 'uppercase',
                  letterSpacing: '0.06em',
                  color: 'var(--color-text-muted)',
                  fontWeight: 600,
                }}
              >
                FLEET BURN RATE
              </span>
              <Activity
                size={16}
                color={totalBurnRate > 0.05 ? 'var(--color-state-suspicious)' : 'var(--color-text-secondary)'}
              />
            </div>

            <div style={{ display: 'flex', alignItems: 'baseline', gap: 'var(--space-3)', marginTop: '2px' }}>
              <div
                className="tabular-nums"
                style={{
                  fontSize: '24px',
                  fontWeight: 700,
                  fontFamily: 'var(--font-mono)',
                  color:
                    totalBurnRate > 0.05
                      ? 'var(--color-state-suspicious)'
                      : 'var(--color-text-primary)',
                }}
              >
                ${totalBurnRate.toFixed(4)}/min
              </div>
              <div style={{ fontSize: 'var(--type-micro-size)', color: 'var(--color-text-secondary)' }}>
                Active run-time cost projection
              </div>
            </div>

            {/* Velocity pulse indicator */}
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                fontSize: '11px',
                fontFamily: 'var(--font-mono)',
                color: 'var(--color-text-muted)',
                marginTop: '4px',
              }}
            >
              <span
                style={{
                  display: 'inline-block',
                  width: '6px',
                  height: '6px',
                  borderRadius: '50%',
                  backgroundColor: totalBurnRate > 0.05 ? 'var(--color-state-suspicious)' : 'var(--color-state-healthy)',
                  boxShadow: `0 0 6px ${totalBurnRate > 0.05 ? 'var(--color-state-suspicious)' : 'var(--color-state-healthy)'}`,
                }}
              />
              <span>Velocity: {totalBurnRate > 0.05 ? 'HIGH SPEND SPIKE' : 'NOMINAL PACING'}</span>
            </div>
          </div>
        </div>

        {/* Right Status & Gate Stack (col-span-3): INTERVENTIONS + AGENTS BY STATE */}
        <div
          style={{
            gridColumn: 'span 3',
            display: 'flex',
            flexDirection: 'column',
            gap: 'var(--space-4)',
          }}
        >
          {/* Interventions Card */}
          <div
            style={{
              backgroundColor: 'var(--color-surface)',
              border: '1px solid var(--color-border)',
              borderRadius: 'var(--radius-md)',
              padding: 'var(--space-4) var(--space-5)',
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'space-between',
              flex: 1,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span
                style={{
                  fontSize: 'var(--type-micro-size)',
                  fontFamily: 'var(--font-mono)',
                  textTransform: 'uppercase',
                  letterSpacing: '0.06em',
                  color: 'var(--color-text-muted)',
                  fontWeight: 600,
                }}
              >
                INTERVENTIONS
              </span>
              <ShieldAlert size={16} color="var(--color-telemetry-cyan)" />
            </div>

            <div style={{ display: 'flex', alignItems: 'baseline', gap: 'var(--space-2)', marginTop: '2px' }}>
              <div
                className="tabular-nums"
                style={{
                  fontSize: '26px',
                  fontWeight: 700,
                  fontFamily: 'var(--font-mono)',
                  color: 'var(--color-telemetry-cyan)',
                }}
              >
                {interventions}
              </div>
              <span
                style={{
                  fontSize: '11px',
                  fontFamily: 'var(--font-mono)',
                  backgroundColor: 'rgba(6, 182, 212, 0.14)',
                  color: 'var(--color-telemetry-cyan)',
                  padding: '1px 6px',
                  borderRadius: 'var(--radius-sm)',
                }}
              >
                CIRCUIT TRIPPED
              </span>
            </div>

            <div style={{ fontSize: 'var(--type-micro-size)', color: 'var(--color-text-secondary)', marginTop: '4px' }}>
              {roiData?.tool_calls_held || 0} tool calls held at gate
            </div>
          </div>

          {/* Agents by State Card with Multi-Color Distribution Bar */}
          <div
            style={{
              backgroundColor: 'var(--color-surface)',
              border: '1px solid var(--color-border)',
              borderRadius: 'var(--radius-md)',
              padding: 'var(--space-4) var(--space-5)',
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'space-between',
              flex: 1,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span
                style={{
                  fontSize: 'var(--type-micro-size)',
                  fontFamily: 'var(--font-mono)',
                  textTransform: 'uppercase',
                  letterSpacing: '0.06em',
                  color: 'var(--color-text-muted)',
                  fontWeight: 600,
                }}
              >
                AGENTS BY STATE
              </span>
              <Cpu size={16} color="var(--color-text-secondary)" />
            </div>

            <div style={{ display: 'flex', alignItems: 'baseline', gap: 'var(--space-3)', marginTop: '2px' }}>
              <div
                className="tabular-nums"
                style={{
                  fontSize: '24px',
                  fontWeight: 700,
                  fontFamily: 'var(--font-mono)',
                  color: 'var(--color-text-primary)',
                }}
              >
                {agents.length} Total
              </div>
            </div>

            {/* Segmented multi-color horizontal distribution bar */}
            <div style={{ marginTop: '4px' }}>
              <div
                style={{
                  height: '6px',
                  width: '100%',
                  display: 'flex',
                  borderRadius: '3px',
                  overflow: 'hidden',
                  backgroundColor: 'var(--color-surface-elevated)',
                  marginBottom: '6px',
                }}
              >
                <div
                  style={{
                    width: `${((stateCounts.healthy || 0) / (agents.length || 1)) * 100}%`,
                    backgroundColor: 'var(--color-state-healthy)',
                  }}
                />
                <div
                  style={{
                    width: `${((stateCounts.suspicious || 0) / (agents.length || 1)) * 100}%`,
                    backgroundColor: 'var(--color-state-suspicious)',
                  }}
                />
                <div
                  style={{
                    width: `${((stateCounts.paused || 0) / (agents.length || 1)) * 100}%`,
                    backgroundColor: 'var(--color-state-paused)',
                  }}
                />
                <div
                  style={{
                    width: `${((stateCounts.killed || 0) / (agents.length || 1)) * 100}%`,
                    backgroundColor: 'var(--color-state-killed)',
                  }}
                />
              </div>

              <div
                style={{
                  fontSize: '11px',
                  fontFamily: 'var(--font-mono)',
                  color: 'var(--color-text-secondary)',
                  display: 'flex',
                  justifyContent: 'space-between',
                }}
              >
                <span style={{ color: 'var(--color-state-healthy)' }}>
                  {stateCounts.healthy || 0} healthy
                </span>
                <span style={{ color: 'var(--color-state-paused)' }}>
                  {stateCounts.paused || 0} paused
                </span>
                <span style={{ color: 'var(--color-state-killed)' }}>
                  {stateCounts.killed || 0} killed
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Asymmetric Fleet Matrix (col-span-8) + Vertical Comparison Rail (col-span-4) */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(12, minmax(0, 1fr))',
          gap: 'var(--space-4)',
          width: '100%',
        }}
      >
        {/* Left (col-span-8): Staggered 2x2 Fleet Node Bento Grid */}
        <div style={{ gridColumn: 'span 8', display: 'flex', flexDirection: 'column' }}>
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
                <div style={{ display: 'flex', gap: 'var(--space-1)' }}>
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
                          backgroundColor: isSelected
                            ? 'var(--color-surface-elevated)'
                            : 'transparent',
                          color: isSelected
                            ? 'var(--color-text-primary)'
                            : 'var(--color-text-muted)',
                          border: isSelected
                            ? '1px solid var(--color-border-accent)'
                            : '1px solid transparent',
                          cursor: 'pointer',
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

        {/* Right (col-span-4): Live Circuit-Breaker & Comparative Rail */}
        <div
          style={{
            gridColumn: 'span 4',
            display: 'flex',
            flexDirection: 'column',
            gap: 'var(--space-4)',
          }}
        >
          {/* Top Half: Side-by-Side Vertical Telemetry Comparison Bar Chart */}
          <div
            style={{
              backgroundColor: 'var(--color-surface)',
              border: '1px solid var(--color-border)',
              borderRadius: 'var(--radius-md)',
              padding: 'var(--space-4) var(--space-5)',
              display: 'flex',
              flexDirection: 'column',
            }}
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                marginBottom: 'var(--space-3)',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
                <BarChart2 size={16} color="var(--color-accent)" />
                <span
                  style={{
                    fontSize: 'var(--type-micro-size)',
                    fontFamily: 'var(--font-mono)',
                    fontWeight: 700,
                    textTransform: 'uppercase',
                    color: 'var(--color-text-primary)',
                  }}
                >
                  Node Burn & Loop Comparison
                </span>
              </div>
              <span
                style={{
                  fontSize: '10px',
                  fontFamily: 'var(--font-mono)',
                  color: 'var(--color-text-muted)',
                }}
              >
                LIVE PEAK RATIOS
              </span>
            </div>

            {/* 4 Agent Vertical Telemetry Bars */}
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(4, 1fr)',
                gap: 'var(--space-2)',
                alignItems: 'flex-end',
                height: '110px',
                paddingTop: 'var(--space-2)',
                borderBottom: '1px solid var(--color-border)',
                paddingBottom: 'var(--space-2)',
              }}
            >
              {agents.slice(0, 4).map((ag) => {
                const maxTokens = Math.max(1, ...agents.map((a) => a.tokens_per_min));
                const barHeightPct = Math.max(12, Math.min(100, (ag.tokens_per_min / maxTokens) * 100));
                const barColor =
                  ag.state === 'killed' || ag.state === 'paused'
                    ? 'var(--color-state-killed)'
                    : ag.loop_score > 0.4
                    ? 'var(--color-state-suspicious)'
                    : 'var(--color-state-healthy)';

                return (
                  <div
                    key={ag.agent_id}
                    style={{
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: 'center',
                      gap: '4px',
                      height: '100%',
                      justifyContent: 'flex-end',
                    }}
                  >
                    <span
                      style={{
                        fontSize: '9px',
                        fontFamily: 'var(--font-mono)',
                        color: barColor,
                        fontWeight: 700,
                      }}
                    >
                      {ag.tokens_per_min >= 1000
                        ? `${(ag.tokens_per_min / 1000).toFixed(0)}k`
                        : ag.tokens_per_min}
                    </span>
                    <div
                      style={{
                        width: '100%',
                        height: `${barHeightPct}%`,
                        backgroundColor: barColor,
                        borderRadius: '3px 3px 0 0',
                        opacity: 0.85,
                        boxShadow: `0 0 10px ${barColor}`,
                      }}
                    />
                    <span
                      style={{
                        fontSize: '11px',
                        fontFamily: 'var(--font-mono)',
                        color: 'var(--color-text-primary)',
                        fontWeight: 600,
                        textTransform: 'uppercase',
                      }}
                    >
                      {ag.agent_id.toUpperCase()}
                    </span>
                  </div>
                );
              })}
            </div>

            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                fontSize: '10px',
                fontFamily: 'var(--font-mono)',
                color: 'var(--color-text-muted)',
                marginTop: 'var(--space-2)',
              }}
            >
              <span>Green: Nominal flow</span>
              <span style={{ color: 'var(--color-state-killed)' }}>Red: Paused/Runaway</span>
            </div>
          </div>

          {/* Bottom Half: Autonomous Gate & Quarantine Log */}
          <div
            style={{
              backgroundColor: 'var(--color-surface)',
              border: '1px solid var(--color-border)',
              borderRadius: 'var(--radius-md)',
              padding: 'var(--space-4) var(--space-5)',
              display: 'flex',
              flexDirection: 'column',
              flex: 1,
            }}
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 'var(--space-2)',
                marginBottom: 'var(--space-3)',
              }}
            >
              <Terminal size={15} color="var(--color-telemetry-cyan)" />
              <span
                style={{
                  fontSize: 'var(--type-micro-size)',
                  fontFamily: 'var(--font-mono)',
                  fontWeight: 700,
                  textTransform: 'uppercase',
                  color: 'var(--color-text-primary)',
                }}
              >
                Quarantine & Decision Feed
              </span>
            </div>

            <div
              style={{
                display: 'flex',
                flexDirection: 'column',
                gap: 'var(--space-2)',
                fontSize: '11px',
                fontFamily: 'var(--font-mono)',
              }}
            >
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
                      padding: 'var(--space-2)',
                      backgroundColor: 'var(--color-canvas)',
                      border: '1px solid var(--color-border)',
                      borderRadius: 'var(--radius-sm)',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '2px',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style={{ fontWeight: 700, color: 'var(--color-text-primary)' }}>
                        Node: {ag.agent_id.toUpperCase()}
                      </span>
                      <span
                        style={{
                          fontSize: '9px',
                          padding: '1px 5px',
                          borderRadius: '2px',
                          fontWeight: 700,
                          backgroundColor: `${badgeColor}22`,
                          color: badgeColor,
                          border: `1px solid ${badgeColor}55`,
                        }}
                      >
                        {badgeText}
                      </span>
                    </div>
                    <div
                      style={{
                        color: 'var(--color-text-muted)',
                        fontSize: '10px',
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
    </div>
  );
};
