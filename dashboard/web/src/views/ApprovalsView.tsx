import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { ShieldAlert, Check, X, Edit2 } from 'lucide-react';
import { api } from '../api/client';
import { Panel } from '../components/Panel';

export const ApprovalsView: React.FC = () => {
  const { data: calls, isLoading: loadingCalls, error: errorCalls, refetch: refetchCalls } = useQuery({
    queryKey: ['tool-calls', 'pending'],
    queryFn: () => api.getToolCalls('pending'),
    refetchInterval: 1000,
  });

  const { data: heals, isLoading: loadingHeals, error: errorHeals, refetch: refetchHeals } = useQuery({
    queryKey: ['heal-proposals', 'pending'],
    queryFn: () => api.getHealProposals('pending'),
    refetchInterval: 1000,
  });

  const pendingCalls = calls?.items || [];
  const pendingHeals = heals?.items || [];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-6)', width: '100%' }}>
      <header>
        <h1 style={{ fontSize: 'var(--type-title-sm-size)', fontWeight: 700, color: 'var(--color-text-primary)' }}>
          Human-in-the-Loop Approvals Inbox
        </h1>
        <p style={{ fontSize: 'var(--type-body-sm-size)', color: 'var(--color-text-secondary)', marginTop: 'var(--space-1)' }}>
          Review, approve, deny, or rewrite high-risk tool calls and memory patches.
        </p>
      </header>

      {/* Pending Tool Calls Panel */}
      <Panel
        title={`Pending Tool Overrides (${pendingCalls.length})`}
        icon={<ShieldAlert size={18} />}
        loading={loadingCalls}
        error={errorCalls}
        empty={pendingCalls.length === 0}
        emptyTitle="Nothing Waiting for a Human"
        emptyMessage="No tool calls currently held by policy gates. Calls exceeding monetary limits will appear here."
        onRetry={() => refetchCalls()}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
          {pendingCalls.map((call) => (
            <div
              key={call.id}
              style={{
                backgroundColor: 'var(--color-surface-elevated)',
                border: '1px solid var(--color-border)',
                borderRadius: 'var(--radius-sm)',
                padding: 'var(--space-4)',
                display: 'flex',
                flexDirection: 'column',
                gap: 'var(--space-3)',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
                  <span style={{ fontWeight: 700, fontFamily: 'var(--font-mono)' }}>{call.agent_id}</span>
                  <span style={{ color: 'var(--color-text-muted)' }}>called</span>
                  <span style={{ color: 'var(--color-accent)', fontWeight: 600 }}>{call.tool_name}</span>
                </div>
                {call.value_usd > 0 && (
                  <span
                    className="tabular-nums"
                    style={{
                      backgroundColor: 'var(--color-state-suspicious-bg)',
                      color: 'var(--color-state-suspicious)',
                      padding: '2px 8px',
                      borderRadius: 'var(--radius-sm)',
                      fontWeight: 700,
                      fontSize: 'var(--type-micro-size)',
                    }}
                  >
                    ${call.value_usd.toFixed(2)} at stake
                  </span>
                )}
              </div>

              <pre
                style={{
                  backgroundColor: 'var(--color-canvas)',
                  padding: 'var(--space-3)',
                  borderRadius: 'var(--radius-sm)',
                  fontSize: 'var(--type-micro-size)',
                  fontFamily: 'var(--font-mono)',
                  overflowX: 'auto',
                }}
              >
                {JSON.stringify(call.args, null, 2)}
              </pre>

              <div style={{ display: 'flex', gap: 'var(--space-2)', justifyContent: 'flex-end' }}>
                <button
                  type="button"
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 'var(--space-1)',
                    padding: 'var(--space-2) var(--space-3)',
                    backgroundColor: 'var(--color-state-healthy-bg)',
                    border: '1px solid var(--color-state-healthy-border)',
                    color: 'var(--color-state-healthy)',
                    borderRadius: 'var(--radius-sm)',
                    fontWeight: 600,
                    fontSize: 'var(--type-micro-size)',
                  }}
                >
                  <Check size={14} /> Approve (A)
                </button>
                <button
                  type="button"
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 'var(--space-1)',
                    padding: 'var(--space-2) var(--space-3)',
                    backgroundColor: 'var(--color-state-killed-bg)',
                    border: '1px solid var(--color-state-killed-border)',
                    color: 'var(--color-state-killed)',
                    borderRadius: 'var(--radius-sm)',
                    fontWeight: 600,
                    fontSize: 'var(--type-micro-size)',
                  }}
                >
                  <X size={14} /> Deny (D)
                </button>
                <button
                  type="button"
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 'var(--space-1)',
                    padding: 'var(--space-2) var(--space-3)',
                    backgroundColor: 'var(--color-surface)',
                    border: '1px solid var(--color-border)',
                    color: 'var(--color-text-primary)',
                    borderRadius: 'var(--radius-sm)',
                    fontWeight: 600,
                    fontSize: 'var(--type-micro-size)',
                  }}
                >
                  <Edit2 size={14} /> Rewrite (R)
                </button>
              </div>
            </div>
          ))}
        </div>
      </Panel>

      {/* Pending Heal Proposals Panel */}
      <Panel
        title={`Pending Heal Proposals (${pendingHeals.length})`}
        icon={<ShieldAlert size={18} />}
        loading={loadingHeals}
        error={errorHeals}
        empty={pendingHeals.length === 0}
        emptyTitle="No Heal Proposals"
        emptyMessage="Judge proposals for malfunctioning agent memory will appear here."
        onRetry={() => refetchHeals()}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
          {pendingHeals.map((heal) => (
            <div
              key={heal.id}
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
                <span style={{ fontWeight: 700, fontFamily: 'var(--font-mono)' }}>heal · {heal.agent_id}</span>
                <span
                  style={{
                    backgroundColor: 'var(--color-state-probation-bg)',
                    color: 'var(--color-state-probation)',
                    padding: '2px 8px',
                    borderRadius: 'var(--radius-sm)',
                    fontWeight: 700,
                    fontSize: 'var(--type-micro-size)',
                  }}
                >
                  {Math.round(heal.confidence * 100)}% Confidence
                </span>
              </div>
              <p style={{ fontSize: 'var(--type-body-sm-size)', color: 'var(--color-text-secondary)' }}>
                {heal.reason}
              </p>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
};
