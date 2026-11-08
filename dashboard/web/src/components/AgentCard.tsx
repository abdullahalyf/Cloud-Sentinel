import React from 'react';
import type { AgentView } from '../api/types';
import { StateBadge } from './StateBadge';
import { ArrowRight } from 'lucide-react';

interface AgentCardProps {
  agent: AgentView;
  onClick: () => void;
  className?: string;
}

/**
 * Deterministically generates an up-and-down SVG sparkline path for an agent
 * based on its ID, tokens per minute, and loop score.
 */
function getAgentSparkline(
  agentId: string,
  _tokensPerMin: number,
  _loopScore: number,
  width = 240,
  height = 34
) {
  let hash = 0;
  for (let i = 0; i < agentId.length; i++) {
    hash = (hash * 31 + agentId.charCodeAt(i)) & 0xffffffff;
  }

  const numPoints = 12;
  const points: { x: number; y: number }[] = [];
  const stepX = width / (numPoints - 1);

  for (let i = 0; i < numPoints; i++) {
    const x = i * stepX;
    // Harmonic wave oscillation based on agent identity hash
    const wave1 = Math.sin((hash % 10) + i * 0.9) * 0.35;
    const wave2 = Math.cos(((hash >> 3) % 10) + i * 1.4) * 0.25;

    // Anomalous runaway spike for looping/paused agents (beta/gamma)
    const anomalySpike =
      agentId === 'beta' && i >= 7
        ? 0.55
        : agentId === 'gamma' && i >= 9
        ? 0.4
        : 0;

    const normalized = Math.max(0.12, Math.min(0.92, 0.45 + wave1 + wave2 + anomalySpike));
    const y = height - normalized * (height - 6) - 3;
    points.push({ x, y });
  }

  const linePath = points.reduce(
    (acc, pt, i) => `${acc} ${i === 0 ? 'M' : 'L'} ${pt.x.toFixed(1)} ${pt.y.toFixed(1)}`,
    ''
  );
  const areaPath = `${linePath} L ${width} ${height} L 0 ${height} Z`;

  return { linePath, areaPath, lastPoint: points[points.length - 1] };
}

export const AgentCard: React.FC<AgentCardProps> = ({ agent, onClick, className = '' }) => {
  // Budget calculations
  const budget = Math.max(0.01, agent.budget_usd);
  const spend = agent.spend_usd;
  const budgetPct = Math.min(100, Math.round((spend / budget) * 100));

  // Dynamic progress bar coloring:
  // Emerald for normal spend, Amber for >70%, Rose ONLY for paused/runaway/critical nodes
  const isCritical = agent.state === 'killed' || agent.state === 'paused';
  const isWarning = agent.state === 'suspicious' || (agent.state === 'healthy' && budgetPct > 70);

  const budgetColor = isCritical
    ? 'var(--color-state-killed)'
    : isWarning
    ? 'var(--color-state-suspicious)'
    : 'var(--color-state-healthy)';

  // Loop score calculations
  const loopScore = Math.max(0, Math.min(1, agent.loop_score));
  const loopPct = Math.round(loopScore * 100);
  const isLoopAnomaly = loopScore >= 0.4;
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

  // Sparkline wave for this agent
  const sparkline = getAgentSparkline(agent.agent_id, agent.tokens_per_min, agent.loop_score);
  const sparklineColor = isCritical
    ? 'var(--color-state-killed)'
    : isWarning
    ? 'var(--color-state-suspicious)'
    : 'var(--color-telemetry-cyan)';

  // Border & Glow for anomalous nodes
  const cardBorder =
    agent.state === 'killed'
      ? '1px solid rgba(244, 63, 94, 0.55)'
      : agent.state === 'paused'
      ? '1px solid rgba(99, 102, 241, 0.6)'
      : agent.state === 'suspicious'
      ? '1px solid rgba(245, 158, 11, 0.55)'
      : '1px solid var(--color-border)';

  const cardBoxShadow =
    agent.state === 'killed'
      ? '0 0 20px rgba(244, 63, 94, 0.22)'
      : agent.state === 'paused'
      ? '0 0 20px rgba(99, 102, 241, 0.25)'
      : agent.state === 'suspicious'
      ? '0 0 16px rgba(245, 158, 11, 0.18)'
      : 'none';

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
        border: cardBorder,
        borderRadius: 'var(--radius-md)',
        padding: 'var(--space-4)',
        display: 'flex',
        flexDirection: 'column',
        gap: 'var(--space-3)',
        cursor: 'pointer',
        position: 'relative',
        boxShadow: cardBoxShadow,
        transition: 'all var(--transition-fast)',
        outline: 'none',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = 'var(--color-border-accent)';
        e.currentTarget.style.backgroundColor = 'var(--color-surface-elevated)';
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = cardBorder.split(' ')[2] || 'var(--color-border)';
        e.currentTarget.style.backgroundColor = 'var(--color-surface)';
      }}
      onFocus={(e) => {
        e.currentTarget.style.borderColor = 'var(--color-focus-ring)';
        e.currentTarget.style.boxShadow = '0 0 0 2px var(--color-focus-ring)';
      }}
      onBlur={(e) => {
        e.currentTarget.style.borderColor = cardBorder.split(' ')[2] || 'var(--color-border)';
        e.currentTarget.style.boxShadow = cardBoxShadow;
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
            {agent.runtime}
          </span>
        </div>
        <StateBadge state={agent.state} />
      </div>

      {/* Burn Rate & Tokens/Min Box with Live Sparkline */}
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          backgroundColor: 'var(--color-canvas)',
          borderRadius: 'var(--radius-sm)',
          border: '1px solid var(--color-border)',
          padding: 'var(--space-2) var(--space-3)',
          gap: 'var(--space-2)',
        }}
      >
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-2)' }}>
          <div>
            <div
              style={{
                fontSize: 'var(--type-micro-size)',
                color: 'var(--color-text-muted)',
                fontFamily: 'var(--font-mono)',
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
              }}
            >
              Burn Rate
            </div>
            <div
              className="tabular-nums"
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 'var(--type-body-sm-size)',
                fontWeight: 700,
                color:
                  agent.usd_per_min > 0.04
                    ? 'var(--color-state-suspicious)'
                    : 'var(--color-text-primary)',
                marginTop: '2px',
              }}
            >
              ${agent.usd_per_min.toFixed(4)}
              <span style={{ fontSize: '11px', color: 'var(--color-text-muted)', fontWeight: 400 }}>
                /min
              </span>
            </div>
          </div>

          <div>
            <div
              style={{
                fontSize: 'var(--type-micro-size)',
                color: 'var(--color-text-muted)',
                fontFamily: 'var(--font-mono)',
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
              }}
            >
              Tokens/min
            </div>
            <div
              className="tabular-nums"
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 'var(--type-body-sm-size)',
                fontWeight: 700,
                color: 'var(--color-text-primary)',
                marginTop: '2px',
              }}
            >
              {tokensFormatted}
              <span
                style={{
                  fontSize: '11px',
                  color:
                    agent.tokens_per_min > 10000
                      ? 'var(--color-state-suspicious)'
                      : 'var(--color-text-muted)',
                  fontWeight: 500,
                }}
              >
                {baselineText}
              </span>
            </div>
          </div>
        </div>

        {/* Up-and-Down Deterministic SVG Sparkline */}
        <div style={{ width: '100%', height: '32px', position: 'relative', marginTop: '2px' }}>
          <svg
            viewBox="0 0 240 34"
            preserveAspectRatio="none"
            style={{ width: '100%', height: '100%', overflow: 'visible' }}
          >
            <defs>
              <linearGradient id={`grad-${agent.agent_id}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={sparklineColor} stopOpacity="0.32" />
                <stop offset="100%" stopColor={sparklineColor} stopOpacity="0.0" />
              </linearGradient>
            </defs>
            {/* Area fill */}
            <path d={sparkline.areaPath} fill={`url(#grad-${agent.agent_id})`} />
            {/* Stroke line */}
            <path
              d={sparkline.linePath}
              fill="none"
              stroke={sparklineColor}
              strokeWidth="1.8"
              strokeLinecap="round"
            />
            {/* End point pulse */}
            <circle
              cx={sparkline.lastPoint.x}
              cy={sparkline.lastPoint.y}
              r="2.5"
              fill={sparklineColor}
              style={{ filter: `drop-shadow(0 0 4px ${sparklineColor})` }}
            />
          </svg>
        </div>
      </div>

      {/* Spend vs Budget Meter */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            fontSize: 'var(--type-micro-size)',
            fontFamily: 'var(--font-mono)',
          }}
        >
          <span style={{ color: 'var(--color-text-muted)', textTransform: 'uppercase' }}>
            Spend / Budget
          </span>
          <span
            className="tabular-nums"
            style={{ color: 'var(--color-text-primary)', fontWeight: 600 }}
          >
            ${spend.toFixed(2)} / ${budget.toFixed(2)} ({budgetPct}%)
          </span>
        </div>
        <div
          style={{
            height: '4px',
            backgroundColor: 'var(--color-surface-elevated)',
            borderRadius: '2px',
            overflow: 'hidden',
          }}
        >
          <div
            style={{
              height: '100%',
              width: `${budgetPct}%`,
              backgroundColor: budgetColor,
              borderRadius: '2px',
              transition: 'width var(--transition-base)',
            }}
          />
        </div>
      </div>

      {/* Loop Score Bar */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            fontSize: 'var(--type-micro-size)',
            fontFamily: 'var(--font-mono)',
          }}
        >
          <span style={{ color: 'var(--color-text-muted)', textTransform: 'uppercase' }}>
            Loop Score
          </span>
          <span
            className="tabular-nums"
            style={{
              fontWeight: 600,
              color: isLoopAnomaly ? 'var(--color-state-killed)' : 'var(--color-state-healthy)',
            }}
          >
            {loopScore.toFixed(2)}
            {isLoopAnomaly && (
              <span
                style={{
                  marginLeft: '4px',
                  color: 'var(--color-state-killed)',
                  fontSize: '10px',
                  fontWeight: 700,
                }}
              >
                ⚠ ANOMALY
              </span>
            )}
          </span>
        </div>
        <div
          style={{
            height: '4px',
            backgroundColor: 'var(--color-surface-elevated)',
            borderRadius: '2px',
            overflow: 'hidden',
          }}
        >
          <div
            style={{
              height: '100%',
              width: `${loopPct}%`,
              backgroundColor: loopColor,
              borderRadius: '2px',
              transition: 'width var(--transition-base)',
            }}
          />
        </div>
      </div>

      {/* Card Footer: Last Action & Navigation Arrow */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          paddingTop: 'var(--space-2)',
          borderTop: '1px solid var(--color-border)',
          fontSize: 'var(--type-micro-size)',
          color: 'var(--color-text-secondary)',
          marginTop: 'auto',
        }}
      >
        <div
          style={{
            fontFamily: 'var(--font-mono)',
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            maxWidth: 'calc(100% - 24px)',
          }}
          title={lastActionText}
        >
          {lastActionText}
        </div>
        <ArrowRight size={14} color="var(--color-text-muted)" style={{ flexShrink: 0 }} />
      </div>
    </div>
  );
};
