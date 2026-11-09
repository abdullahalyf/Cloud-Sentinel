import React from 'react';

interface LoadingStateProps {
  lines?: number;
  className?: string;
}

export const LoadingState: React.FC<LoadingStateProps> = ({ lines = 3, className = '' }) => {
  return (
    <div
      role="status"
      aria-label="Loading content"
      className={`loading-skeleton-container ${className}`}
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 'var(--space-3)',
        padding: 'var(--space-4)',
        width: '100%',
      }}
    >
      {/* Header skeleton */}
      <div
        className="skeleton-bar"
        style={{
          height: '24px',
          width: '40%',
          backgroundColor: 'var(--color-surface-elevated)',
          borderRadius: 'var(--radius-sm)',
        }}
      />
      {/* Body lines */}
      {Array.from({ length: lines }).map((_, i) => (
        <div
          key={i}
          className="skeleton-bar"
          style={{
            height: '16px',
            width: i === lines - 1 ? '70%' : '100%',
            backgroundColor: 'var(--color-surface-elevated)',
            borderRadius: 'var(--radius-sm)',
            opacity: 0.8 - i * 0.15,
          }}
        />
      ))}
      <span style={{ position: 'absolute', width: '1px', height: '1px', overflow: 'hidden', clip: 'rect(0,0,0,0)' }}>
        Loading...
      </span>
    </div>
  );
};
