import React, { useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Check, Circle, Loader2, Play, RotateCcw, Square, X, AlertTriangle } from 'lucide-react';
import { api, ApiError } from '../api/client';
import { DEMO_STEPS, resetDemo, runDemo, type StepStatus } from '../lib/demo';

interface Props {
  onClose: () => void;
}

const idle = (): { status: StepStatus; detail?: string }[] => DEMO_STEPS.map(() => ({ status: 'waiting' }));

const colors: Record<StepStatus, string> = {
  waiting: 'var(--color-text-muted)',
  running: 'var(--color-accent)',
  done: 'var(--color-state-healthy)',
  failed: 'var(--color-state-killed)',
};

export const DemoPanel: React.FC<Props> = ({ onClose }) => {
  const navigate = useNavigate();
  const [steps, setSteps] = useState(idle);
  const [running, setRunning] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);

  const start = async () => {
    abort.current = new AbortController();
    setSteps(idle());
    setNote(null);
    setRunning(true);
    await runDemo({
      api,
      navigate,
      signal: abort.current.signal,
      onStatus: (i, status, detail) =>
        setSteps((prev) => prev.map((s, k) => (k === i ? { status, detail } : s))),
    });
    setRunning(false);
  };

  const stop = () => abort.current?.abort();

  const reset = async () => {
    setNote(null);
    try {
      await resetDemo(api);
      setSteps(idle());
      setNote('Demo reset: killed agents restarted, paused agents resumed, memory cleared.');
    } catch (e) {
      setNote(`Reset failed: ${e instanceof ApiError ? e.detail : e instanceof Error ? e.message : 'unknown error'}`);
    }
  };

  const small: React.CSSProperties = {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 6,
    padding: 'var(--space-1) var(--space-3)',
    borderRadius: 'var(--radius-sm)',
    border: '1px solid var(--color-border)',
    color: 'var(--color-text-primary)',
    fontSize: 'var(--type-micro-size)',
    fontWeight: 600,
  };

  return (
    <div
      role="dialog"
      aria-label="Run the 3 AM incident"
      style={{
        position: 'fixed',
        top: 64,
        right: 16,
        width: 420,
        zIndex: 200,
        padding: 'var(--space-4)',
        background: 'rgba(8, 12, 20, 0.98)',
        border: '1px solid var(--color-border-accent)',
        borderRadius: 'var(--radius-md)',
        boxShadow: '0 16px 48px rgba(0,0,0,0.7)',
        display: 'flex',
        flexDirection: 'column',
        gap: 'var(--space-3)',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <strong style={{ fontSize: 'var(--type-body-size)' }}>Run the 3 AM incident</strong>
        <button type="button" aria-label="Close demo panel" onClick={onClose} style={{ color: 'var(--color-text-muted)' }}>
          <X size={16} />
        </button>
      </div>

      <ol style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
        {DEMO_STEPS.map((step, i) => {
          const s = steps[i];
          const Icon = s.status === 'done' ? Check : s.status === 'running' ? Loader2 : s.status === 'failed' ? AlertTriangle : Circle;
          return (
            <li
              key={step.id}
              data-testid={`demo-step-${step.id}`}
              data-status={s.status}
              style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'flex-start', fontSize: 'var(--type-body-sm-size)' }}
            >
              <Icon size={15} color={colors[s.status]} style={{ marginTop: 3, flexShrink: 0 }} />
              <div style={{ flex: 1 }}>
                <span style={{ color: s.status === 'waiting' ? 'var(--color-text-secondary)' : 'var(--color-text-primary)' }}>
                  {i + 1}. {step.label}
                </span>
                {step.human && s.status === 'running' && (
                  <div style={{ marginTop: 2 }}>
                    <Link to="/agents/beta" style={{ color: 'var(--color-accent)', fontWeight: 600 }}>
                      Open beta →
                    </Link>
                    <span style={{ color: 'var(--color-text-muted)' }}> waiting for you</span>
                  </div>
                )}
                {s.detail && (
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--type-micro-size)', color: colors[s.status] }}>
                    {s.detail}
                  </div>
                )}
              </div>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--type-micro-size)', color: colors[s.status] }}>
                {s.status}
              </span>
            </li>
          );
        })}
      </ol>

      {note && <div style={{ fontSize: 'var(--type-micro-size)', color: 'var(--color-text-secondary)' }}>{note}</div>}

      <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
        {running ? (
          <button type="button" aria-label="Stop demo" onClick={stop} style={small}>
            <Square size={12} /> Stop
          </button>
        ) : (
          <button
            type="button"
            aria-label="Start demo"
            onClick={start}
            style={{ ...small, background: 'var(--color-accent)', color: 'var(--color-canvas)', border: 'none' }}
          >
            <Play size={12} fill="currentColor" /> Start
          </button>
        )}
        <button type="button" aria-label="Reset demo" disabled={running} onClick={reset} style={small}>
          <RotateCcw size={12} /> Reset demo
        </button>
      </div>
    </div>
  );
};
