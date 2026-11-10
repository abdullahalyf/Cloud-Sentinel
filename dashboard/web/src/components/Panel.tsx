import React from 'react';
import { LoadingState } from './LoadingState';
import { EmptyState } from './EmptyState';
import { ErrorState } from './ErrorState';

export interface PanelProps {
  title: string;
  /** one line under the title, in the muted colour */
  subtitle?: React.ReactNode;
  /** kept for older call sites; the card header no longer shows icons */
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

/** A card with a title, an optional subtitle and actions, and the three mandatory states. */
export const Panel: React.FC<PanelProps> = ({
  title,
  subtitle,
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
      className={`mission-panel card ${className}`}
      style={{ display: 'flex', flexDirection: 'column', width: '100%', minWidth: 0 }}
    >
      <header
        style={{
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          gap: 'var(--space-3)',
          padding: '20px 22px 0',
          flexWrap: 'wrap',
        }}
      >
        <div style={{ minWidth: 0 }}>
          <h2 className="card-title">{title}</h2>
          {subtitle && <p className="card-sub">{subtitle}</p>}
        </div>
        {actions && <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', flexWrap: 'wrap' }}>{actions}</div>}
      </header>

      <div style={{ padding: '16px 22px 22px', flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
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
