import React, { useEffect, useState } from 'react';
import { AlertTriangle, X } from 'lucide-react';

interface ConfirmDialogProps {
  isOpen: boolean;
  title: string;
  message: string;
  agentId: string;
  confirmLabel?: string;
  isDangerous?: boolean;
  onConfirm: (reason: string) => void;
  onCancel: () => void;
}

export const ConfirmDialog: React.FC<ConfirmDialogProps> = ({
  isOpen,
  title,
  message,
  agentId,
  confirmLabel = 'Confirm Action',
  isDangerous = true,
  onConfirm,
  onCancel,
}) => {
  const [reason, setReason] = useState('');

  // Handle Esc key to cancel dialog
  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onCancel();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onCancel]);

  // Reset reason when dialog opens
  useEffect(() => {
    if (isOpen) {
      setReason('');
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (reason.trim()) {
      onConfirm(reason.trim());
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-dialog-title"
      data-testid="confirm-dialog"
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        backgroundColor: 'rgba(25, 18, 34, 0.38)',
        zIndex: 99999,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 'var(--space-4)',
      }}
    >
      <div
        style={{
          width: '100%',
          maxWidth: '520px',
          backgroundColor: 'var(--color-surface)',
          border: '1px solid var(--color-border)',
          borderRadius: 'var(--radius-md)',
          boxShadow: 'var(--shadow-pop)',
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
          animation: 'modalIn 0.18s cubic-bezier(0, 0, 0.2, 1)',
        }}
      >
        {/* Modal Header */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: 'var(--space-4) var(--space-6)',
            borderBottom: '1px solid var(--color-border)',
            backgroundColor: isDangerous ? 'var(--color-state-killed-bg)' : 'var(--color-surface-elevated)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
            <AlertTriangle
              size={18}
              color={isDangerous ? 'var(--color-state-killed)' : 'var(--color-state-suspicious)'}
            />
            <h2
              id="confirm-dialog-title"
              style={{
                fontSize: 'var(--type-body-size)',
                fontWeight: 700,
                color: isDangerous ? 'var(--color-state-killed)' : 'var(--color-text-primary)',
              }}
            >
              {title}
            </h2>
          </div>
          <button
            type="button"
            data-testid="confirm-dialog-close"
            aria-label="Close dialog"
            onClick={onCancel}
            style={{
              color: 'var(--color-text-muted)',
              padding: '4px',
              borderRadius: 'var(--radius-sm)',
            }}
          >
            <X size={16} />
          </button>
        </div>

        {/* Modal Body */}
        <form onSubmit={handleSubmit} style={{ padding: 'var(--space-6)', display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
          <p style={{ fontSize: 'var(--type-body-sm-size)', color: 'var(--color-text-secondary)', lineHeight: 1.5 }}>
            {message} Target agent:{' '}
            <strong style={{ fontFamily: 'var(--font-mono)', color: 'var(--color-text-primary)' }}>{agentId}</strong>.
          </p>

          <div>
            <label
              htmlFor="confirm-reason"
              style={{
                display: 'block',
                fontSize: 'var(--type-micro-size)',
                fontFamily: 'var(--font-mono)',
                textTransform: 'uppercase',
                fontWeight: 700,
                color: 'var(--color-text-muted)',
                marginBottom: 'var(--space-1)',
              }}
            >
              Operator Justification Reason (Required):
            </label>
            <textarea
              id="confirm-reason"
              data-testid="confirm-reason-input"
              rows={3}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="e.g. Terminating rogue token spike exceeding safety limits"
              required
              autoFocus
              style={{
                width: '100%',
                backgroundColor: 'var(--color-canvas)',
                border: '1px solid var(--color-border)',
                borderRadius: 'var(--radius-sm)',
                padding: 'var(--space-2) var(--space-3)',
                color: 'var(--color-text-primary)',
                fontFamily: 'var(--font-sans)',
                fontSize: 'var(--type-body-sm-size)',
                outline: 'none',
                resize: 'vertical',
              }}
              onFocus={(e) => (e.currentTarget.style.borderColor = 'var(--color-focus-ring)')}
              onBlur={(e) => (e.currentTarget.style.borderColor = 'var(--color-border)')}
            />
          </div>

          {/* Modal Actions */}
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 'var(--space-3)', marginTop: 'var(--space-2)' }}>
            <button
              type="button"
              data-testid="confirm-cancel-btn"
              onClick={onCancel}
              style={{
                padding: 'var(--space-2) var(--space-4)',
                borderRadius: 'var(--radius-sm)',
                fontSize: 'var(--type-body-sm-size)',
                fontWeight: 600,
                backgroundColor: 'var(--color-surface-elevated)',
                color: 'var(--color-text-secondary)',
                border: '1px solid var(--color-border)',
              }}
            >
              Cancel (Esc)
            </button>
            <button
              type="submit"
              data-testid="confirm-submit-btn"
              disabled={!reason.trim()}
              style={{
                padding: 'var(--space-2) var(--space-4)',
                borderRadius: 'var(--radius-sm)',
                fontSize: 'var(--type-body-sm-size)',
                fontWeight: 600,
                backgroundColor: isDangerous ? 'var(--color-state-killed)' : 'var(--color-accent)',
                color: '#fff',
                border: 'none',
                cursor: reason.trim() ? undefined : 'not-allowed',
                opacity: reason.trim() ? 1 : 0.5,
                transition: 'opacity var(--transition-fast)',
              }}
            >
              {confirmLabel}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

