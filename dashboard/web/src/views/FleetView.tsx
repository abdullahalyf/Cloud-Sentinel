import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { LayoutDashboard, RefreshCw } from 'lucide-react';
import { api } from '../api/client';
import { Panel } from '../components/Panel';

export const FleetView: React.FC = () => {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['fleet'],
    queryFn: api.getFleet,
    refetchInterval: 1000,
  });

  const agents = data?.agents || [];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-6)', width: '100%' }}>
      {/* Fleet Hero Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <h1 style={{ fontSize: 'var(--type-title-sm-size)', fontWeight: 700, color: 'var(--color-text-primary)' }}>
            Fleet Telemetry Control
          </h1>
          <p style={{ fontSize: 'var(--type-body-sm-size)', color: 'var(--color-text-secondary)', marginTop: 'var(--space-1)' }}>
            Real-time circuit-breaker monitoring, token burn rates, and automated quaranteens.
          </p>
        </div>
        <button
          type="button"
          onClick={() => refetch()}
          aria-label="Refresh Fleet Data"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 'var(--space-2)',
            padding: 'var(--space-2) var(--space-3)',
            backgroundColor: 'var(--color-surface)',
            border: '1px solid var(--color-border)',
            borderRadius: 'var(--radius-sm)',
            color: 'var(--color-text-secondary)',
            fontSize: 'var(--type-micro-size)',
            fontWeight: 600,
          }}
        >
          <RefreshCw size={14} />
          Refresh
        </button>
      </div>

      {/* Main Fleet Overview Panel */}
      <Panel
        title="Active Agent Fleet"
        icon={<LayoutDashboard size={18} />}
        loading={isLoading}
        error={error}
        empty={agents.length === 0}
        emptyTitle="No Agents Running"
        emptyMessage="No agents yet: start one with python -m brain --fake"
        onRetry={() => refetch()}
      >
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 'var(--space-4)' }}>
          {agents.map((agent) => (
            <div
              key={agent.agent_id}
              style={{
                backgroundColor: 'var(--color-surface-elevated)',
                border: '1px solid var(--color-border)',
                borderRadius: 'var(--radius-sm)',
                padding: 'var(--space-4)',
                display: 'flex',
                flexDirection: 'column',
                gap: 'var(--space-2)',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span style={{ fontWeight: 700, fontFamily: 'var(--font-mono)' }}>{agent.agent_id}</span>
                <span
                  style={{
                    fontSize: 'var(--type-micro-size)',
                    textTransform: 'uppercase',
                    padding: '2px 8px',
                    borderRadius: 'var(--radius-sm)',
                    fontWeight: 700,
                    backgroundColor:
                      agent.state === 'healthy'
                        ? 'var(--color-state-healthy-bg)'
                        : agent.state === 'paused'
                        ? 'var(--color-state-paused-bg)'
                        : agent.state === 'killed'
                        ? 'var(--color-state-killed-bg)'
                        : 'var(--color-state-suspicious-bg)',
                    color:
                      agent.state === 'healthy'
                        ? 'var(--color-state-healthy)'
                        : agent.state === 'paused'
                        ? 'var(--color-state-paused)'
                        : agent.state === 'killed'
                        ? 'var(--color-state-killed)'
                        : 'var(--color-state-suspicious)',
                  }}
                >
                  {agent.state}
                </span>
              </div>
              <div style={{ fontSize: 'var(--type-micro-size)', color: 'var(--color-text-secondary)', display: 'flex', justifyContent: 'space-between' }}>
                <span>Burn Rate:</span>
                <span className="tabular-nums" style={{ fontWeight: 600, color: 'var(--color-text-primary)' }}>
                  ${agent.usd_per_min.toFixed(4)}/min
                </span>
              </div>
              <div style={{ fontSize: 'var(--type-micro-size)', color: 'var(--color-text-secondary)', display: 'flex', justifyContent: 'space-between' }}>
                <span>Tokens/min:</span>
                <span className="tabular-nums" style={{ fontWeight: 600, color: 'var(--color-text-primary)' }}>
                  {agent.tokens_per_min.toLocaleString()}
                </span>
              </div>
              <div style={{ fontSize: 'var(--type-micro-size)', color: 'var(--color-text-secondary)', display: 'flex', justifyContent: 'space-between' }}>
                <span>Loop Score:</span>
                <span
                  className="tabular-nums"
                  style={{
                    fontWeight: 600,
                    color: agent.loop_score > 0.5 ? 'var(--color-state-suspicious)' : 'var(--color-text-primary)',
                  }}
                >
                  {agent.loop_score.toFixed(2)}
                </span>
              </div>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
};
