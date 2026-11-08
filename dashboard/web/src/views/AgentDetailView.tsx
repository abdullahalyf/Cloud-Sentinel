import React from 'react';
import { useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Cpu, Database, Activity } from 'lucide-react';
import { api } from '../api/client';
import { Panel } from '../components/Panel';

export const AgentDetailView: React.FC = () => {
  const { id = 'beta' } = useParams<{ id: string }>();

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['agent', id],
    queryFn: () => api.getAgent(id),
    refetchInterval: 1000,
  });

  const { data: nodes } = useQuery({
    queryKey: ['agent-nodes', id],
    queryFn: () => api.getAgentNodes(id),
    refetchInterval: 1000,
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-6)', width: '100%' }}>
      <header>
        <h1 style={{ fontSize: 'var(--type-title-sm-size)', fontWeight: 700, color: 'var(--color-text-primary)' }}>
          Agent Command & Telemetry: <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--color-accent)' }}>{id}</span>
        </h1>
        <p style={{ fontSize: 'var(--type-body-sm-size)', color: 'var(--color-text-secondary)', marginTop: 'var(--space-1)' }}>
          State transitions, live LangGraph flow, memory editor, and manual operator overrides.
        </p>
      </header>

      {/* Agent Summary Panel */}
      <Panel
        title={`Status Overview: ${id}`}
        icon={<Cpu size={18} />}
        loading={isLoading}
        error={error}
        onRetry={() => refetch()}
      >
        {data && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 'var(--space-4)' }}>
            <div>
              <div style={{ fontSize: 'var(--type-micro-size)', color: 'var(--color-text-muted)' }}>CURRENT STATE</div>
              <div style={{ fontSize: 'var(--type-title-sm-size)', fontWeight: 700, marginTop: 'var(--space-1)' }}>
                {data.agent.state.toUpperCase()}
              </div>
            </div>
            <div>
              <div style={{ fontSize: 'var(--type-micro-size)', color: 'var(--color-text-muted)' }}>BURN RATE</div>
              <div className="tabular-nums" style={{ fontSize: 'var(--type-title-sm-size)', fontWeight: 700, marginTop: 'var(--space-1)' }}>
                ${data.agent.usd_per_min.toFixed(4)}/min
              </div>
            </div>
            <div>
              <div style={{ fontSize: 'var(--type-micro-size)', color: 'var(--color-text-muted)' }}>SPEND / BUDGET</div>
              <div className="tabular-nums" style={{ fontSize: 'var(--type-title-sm-size)', fontWeight: 700, marginTop: 'var(--space-1)' }}>
                ${data.agent.spend_usd.toFixed(2)} / ${data.agent.budget_usd.toFixed(2)}
              </div>
            </div>
            <div>
              <div style={{ fontSize: 'var(--type-micro-size)', color: 'var(--color-text-muted)' }}>LOOP SCORE</div>
              <div className="tabular-nums" style={{ fontSize: 'var(--type-title-sm-size)', fontWeight: 700, marginTop: 'var(--space-1)' }}>
                {data.agent.loop_score.toFixed(2)}
              </div>
            </div>
          </div>
        )}
      </Panel>

      {/* Graph Nodes Panel */}
      <Panel
        title="LangGraph Transition Nodes"
        icon={<Activity size={18} />}
        empty={!nodes || nodes.items.length === 0}
        emptyTitle="No Execution Graph Recorded"
        emptyMessage="Agent has not emitted graph_node spans yet. Run an agent with the cloudsentinel SDK adapter."
      >
        {nodes && nodes.items.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
            <div style={{ fontSize: 'var(--type-micro-size)', color: 'var(--color-text-muted)' }}>
              Recent Steps ({nodes.items.length} transitions captured):
            </div>
            <div style={{ display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
              {nodes.items.slice(-8).map((item, idx) => (
                <div
                  key={idx}
                  style={{
                    backgroundColor: 'var(--color-surface-elevated)',
                    border: '1px solid var(--color-border)',
                    padding: 'var(--space-2) var(--space-3)',
                    borderRadius: 'var(--radius-sm)',
                    fontFamily: 'var(--font-mono)',
                    fontSize: 'var(--type-micro-size)',
                  }}
                >
                  <span style={{ color: 'var(--color-text-primary)' }}>{item.node}</span>
                  <span style={{ color: 'var(--color-text-muted)', margin: '0 var(--space-1)' }}>→</span>
                  <span style={{ color: 'var(--color-accent)' }}>{item.next}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </Panel>

      {/* Memory Editor Placeholder */}
      <Panel
        title="Agent Working Memory"
        icon={<Database size={18} />}
        empty={!data?.memory}
        emptyTitle="Memory is Clean"
        emptyMessage="No persistent memory keys stored for this agent."
      >
        {data?.memory && (
          <pre
            style={{
              backgroundColor: 'var(--color-canvas)',
              padding: 'var(--space-4)',
              borderRadius: 'var(--radius-sm)',
              fontFamily: 'var(--font-mono)',
              fontSize: 'var(--type-body-sm-size)',
              overflowX: 'auto',
            }}
          >
            {JSON.stringify(data.memory.content, null, 2)}
          </pre>
        )}
      </Panel>
    </div>
  );
};
