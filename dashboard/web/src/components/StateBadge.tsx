import React, { useEffect, useRef, useState } from 'react';
import type { AgentState } from '../api/types';

interface StateBadgeProps {
  state: AgentState;
  className?: string;
}

const STATE_CONFIG: Record<
  AgentState,
  {
    label: string;
    color: string;
    bg: string;
    border: string;
    pulseDot?: boolean;
  }
> = {
  healthy: {
    label: 'HEALTHY',
    color: 'var(--color-state-healthy)',
    bg: 'var(--color-state-healthy-bg)',
    border: 'var(--color-state-healthy-border)',
    pulseDot: true,
  },
  suspicious: {
    label: 'SUSPICIOUS',
    color: 'var(--color-state-suspicious)',
    bg: 'var(--color-state-suspicious-bg)',
    border: 'var(--color-state-suspicious-border)',
    pulseDot: false,
  },
  paused: {
    label: 'PAUSED',
    color: 'var(--color-state-paused-text)',
    bg: 'var(--color-state-paused-bg)',
    border: 'var(--color-state-paused-border)',
    pulseDot: false,
  },
  probation: {
    label: 'PROBATION',
    color: 'var(--color-state-probation)',
    bg: 'var(--color-state-probation-bg)',
    border: 'var(--color-state-probation-border)',
    pulseDot: true,
  },
  killed: {
    label: 'KILLED',
    color: 'var(--color-state-killed-text)',
    bg: 'var(--color-state-killed-bg)',
    border: 'var(--color-state-killed-border)',
    pulseDot: false,
  },
};

export const StateBadge: React.FC<StateBadgeProps> = ({ state, className = '' }) => {
  const config = STATE_CONFIG[state] || STATE_CONFIG.healthy;
  const prevStateRef = useRef<AgentState>(state);
  const [animating, setAnimating] = useState(false);

  useEffect(() => {
    if (prevStateRef.current !== state) {
      setAnimating(true);
      const timer = setTimeout(() => setAnimating(false), 200);
      prevStateRef.current = state;
      return () => clearTimeout(timer);
    }
  }, [state]);

  return (
    <span
      role="status"
      aria-label={`Agent state: ${config.label}`}
      className={`state-badge ${className} ${animating ? 'state-change-anim' : ''}`}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        height: 24,
        padding: '0 10px',
        borderRadius: 999,
        backgroundColor: config.bg,
        color: config.color,
        fontSize: 12,
        fontWeight: 700,
        whiteSpace: 'nowrap',
        transition: 'transform var(--transition-base), background-color var(--transition-base)',
        transform: animating ? 'scale(1.08)' : 'scale(1)',
      }}
    >
      <span
        style={{
          width: '6px',
          height: '6px',
          borderRadius: '50%',
          backgroundColor: config.color,
          display: 'inline-block',
        }}
      />
      <span className="state-badge-label">{config.label}</span>
    </span>
  );
};
