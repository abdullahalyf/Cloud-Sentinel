import React from 'react';
import { LoadingState } from './LoadingState';
import { EmptyState } from './EmptyState';
import { ErrorState } from './ErrorState';

export interface PanelProps {
  title: string;
  icon?: React.ReactNode;
  actions?: React.ReactNode;
  loading?: boolean;
  error?: Error | string | null;
  empty?: boolean;
  emptyTitle?: string;
  emptyMessage?: string;
  onRetry?: () => void;
  children?: React.ReactNode;
  className?: string;
}

export const Panel: React.FC<PanelProps> = ({
  title,
  icon,
  actions,
  loading = false,
  error = null,
  empty = false,
  emptyTitle,
  emptyMessage,
  onRetry,
  children,
  className = '',
}) => {
  return (
    <section
      aria-label={title}
      className={`mission-panel ${className}`}
      style={{
        backgroundColor: 'var(--color-surface)',
        border: '1px solid var(--color-border)',
        borderRadius: 'var(--radius-md)',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        width: '100%',
      }}
    >
      {/* Panel Header */}
      <header
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: 'var(--space-3) var(--space-4)',
          borderBottom: '1px solid var(--color-border)',
          minHeight: '48px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
          {icon && <span style={{ color: 'var(--color-text-muted)', display: 'flex' }}>{icon}</span>}
          <h2
            style={{
              fontSize: 'var(--type-body-size)',
              lineHeight: 'var(--type-body-lh)',
              fontWeight: 600,
              color: 'var(--color-text-primary)',
            }}
          >
            {title}
          </h2>
        </div>
        {actions && <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>{actions}</div>}
      </header>

      {/* Panel Body */}
      <div
        style={{
          padding: 'var(--space-4)',
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        {loading ? (
          <LoadingState />
        ) : error ? (
          <ErrorState error={error} onRetry={onRetry} />
        ) : empty ? (
          <EmptyState title={emptyTitle} message={emptyMessage} />
        ) : (
          children
        )}
      </div>
    </section>
  );
};
