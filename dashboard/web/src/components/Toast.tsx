import React, { createContext, useContext, useState, useCallback } from 'react';
import { CheckCircle2, AlertCircle, Info, X } from 'lucide-react';

export type ToastType = 'success' | 'error' | 'info';

export interface ToastMessage {
  id: string;
  type: ToastType;
  title: string;
  detail?: string;
}

interface ToastContextValue {
  showToast: (type: ToastType, title: string, detail?: string) => void;
  success: (title: string, detail?: string) => void;
  error: (title: string, detail?: string) => void;
  info: (title: string, detail?: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export const useToast = (): ToastContextValue => {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error('useToast must be used within a ToastProvider');
  }
  return ctx;
};

export const ToastProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const showToast = useCallback(
    (type: ToastType, title: string, detail?: string) => {
      const id = `${Date.now()}-${Math.random().toString(36).substring(2, 7)}`;
      const toast: ToastMessage = { id, type, title, detail };
      setToasts((prev) => [...prev, toast]);

      setTimeout(() => {
        removeToast(id);
      }, 5000);
    },
    [removeToast]
  );

  const success = useCallback((title: string, detail?: string) => showToast('success', title, detail), [showToast]);
  const error = useCallback((title: string, detail?: string) => showToast('error', title, detail), [showToast]);
  const info = useCallback((title: string, detail?: string) => showToast('info', title, detail), [showToast]);

  return (
    <ToastContext.Provider value={{ showToast, success, error, info }}>
      {children}
      {/* Toast container floating top-right */}
      <div
        aria-live="polite"
        data-testid="toast-container"
        style={{
          position: 'fixed',
          top: 'var(--space-6)',
          right: 'var(--space-6)',
          zIndex: 100000,
          display: 'flex',
          flexDirection: 'column',
          gap: 'var(--space-2)',
          maxWidth: '420px',
          width: 'calc(100% - 32px)',
          pointerEvents: 'none',
        }}
      >
        {toasts.map((t) => {
          const color =
            t.type === 'success'
              ? 'var(--color-state-healthy)'
              : t.type === 'error'
              ? 'var(--color-state-killed)'
              : 'var(--color-telemetry-cyan)';
          const border =
            t.type === 'success'
              ? 'var(--color-state-healthy-border)'
              : t.type === 'error'
              ? 'var(--color-state-killed-border)'
              : 'var(--color-border-accent)';

          return (
            <div
              key={t.id}
              role="status"
              data-testid={`toast-${t.type}`}
              style={{
                pointerEvents: 'auto',
                display: 'flex',
                alignItems: 'flex-start',
                gap: 'var(--space-3)',
                padding: 'var(--space-3) var(--space-4)',
                backgroundColor: 'var(--color-surface-elevated)',
                border: `1px solid ${border}`,
                borderLeft: `4px solid ${color}`,
                borderRadius: 'var(--radius-sm)',
                boxShadow: '0 8px 24px rgba(0, 0, 0, 0.6)',
                backdropFilter: 'blur(8px)',
                animation: 'toastIn 0.2s cubic-bezier(0, 0, 0.2, 1)',
              }}
            >
              <div style={{ color, marginTop: '2px', flexShrink: 0 }}>
                {t.type === 'success' && <CheckCircle2 size={18} />}
                {t.type === 'error' && <AlertCircle size={18} />}
                {t.type === 'info' && <Info size={18} />}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div
                  style={{
                    fontSize: 'var(--type-body-sm-size)',
                    fontWeight: 600,
                    color: 'var(--color-text-primary)',
                  }}
                >
                  {t.title}
                </div>
                {t.detail && (
                  <div
                    style={{
                      fontSize: 'var(--type-micro-size)',
                      color: 'var(--color-text-secondary)',
                      marginTop: '2px',
                      wordBreak: 'break-word',
                      fontFamily: 'var(--font-mono)',
                    }}
                  >
                    {t.detail}
                  </div>
                )}
              </div>
              <button
                type="button"
                aria-label="Dismiss toast"
                onClick={() => removeToast(t.id)}
                style={{
                  color: 'var(--color-text-muted)',
                  cursor: 'pointer',
                  padding: '2px',
                  lineHeight: 1,
                  background: 'none',
                  border: 'none',
                }}
              >
                <X size={14} />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
};
