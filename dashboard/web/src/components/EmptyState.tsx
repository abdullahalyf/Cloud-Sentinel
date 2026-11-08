import React from 'react';
import { Inbox } from 'lucide-react';

interface EmptyStateProps {
  title?: string;
  message?: string;
  icon?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}

export const EmptyState: React.FC<EmptyStateProps> = ({
  title = 'No Data Available',
  message = 'There are no active records in this view. Data will appear automatically when agents emit telemetry or trigger policy gates.',
  icon,
  action,
  className = '',
}) => {
  return (
    <div
      role="region"
      aria-label={title}
      className={`empty-state-panel ${className}`}
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 'var(--space-8) var(--space-4)',
        textAlign: 'center',
        backgroundColor: 'var(--color-surface)',
        borderRadius: 'var(--radius-md)',
        border: '1px solid var(--color-border)',
        minHeight: '200px',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: '48px',
          height: '48px',
          borderRadius: '50%',
          backgroundColor: 'var(--color-surface-elevated)',
          color: 'var(--color-text-muted)',
          marginBottom: 'var(--space-3)',
        }}
      >
        {icon || <Inbox size={24} />}
      </div>
      <h3
        style={{
          fontSize: 'var(--type-body-size)',
          lineHeight: 'var(--type-body-lh)',
          fontWeight: 600,
          color: 'var(--color-text-primary)',
          marginBottom: 'var(--space-2)',
        }}
      >
        {title}
      </h3>
      <p
        style={{
          fontSize: 'var(--type-body-sm-size)',
          lineHeight: 'var(--type-body-sm-lh)',
          color: 'var(--color-text-secondary)',
          maxWidth: '440px',
          marginBottom: action ? 'var(--space-4)' : 0,
        }}
      >
        {message}
      </p>
      {action && <div>{action}</div>}
    </div>
  );
};
