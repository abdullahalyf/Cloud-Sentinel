import React from 'react';

export interface StatTileProps {
  label: string;
  value: string | number;
  subtext?: string;
  icon?: React.ReactNode;
  color?: string;
  badge?: React.ReactNode;
  className?: string;
}

export const StatTile: React.FC<StatTileProps> = ({
  label,
  value,
  subtext,
  icon,
  color = 'var(--color-text-primary)',
  badge,
  className = '',
}) => {
  return (
    <div
      role="region"
      aria-label={label}
      className={`bento-stat-tile card ${className}`}
      style={{
        padding: 'var(--space-4)',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        minHeight: '110px',
        position: 'relative',
        transition: 'border-color var(--transition-fast)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 'var(--space-2)' }}>
        <span
          style={{
            fontSize: 'var(--type-micro-size)',
            fontFamily: 'var(--font-mono)',
            textTransform: 'uppercase',
            color: 'var(--color-text-muted)',
            letterSpacing: '0.05em',
            fontWeight: 600,
          }}
        >
          {label}
        </span>
        {icon && <span style={{ color: 'var(--color-text-muted)', display: 'flex' }}>{icon}</span>}
      </div>

      <div style={{ display: 'flex', alignItems: 'baseline', gap: 'var(--space-2)' }}>
        <div
          className="tabular-nums"
          style={{
            fontSize: 'var(--type-title-md-size)',
            lineHeight: 'var(--type-title-md-lh)',
            fontWeight: 700,
            color,
            fontFamily: 'var(--font-mono)',
          }}
        >
          {value}
        </div>
        {badge}
      </div>

      {subtext && (
        <div
          style={{
            fontSize: 'var(--type-micro-size)',
            color: 'var(--color-text-secondary)',
            marginTop: 'var(--space-1)',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {subtext}
        </div>
      )}
    </div>
  );
};
