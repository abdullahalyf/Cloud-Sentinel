import React from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

interface ErrorStateProps {
  error?: Error | string | null;
  detail?: string;
  onRetry?: () => void;
  className?: string;
}

export const ErrorState: React.FC<ErrorStateProps> = ({ error, detail, onRetry, className = '' }) => {
  let displayMessage = 'An unexpected error occurred while communicating with the C2 API.';
  if (detail) {
    displayMessage = detail;
  } else if (typeof error === 'string') {
    displayMessage = error;
  } else if (error instanceof Error) {
    displayMessage = error.message;
  }

  const isNetworkIssue =
    displayMessage.toLowerCase().includes('network') ||
    displayMessage.toLowerCase().includes('fetch') ||
    displayMessage.toLowerCase().includes('connection refused') ||
    displayMessage.toLowerCase().includes('0:');

  return (
    <div
      role="alert"
      aria-live="assertive"
      className={`error-diagnostic-panel ${className}`}
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'flex-start',
        padding: 'var(--space-4)',
        backgroundColor: 'var(--color-state-killed-bg)',
        border: '1px solid var(--color-state-killed-border)',
        borderRadius: 'var(--radius-md)',
        color: 'var(--color-text-primary)',
        width: '100%',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', marginBottom: 'var(--space-2)' }}>
        <AlertTriangle size={20} color="var(--color-state-killed)" />
        <span style={{ fontWeight: 600, fontSize: 'var(--type-body-size)', color: 'var(--color-state-killed)' }}>
          API Diagnostic Warning
        </span>
      </div>

      <p
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 'var(--type-micro-size)',
          lineHeight: 'var(--type-micro-lh)',
          color: 'var(--color-text-primary)',
          backgroundColor: 'rgba(0, 0, 0, 0.4)',
          padding: 'var(--space-2) var(--space-3)',
          borderRadius: 'var(--radius-sm)',
          width: '100%',
          overflowX: 'auto',
          wordBreak: 'break-word',
          marginBottom: 'var(--space-3)',
        }}
      >
        {displayMessage}
      </p>

      {isNetworkIssue && (
        <div
          style={{
            fontSize: 'var(--type-micro-size)',
            color: 'var(--color-text-secondary)',
            marginBottom: 'var(--space-3)',
          }}
        >
          <strong>Connection Hint:</strong> Ensure the C2 Mock API is actively serving on port 8000 (
          <code className="tabular-nums" style={{ color: 'var(--color-accent)' }}>
            python -m shared.mocks.mock_api
          </code>
          ) or check your Vite proxy settings.
        </div>
      )}

      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          aria-label="Retry failed request"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 'var(--space-2)',
            padding: 'var(--space-2) var(--space-4)',
            backgroundColor: 'var(--color-surface-elevated)',
            border: '1px solid var(--color-border)',
            borderRadius: 'var(--radius-sm)',
            color: 'var(--color-text-primary)',
            fontSize: 'var(--type-body-sm-size)',
            fontWeight: 500,
            cursor: 'pointer',
            transition: 'background-color var(--transition-fast)',
          }}
          onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'var(--color-surface)')}
          onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'var(--color-surface-elevated)')}
        >
          <RefreshCw size={14} />
          Retry Request
        </button>
      )}
    </div>
  );
};
