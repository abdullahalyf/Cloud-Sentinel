import React from 'react';
import type { AgentView } from '../api/types';
import { StateBadge } from './StateBadge';
import { ArrowRight } from 'lucide-react';

interface AgentCardProps {
  agent: AgentView;
  onClick: () => void;
  className?: string;
}

export const AgentCard: React.FC<AgentCardProps> = ({ agent, onClick, className = '' }) => {
  // Budget calculations
  const budget = Math.max(0.01, agent.budget_usd);
  const spend = agent.spend_usd;
  const budgetPct = Math.min(100, Math.round((spend / budget) * 100));
  const budgetColor =
    budgetPct >= 90
      ? 'var(--color-state-killed)'
      : budgetPct >= 75
      ? 'var(--color-state-suspicious)'
      : 'var(--color-telemetry-cyan)';

  // Loop score calculations
  const loopScore = Math.max(0, Math.min(1, agent.loop_score));
  const loopPct = Math.round(loopScore * 100);
  const loopColor =
    loopScore >= 0.6
      ? 'var(--color-state-killed)'
      : loopScore >= 0.4
      ? 'var(--color-state-suspicious)'
      : 'var(--color-state-healthy)';

  // Baseline ratio formatting (Task A4 note)
  let baselineText = '';
  const median = agent.baseline?.tokens_per_min?.median;
  if (median && median > 0) {
    const ratio = (agent.tokens_per_min / median).toFixed(1);
    baselineText = ` — ${ratio}× normal`;
  }

  // Token count formatting
  const tokensFormatted =
    agent.tokens_per_min >= 1000
      ? `${(agent.tokens_per_min / 1000).toFixed(1)}k`
      : agent.tokens_per_min.toString();

  // Last action display
  let lastActionText = 'Operating nominally within budget.';
  if (agent.last_verdict) {
    lastActionText = `[${agent.last_verdict.action}] ${agent.last_verdict.reason}`;
  } else if (agent.state === 'paused') {
    lastActionText = 'Agent paused by circuit breaker quarantine.';
  } else if (agent.state === 'killed') {
    lastActionText = 'Terminated by hard limit policy enforcement.';
  } else if (agent.state === 'probation') {
    lastActionText = 'Resumed on probation; active surveillance window.';
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onClick();
    }
  };

  return (
    <div
      role="button"
      tabIndex={0}
      aria-label={`Inspect agent ${agent.agent_id}, state ${agent.state}`}
      data-testid={`agent-card-${agent.agent_id}`}
      onClick={onClick}
      onKeyDown={handleKeyDown}
      className={`agent-card ${className}`}
      style={{
        backgroundColor: 'var(--color-surface)',
        border: '1px solid var(--color-border)',
        borderRadius: 'var(--radius-md)',
        padding: 'var(--space-4)',
        display: 'flex',
        flexDirection: 'column',
        gap: 'var(--space-3)',
        cursor: 'pointer',
        position: 'relative',
        transition: 'all var(--transition-fast)',
        outline: 'none',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = 'var(--color-border-accent)';
        e.currentTarget.style.backgroundColor = 'var(--color-surface-elevated)';
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = 'var(--color-border)';
        e.currentTarget.style.backgroundColor = 'var(--color-surface)';
      }}
      onFocus={(e) => {
        e.currentTarget.style.borderColor = 'var(--color-focus-ring)';
        e.currentTarget.style.boxShadow = '0 0 0 2px var(--color-focus-ring)';
      }}
      onBlur={(e) => {
        e.currentTarget.style.borderColor = 'var(--color-border)';
        e.currentTarget.style.boxShadow = 'none';
      }}
    >
      {/* Card Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 'var(--type-body-size)',
              fontWeight: 700,
              color: 'var(--color-text-primary)',
            }}
          >
            {agent.agent_id}
          </span>
          <span
            style={{
              fontSize: 'var(--type-micro-size)',
              fontFamily: 'var(--font-mono)',
              color: 'var(--color-text-muted)',
              backgroundColor: 'var(--color-surface-elevated)',
              padding: '1px 6px',
              borderRadius: 'var(--radius-sm)',
              textTransform: 'uppercase',
            }}
          >
            {agent.runtime || 'local'}
          </span>
        </div>
        <StateBadge state={agent.state} />
      </div>

      {/* Primary Telemetry Metrics */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-2)' }}>
        <div style={{ backgroundColor: 'var(--color-canvas)', padding: 'var(--space-2) var(--space-3)', borderRadius: 'var(--radius-sm)' }}>
          <div style={{ fontSize: 'var(--type-micro-size)', color: 'var(--color-text-muted)', fontFamily: 'var(--font-mono)' }}>
            BURN RATE
          </div>
          <div
            className="tabular-nums"
            style={{
              fontSize: 'var(--type-body-size)',
              fontWeight: 700,
              color: 'var(--color-text-primary)',
              fontFamily: 'var(--font-mono)',
              marginTop: '2px',
            }}
          >
            ${agent.usd_per_min.toFixed(4)}
            <span style={{ fontSize: '11px', color: 'var(--color-text-muted)' }}>/min</span>
          </div>
        </div>

        <div style={{ backgroundColor: 'var(--color-canvas)', padding: 'var(--space-2) var(--space-3)', borderRadius: 'var(--radius-sm)' }}>
          <div style={{ fontSize: 'var(--type-micro-size)', color: 'var(--color-text-muted)', fontFamily: 'var(--font-mono)' }}>
            TOKENS/MIN
          </div>
          <div
            className="tabular-nums"
            style={{
              fontSize: 'var(--type-body-size)',
              fontWeight: 700,
              color: 'var(--color-text-primary)',
              fontFamily: 'var(--font-mono)',
              marginTop: '2px',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
            title={`${agent.tokens_per_min.toLocaleString()} tokens/min${baselineText}`}
          >
            {tokensFormatted}
            <span style={{ fontSize: '11px', color: 'var(--color-text-muted)' }}>{baselineText}</span>
          </div>
        </div>
      </div>

      {/* Spend vs Budget Bar */}
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 'var(--type-micro-size)', marginBottom: '4px' }}>
          <span style={{ color: 'var(--color-text-muted)', fontFamily: 'var(--font-mono)' }}>SPEND / BUDGET</span>
          <span className="tabular-nums" style={{ color: 'var(--color-text-primary)', fontWeight: 600 }}>
            ${agent.spend_usd.toFixed(2)} / ${agent.budget_usd.toFixed(2)} ({budgetPct}%)
          </span>
        </div>
        <div
          role="progressbar"
          aria-valuenow={budgetPct}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label="Spend vs Budget"
          style={{
            height: '6px',
            width: '100%',
            backgroundColor: 'var(--color-surface-elevated)',
            borderRadius: '3px',
            overflow: 'hidden',
          }}
        >
          <div
            style={{
              height: '100%',
              width: `${budgetPct}%`,
              backgroundColor: budgetColor,
              borderRadius: '3px',
              transition: 'width var(--transition-base)',
            }}
          />
        </div>
      </div>

      {/* Loop Score Bar */}
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 'var(--type-micro-size)', marginBottom: '4px' }}>
          <span style={{ color: 'var(--color-text-muted)', fontFamily: 'var(--font-mono)' }}>LOOP SCORE</span>
          <span className="tabular-nums" style={{ color: loopColor, fontWeight: 700 }}>
            {agent.loop_score.toFixed(2)} {agent.loop_score >= 0.6 && '⚠ ANOMALY'}
          </span>
        </div>
        <div
          role="progressbar"
          aria-valuenow={loopPct}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label="Loop Score"
          style={{
            height: '6px',
            width: '100%',
            backgroundColor: 'var(--color-surface-elevated)',
            borderRadius: '3px',
            overflow: 'hidden',
          }}
        >
          <div
            style={{
              height: '100%',
              width: `${loopPct}%`,
              backgroundColor: loopColor,
              borderRadius: '3px',
              transition: 'width var(--transition-base)',
            }}
          />
        </div>
      </div>

      {/* Last Action Bar */}
      <div
        style={{
          borderTop: '1px solid var(--color-border)',
          paddingTop: 'var(--space-2)',
          marginTop: 'var(--space-1)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          fontSize: 'var(--type-micro-size)',
          color: 'var(--color-text-secondary)',
        }}
      >
        <div
          style={{
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
            maxWidth: '220px',
          }}
          title={lastActionText}
        >
          {lastActionText}
        </div>
        <ArrowRight size={14} color="var(--color-text-muted)" />
      </div>
    </div>
  );
};
