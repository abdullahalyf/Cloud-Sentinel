import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { DollarSign, TrendingUp } from 'lucide-react';
import { api } from '../api/client';
import { Panel } from '../components/Panel';

export const CostView: React.FC = () => {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['roi'],
    queryFn: api.getRoi,
    refetchInterval: 1000,
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-6)', width: '100%' }}>
      <header>
        <h1 style={{ fontSize: 'var(--type-title-sm-size)', fontWeight: 700, color: 'var(--color-text-primary)' }}>
          Cost Burn-Down & ROI Attribution
        </h1>
        <p style={{ fontSize: 'var(--type-body-sm-size)', color: 'var(--color-text-secondary)', marginTop: 'var(--space-1)' }}>
          Real-time financial return on investment, task-attributed spend, and wasted tokens analysis.
        </p>
      </header>

      {/* ROI Hero Cards Panel */}
      <Panel
        title="Economic Return Summary"
        icon={<DollarSign size={18} />}
        loading={isLoading}
        error={error}
        onRetry={() => refetch()}
      >
        {data && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 'var(--space-4)' }}>
            <div style={{ backgroundColor: 'var(--color-surface-elevated)', padding: 'var(--space-4)', borderRadius: 'var(--radius-sm)' }}>
              <div style={{ fontSize: 'var(--type-micro-size)', color: 'var(--color-text-muted)' }}>TOTAL VALUE SAVED</div>
              <div className="tabular-nums" style={{ fontSize: 'var(--type-title-md-size)', fontWeight: 700, color: 'var(--color-state-healthy)', marginTop: 'var(--space-1)' }}>
                ${data.saved_usd.toFixed(4)}
              </div>
              <div style={{ fontSize: 'var(--type-micro-size)', color: 'var(--color-text-secondary)', marginTop: 'var(--space-1)' }}>
                Across {data.interventions} circuit interventions
              </div>
            </div>

            <div style={{ backgroundColor: 'var(--color-surface-elevated)', padding: 'var(--space-4)', borderRadius: 'var(--radius-sm)' }}>
              <div style={{ fontSize: 'var(--type-micro-size)', color: 'var(--color-text-muted)' }}>TOTAL FLEET SPEND</div>
              <div className="tabular-nums" style={{ fontSize: 'var(--type-title-md-size)', fontWeight: 700, color: 'var(--color-text-primary)', marginTop: 'var(--space-1)' }}>
                ${data.total_spend_usd.toFixed(4)}
              </div>
              <div style={{ fontSize: 'var(--type-micro-size)', color: 'var(--color-text-secondary)', marginTop: 'var(--space-1)' }}>
                Cumulative token expenditure
              </div>
            </div>

            <div style={{ backgroundColor: 'var(--color-surface-elevated)', padding: 'var(--space-4)', borderRadius: 'var(--radius-sm)' }}>
              <div style={{ fontSize: 'var(--type-micro-size)', color: 'var(--color-text-muted)' }}>COST PER SUCCESS</div>
              <div className="tabular-nums" style={{ fontSize: 'var(--type-title-md-size)', fontWeight: 700, color: 'var(--color-telemetry-cyan)', marginTop: 'var(--space-1)' }}>
                ${data.cost_per_successful_task_usd.toFixed(4)}
              </div>
              <div style={{ fontSize: 'var(--type-micro-size)', color: 'var(--color-text-secondary)', marginTop: 'var(--space-1)' }}>
                {data.tasks_succeeded} / {data.tasks_total} tasks resolved
              </div>
            </div>

            <div style={{ backgroundColor: 'var(--color-surface-elevated)', padding: 'var(--space-4)', borderRadius: 'var(--radius-sm)' }}>
              <div style={{ fontSize: 'var(--type-micro-size)', color: 'var(--color-text-muted)' }}>WASTED SPEND</div>
              <div className="tabular-nums" style={{ fontSize: 'var(--type-title-md-size)', fontWeight: 700, color: 'var(--color-state-killed)', marginTop: 'var(--space-1)' }}>
                ${data.wasted_usd.toFixed(4)}
              </div>
              <div style={{ fontSize: 'var(--type-micro-size)', color: 'var(--color-text-secondary)', marginTop: 'var(--space-1)' }}>
                Failed or abandoned loops
              </div>
            </div>
          </div>
        )}
      </Panel>

      {/* ROI Horizon Formula Note */}
      {data?.formula && (
        <Panel title="Attribution Methodology" icon={<TrendingUp size={18} />}>
          <p style={{ fontSize: 'var(--type-body-sm-size)', color: 'var(--color-text-secondary)', lineHeight: 1.6 }}>
            {data.formula}
          </p>
        </Panel>
      )}
    </div>
  );
};
