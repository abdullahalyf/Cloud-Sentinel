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
  Server,
  Filter,
} from 'lucide-react';
import { api } from '../api/client';
import type { AgentState, AgentView } from '../api/types';
import { Panel } from '../components/Panel';
import { StatTile } from '../components/StatTile';
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
  const totalSpend = roiData?.total_spend_usd ?? agents.reduce((sum, a) => sum + (a.spend_usd || 0), 0);
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
                textTransform: 'uppercase',
                fontWeight: 600,
              }}
            >
              <span
                style={{
                  width: '6px',
                  height: '6px',
                  borderRadius: '50%',
                  backgroundColor: 'var(--color-state-healthy)',
                }}
              />
              Live Polling (1 Hz)
            </span>
          </div>
          <p
            style={{
              fontSize: 'var(--type-body-sm-size)',
              color: 'var(--color-text-secondary)',
              marginTop: 'var(--space-1)',
            }}
          >
            Autonomous circuit breaker monitoring, real-time token burn attribution, and incident quarantine.
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
            <Server size={14} color="var(--color-telemetry-cyan)" />
            <span>API:</span>
            <span style={{ color: 'var(--color-text-primary)', fontWeight: 600 }}>:8000</span>
            <span>· Updated:</span>
            <span className="tabular-nums" style={{ color: 'var(--color-text-primary)' }}>
              {lastUpdated}
            </span>
          </div>

          <button
            type="button"
            onClick={handleRefreshAll}
            aria-label="Refresh fleet data"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 'var(--space-2)',
              padding: 'var(--space-2) var(--space-3)',
              backgroundColor: 'var(--color-surface-elevated)',
              border: '1px solid var(--color-border)',
              borderRadius: 'var(--radius-sm)',
              color: 'var(--color-text-primary)',
              fontSize: 'var(--type-micro-size)',
              fontWeight: 600,
              cursor: 'pointer',
              transition: 'background-color var(--transition-fast)',
            }}
            onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'var(--color-surface)')}
            onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'var(--color-surface-elevated)')}
          >
            <RefreshCw size={13} />
            Refresh
          </button>
        </div>
      </div>

      {/* Top Bento KPI Strip */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
          gap: 'var(--space-4)',
        }}
      >
        <StatTile
          label="Total $ Saved"
          value={`$${totalSaved.toFixed(4)}`}
          subtext={`Saved via ${interventions} automated stops`}
          icon={<DollarSign size={18} />}
          color="var(--color-state-healthy)"
        />

        <StatTile
          label="Total Fleet Spend"
          value={`$${totalSpend.toFixed(4)}`}
          subtext={`${agents.length} monitored agent services`}
          icon={<TrendingUp size={18} />}
        />

        <StatTile
          label="Fleet Burn Rate"
          value={`$${totalBurnRate.toFixed(4)}/min`}
          subtext="Active run-time cost projection"
          icon={<Activity size={18} />}
          color={totalBurnRate > 0.05 ? 'var(--color-state-suspicious)' : 'var(--color-text-primary)'}
        />

        <StatTile
          label="Interventions"
          value={interventions}
          subtext={`${roiData?.tool_calls_held || 0} tool calls held at gate`}
          icon={<ShieldAlert size={18} />}
          color="var(--color-telemetry-cyan)"
        />

        <StatTile
          label="Agents by State"
          value={`${agents.length} Total`}
          subtext={`${stateCounts.healthy || 0} healthy · ${stateCounts.paused || 0} paused · ${stateCounts.killed || 0} killed`}
          icon={<Cpu size={18} />}
        />
      </div>

      {/* Fleet Node Grid & Filter Bar */}
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
                      backgroundColor: isSelected ? 'var(--color-surface-elevated)' : 'transparent',
                      color: isSelected ? 'var(--color-text-primary)' : 'var(--color-text-muted)',
                      border: isSelected ? '1px solid var(--color-border-accent)' : '1px solid transparent',
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
            gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
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
  );
};
