import React from 'react';
import type { AgentView } from '../api/types';
import { StateBadge } from './StateBadge';
import { ArrowRight, ShieldAlert } from 'lucide-react';
import { areaFromLine, hashString, mulberry32, smoothPath } from './charts';

interface AgentCardProps {
  agent: AgentView;
  onClick: () => void;
  className?: string;
}

/**
 * Deterministic fluctuating sparkline. Seeded from the agent id plus its quantised burn rate and
 * tokens/min, so every card has a distinct waveform that only changes when the load meaningfully does.
 */
export function getAgentSparkline(
  agentId: string,
  usdPerMin: number,
  tokensPerMin: number,
  loopScore: number,
  width = 240,
  height = 38
) {
  const seed = hashString(`${agentId}|${Math.round(usdPerMin * 1000)}|${Math.round(tokensPerMin / 250)}`);
  const rnd = mulberry32(seed);
  const n = 20;
  const phaseA = rnd() * Math.PI * 2;
  const phaseB = rnd() * Math.PI * 2;
  const freqA = 0.5 + rnd() * 0.5;
  const freqB = 1.1 + rnd() * 0.9;
  const amp = 0.14 + rnd() * 0.1;
  const runaway = Math.max(0, Math.min(1, loopScore));
  const pts = [];
  for (let i = 0; i < n; i++) {
    const t = i / (n - 1);
    const wave =
      Math.sin(phaseA + i * freqA) * amp +
      Math.cos(phaseB + i * freqB) * amp * 0.7 +
      (rnd() - 0.5) * 0.12;
    // Looping agents ramp up toward the right edge
    const ramp = runaway >= 0.4 ? Math.pow(t, 2.2) * runaway * 0.5 : 0;
    const v = Math.max(0.08, Math.min(0.94, 0.42 + wave + ramp));
    pts.push({ x: t * width, y: height - 3 - v * (height - 8) });
  }
  const linePath = smoothPath(pts);
  const last = pts[pts.length - 1];
  return { linePath, areaPath: areaFromLine(linePath, last, pts[0], height), lastPoint: last };
}

export const AgentCard: React.FC<AgentCardProps> = ({ agent, onClick, className = '' }) => {
  // Each agent's true individual spend-to-budget ratio
  const budget = Math.max(0.01, agent.budget_usd);
  const spend = agent.spend_usd;
  const budgetRatio = spend / budget;
  const budgetPct = Math.min(100, Math.round(budgetRatio * 100));
  const budgetBarPct = spend > 0 ? Math.max(2, Math.min(100, budgetRatio * 100)) : 0;

  const isCritical = agent.state === 'killed' || agent.state === 'paused';
  const isSuspicious = agent.state === 'suspicious';
  const isWarning = isSuspicious || (!isCritical && budgetPct > 70);
  const isAnomalous = isCritical || isSuspicious;

  // Rose/Amber only for anomalous or near-budget nodes; healthy nodes stay Emerald/Cyan
  const budgetFill = isCritical
    ? 'linear-gradient(90deg, #be123c, #f43f5e)'
    : isWarning
    ? 'linear-gradient(90deg, #d97706, #f59e0b)'
    : 'linear-gradient(90deg, #06b6d4, #10b981)';
  const sparklineColor = isCritical
    ? '#f43f5e'
    : isWarning
    ? '#f59e0b'
    : agent.loop_score >= 0.4
    ? '#f59e0b'
    : '#06b6d4';

  // Loop score
  const loopScore = Math.max(0, Math.min(1, agent.loop_score));
  const loopPct = Math.round(loopScore * 100);
  const isLoopAnomaly = loopScore >= 0.4;
  const loopFill =
    loopScore >= 0.6
      ? 'linear-gradient(90deg, #be123c, #f43f5e)'
      : loopScore >= 0.4
      ? 'linear-gradient(90deg, #d97706, #f59e0b)'
      : 'linear-gradient(90deg, #059669, #10b981)';

  // Baseline ratio formatting (Task A4 note)
  let baselineText = '';
  const median = agent.baseline?.tokens_per_min?.median;
  if (median && median > 0) {
    baselineText = ` — ${(agent.tokens_per_min / median).toFixed(1)}× normal`;
  }

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

  const sparkline = getAgentSparkline(
    agent.agent_id,
    agent.usd_per_min,
    agent.tokens_per_min,
    agent.loop_score
  );

  const pulseClass = isCritical ? 'anomaly-rose' : isSuspicious ? 'anomaly-amber' : '';
  const badgeColor = isCritical ? '#f43f5e' : '#f59e0b';
  const idleBorder = '1px solid rgba(255, 255, 255, 0.08)';

  const handleKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onClick();
    }
  };

  const microLabel: React.CSSProperties = {
    fontSize: 'var(--type-micro-size)',
    color: 'var(--color-text-muted)',
    fontFamily: 'var(--font-mono)',
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
  };
  const track: React.CSSProperties = {
    height: '5px',
    backgroundColor: 'rgba(255,255,255,0.07)',
    borderRadius: '3px',
    overflow: 'hidden',
  };

  return (
    <div
      role="button"
      tabIndex={0}
      aria-label={`Inspect agent ${agent.agent_id}, state ${agent.state}`}
      data-testid={`agent-card-${agent.agent_id}`}
      onClick={onClick}
      onKeyDown={handleKeyDown}
      className={`agent-card glass ${pulseClass} ${className}`}
      style={{
        border: isAnomalous ? `1px solid ${badgeColor}88` : idleBorder,
        padding: 'var(--space-4)',
        display: 'flex',
        flexDirection: 'column',
        gap: 'var(--space-3)',
        cursor: 'pointer',
        outline: 'none',
        minWidth: 0,
      }}
    >
      {/* Header */}
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
              ...microLabel,
              backgroundColor: 'rgba(255,255,255,0.06)',
              padding: '1px 6px',
              borderRadius: 'var(--radius-sm)',
            }}
          >
            {agent.runtime}
          </span>
        </div>
        <StateBadge state={agent.state} />
      </div>

      {/* Burn metrics + live sparkline */}
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          backgroundColor: 'rgba(5, 7, 11, 0.6)',
          borderRadius: '8px',
          border: '1px solid rgba(255,255,255,0.06)',
          padding: 'var(--space-2) var(--space-3)',
          gap: 'var(--space-2)',
        }}
      >
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-2)' }}>
          <div>
            <div style={microLabel}>Burn Rate</div>
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
            <div style={microLabel}>Tokens/min</div>
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

        <div style={{ width: '100%', height: '38px', position: 'relative' }}>
          <svg
            viewBox="0 0 240 38"
            preserveAspectRatio="none"
            style={{ width: '100%', height: '100%', overflow: 'visible' }}
            aria-hidden="true"
          >
            <defs>
              <linearGradient id={`grad-${agent.agent_id}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={sparklineColor} stopOpacity="0.34" />
                <stop offset="100%" stopColor={sparklineColor} stopOpacity="0" />
              </linearGradient>
            </defs>
            <path d={sparkline.areaPath} fill={`url(#grad-${agent.agent_id})`} />
            <path
              d={sparkline.linePath}
              fill="none"
              stroke={sparklineColor}
              strokeWidth="1.8"
              strokeLinecap="round"
              vectorEffect="non-scaling-stroke"
            />
          </svg>
          {/* Live pulse dot kept as HTML so it stays circular under non-uniform SVG scaling */}
          <span
            style={{
              position: 'absolute',
              right: 0,
              top: `${(sparkline.lastPoint.y / 38) * 100}%`,
              width: 7,
              height: 7,
              marginTop: -3.5,
              marginRight: -3,
              borderRadius: '50%',
              backgroundColor: sparklineColor,
              boxShadow: `0 0 8px ${sparklineColor}`,
            }}
          />
        </div>
      </div>

      {/* Spend vs Budget */}
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
        <div style={track}>
          <div
            className="meter-fill"
            style={{
              height: '100%',
              width: `${budgetBarPct}%`,
              background: budgetFill,
              borderRadius: '3px',
            }}
          />
        </div>
      </div>

      {/* Loop Score */}
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
        <div style={track}>
          <div
            className="meter-fill"
            style={{
              height: '100%',
              width: `${loopPct}%`,
              background: loopFill,
              borderRadius: '3px',
            }}
          />
        </div>
      </div>

      {/* Footer: quarantine badge for anomalous nodes, plain last action otherwise */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 'var(--space-2)',
          paddingTop: 'var(--space-2)',
          borderTop: '1px solid rgba(255,255,255,0.08)',
          fontSize: 'var(--type-micro-size)',
          color: 'var(--color-text-secondary)',
          marginTop: 'auto',
          minWidth: 0,
        }}
      >
        {isAnomalous ? (
          <div
            data-testid={`quarantine-badge-${agent.agent_id}`}
            title={lastActionText}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              minWidth: 0,
              fontFamily: 'var(--font-mono)',
              fontSize: '11px',
              fontWeight: 600,
              color: badgeColor,
              backgroundColor: `${badgeColor}1f`,
              border: `1px solid ${badgeColor}66`,
              borderRadius: '4px',
              padding: '3px 8px',
            }}
          >
            <ShieldAlert size={12} style={{ flexShrink: 0 }} />
            <span style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {lastActionText}
            </span>
          </div>
        ) : (
          <div
            style={{
              fontFamily: 'var(--font-mono)',
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              minWidth: 0,
            }}
            title={lastActionText}
          >
            {lastActionText}
          </div>
        )}
        <ArrowRight size={14} color="var(--color-text-muted)" style={{ flexShrink: 0 }} />
      </div>
    </div>
  );
};
