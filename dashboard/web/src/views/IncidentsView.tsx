import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, ShieldCheck } from 'lucide-react';
import { api } from '../api/client';
import { Panel } from '../components/Panel';

export const IncidentsView: React.FC = () => {
  const { data: alertsData, isLoading: loadingAlerts, error: errorAlerts, refetch: refetchAlerts } = useQuery({
    queryKey: ['alerts'],
    queryFn: () => api.getAlerts(20),
    refetchInterval: 1000,
  });

  const { data: actionsData, isLoading: loadingActions, error: errorActions, refetch: refetchActions } = useQuery({
    queryKey: ['actions'],
    queryFn: () => api.getActions(20),
    refetchInterval: 1000,
  });

  const alerts = alertsData?.items || [];
  const actions = actionsData?.items || [];

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

      {/* Incident Alerts Panel */}
      <Panel
        title="Detected Incident Alerts"
        icon={<AlertTriangle size={18} />}
        loading={loadingAlerts}
        error={errorAlerts}
        empty={alerts.length === 0}
        emptyTitle="Zero Active Incidents"
        emptyMessage="No anomaly flags or semantic loop alerts have tripped the circuit breaker."
        onRetry={() => refetchAlerts()}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
          {alerts.map((alert) => (
            <div
              key={alert.id}
              style={{
                backgroundColor: 'var(--color-surface-elevated)',
                border: '1px solid var(--color-border)',
                borderRadius: 'var(--radius-sm)',
                padding: 'var(--space-3) var(--space-4)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}
            >
              <div>
                <span style={{ fontWeight: 700, fontFamily: 'var(--font-mono)' }}>{alert.agent_id}</span>
                <span style={{ color: 'var(--color-text-muted)', margin: '0 var(--space-2)' }}>—</span>
                <span style={{ color: 'var(--color-text-primary)' }}>{alert.message}</span>
              </div>
              <span
                style={{
                  fontSize: 'var(--type-micro-size)',
                  padding: '2px 8px',
                  borderRadius: 'var(--radius-sm)',
                  backgroundColor: 'var(--color-state-suspicious-bg)',
                  color: 'var(--color-state-suspicious)',
                  fontWeight: 600,
                  textTransform: 'uppercase',
                }}
              >
                {alert.severity}
              </span>
            </div>
          ))}
        </div>
      </Panel>

      {/* Execution Actions Log */}
      <Panel
        title="Automated Interventions Log"
        icon={<ShieldCheck size={18} />}
        loading={loadingActions}
        error={errorActions}
        empty={actions.length === 0}
        emptyTitle="No Actions Logged"
        emptyMessage="Circuit breaker has not intervened on any running agent containers."
        onRetry={() => refetchActions()}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
          {actions.map((act) => (
            <div
              key={act.id}
              style={{
                backgroundColor: 'var(--color-surface-elevated)',
                border: '1px solid var(--color-border)',
                borderRadius: 'var(--radius-sm)',
                padding: 'var(--space-3) var(--space-4)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}
            >
              <div>
                <span
                  style={{
                    fontFamily: 'var(--font-mono)',
                    fontWeight: 700,
                    color: act.action === 'KILL' ? 'var(--color-state-killed)' : 'var(--color-state-paused)',
                    marginRight: 'var(--space-2)',
                  }}
                >
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
