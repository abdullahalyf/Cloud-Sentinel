import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Link, useNavigate } from 'react-router-dom';
import { Check, Circle, Loader2, Play, RotateCcw, Square, X, AlertTriangle, Minus, Maximize2, GripHorizontal } from 'lucide-react';
import { api, ApiError } from '../api/client';
import { DEMO_STEPS, resetDemo, runDemo, type StepStatus } from '../utils/demo';
import { clampPanel, dragTo, type PanelPos } from '../utils/panelDrag';

interface Props {
  onClose: () => void;
}

const idle = (): { status: StepStatus; detail?: string }[] => DEMO_STEPS.map(() => ({ status: 'waiting' }));

const TONE: Record<StepStatus, { fg: string; bg: string; label: string }> = {
  waiting: { fg: 'var(--color-text-muted)', bg: 'var(--color-fill)', label: 'Waiting' },
  running: { fg: 'var(--color-accent-text)', bg: 'rgba(117, 72, 231, 0.12)', label: 'Running' },
  done: { fg: 'var(--color-state-healthy)', bg: 'var(--color-state-healthy-bg)', label: 'Done' },
  failed: { fg: 'var(--color-state-killed)', bg: 'var(--color-state-killed-bg)', label: 'Failed' },
};

/** The scripted "3 AM incident". Rendered in a portal so nothing on the page can sit on top of it. */
export const DemoPanel: React.FC<Props> = ({ onClose }) => {
  const navigate = useNavigate();
  const [steps, setSteps] = useState(idle);
  const [running, setRunning] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [note, setNote] = useState<{ tone: 'ok' | 'bad'; text: string } | null>(null);
  const abort = useRef<AbortController | null>(null);

  // The panel floats over the page the demo is driving, so it can be dragged out of the way or minimized.
  const panel = useRef<HTMLDivElement>(null);
  const drag = useRef<{ start: PanelPos; x: number; y: number } | null>(null);
  const [pos, setPos] = useState<PanelPos>({ left: 264, top: 72 });
  const [minimized, setMinimized] = useState(false);
  const [dragging, setDragging] = useState(false);

  const place = (p: PanelPos) => {
    const r = panel.current?.getBoundingClientRect();
    setPos(clampPanel(p, { w: r?.width ?? 440, h: r?.height ?? 120 }, { w: window.innerWidth, h: window.innerHeight }));
  };
  const onDragStart = (e: React.PointerEvent<HTMLDivElement>) => {
    if ((e.target as HTMLElement).closest('button')) return; // the header buttons stay clickable
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = { start: pos, x: e.clientX, y: e.clientY };
    setDragging(true);
  };
  const onDragMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (drag.current) place(dragTo(drag.current.start, { x: drag.current.x, y: drag.current.y }, { x: e.clientX, y: e.clientY }));
  };
  const onDragEnd = () => {
    drag.current = null;
    setDragging(false);
  };
  const onHeaderKey = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const step = e.shiftKey ? 80 : 24;
    const d: Record<string, [number, number]> = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
    const m = d[e.key];
    if (!m) return;
    e.preventDefault();
    place({ left: pos.left + m[0], top: pos.top + m[1] });
  };
  // keep it on screen if the window shrinks or the panel changes size (minimize / expand)
  useEffect(() => {
    const fit = () => place(pos);
    fit();
    window.addEventListener('resize', fit);
    return () => window.removeEventListener('resize', fit);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [minimized]);

  // Esc closes the panel (the run keeps going in the background only if it was started)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const start = async () => {
    abort.current = new AbortController();
    setSteps(idle());
    setNote(null);
    setRunning(true);
    const ok = await runDemo({
      api,
      navigate,
      signal: abort.current.signal,
      onStatus: (i, status, detail) => setSteps((prev) => prev.map((s, k) => (k === i ? { status, detail } : s))),
    });
    setRunning(false);
    if (ok) setNote({ tone: 'ok', text: 'Demo finished. Every step waited for the real API state.' });
  };

  const stop = () => {
    abort.current?.abort();
    setNote({ tone: 'bad', text: 'Stopped. Press Reset demo before running it again.' });
  };

  const reset = async () => {
    setNote(null);
    setResetting(true);
    try {
      await resetDemo(api);
      setSteps(idle());
      setNote({ tone: 'ok', text: 'Demo reset: killed agents restarted, paused agents resumed, memory cleared.' });
    } catch (e) {
      setNote({ tone: 'bad', text: `Reset failed: ${e instanceof ApiError ? e.detail : e instanceof Error ? e.message : 'unknown error'}` });
    } finally {
      setResetting(false);
    }
  };

  const doneCount = steps.filter((s) => s.status === 'done').length;

  return createPortal(
    <div
      ref={panel}
      role="dialog"
      aria-label="Run the 3 AM incident"
      className="pop-in"
      data-minimized={minimized}
      style={{
        position: 'fixed',
        top: pos.top,
        left: pos.left,
        width: minimized ? 320 : 440,
        maxWidth: 'calc(100vw - 32px)',
        zIndex: 1000,
        padding: minimized ? '12px 16px' : '20px 22px 22px',
        background: 'var(--color-surface)',
        borderRadius: 20,
        boxShadow: 'var(--shadow-pop), var(--ring)',
        display: 'flex',
        flexDirection: 'column',
        gap: minimized ? 10 : 14,
        color: 'var(--color-text-primary)',
      }}
    >
      <div
        data-testid="demo-drag-handle"
        tabIndex={0}
        role="group"
        aria-label="Demo panel header. Drag, or use the arrow keys, to move the panel"
        title="Drag to move"
        onPointerDown={onDragStart}
        onPointerMove={onDragMove}
        onPointerUp={onDragEnd}
        onPointerCancel={onDragEnd}
        onKeyDown={onHeaderKey}
        style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, cursor: dragging ? 'grabbing' : 'grab', touchAction: 'none', userSelect: 'none' }}
      >
        <div style={{ minWidth: 0 }}>
          <h2 className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <GripHorizontal size={15} color="var(--color-text-muted)" aria-hidden />
            Run the 3 AM incident
          </h2>
          <p className="card-sub">
            {minimized ? `${doneCount} of ${DEMO_STEPS.length} steps done` : `${doneCount} of ${DEMO_STEPS.length} steps done · every step waits for the real API state`}
          </p>
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          <button type="button" className="corner-btn" aria-label={minimized ? 'Expand demo panel' : 'Minimize demo panel'} aria-expanded={!minimized} onClick={() => setMinimized((m) => !m)}>
            {minimized ? <Maximize2 size={14} /> : <Minus size={15} />}
          </button>
          <button type="button" className="corner-btn" aria-label="Close demo panel" onClick={onClose}>
            <X size={15} />
          </button>
        </div>
      </div>

      <div style={{ height: 4, borderRadius: 2, background: 'var(--color-fill)', overflow: 'hidden' }}>
        <div className="meter-fill" style={{ height: '100%', width: `${(doneCount / DEMO_STEPS.length) * 100}%`, background: 'var(--accent-gradient)' }} />
      </div>

      {!minimized && (<>
      <ol style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 4 }}>
        {DEMO_STEPS.map((step, i) => {
          const s = steps[i];
          const tone = TONE[s.status];
          const Icon = s.status === 'done' ? Check : s.status === 'running' ? Loader2 : s.status === 'failed' ? AlertTriangle : Circle;
          return (
            <li
              key={step.id}
              data-testid={`demo-step-${step.id}`}
              data-status={s.status}
              style={{
                display: 'grid',
                gridTemplateColumns: '20px 1fr auto',
                gap: 10,
                alignItems: 'start',
                padding: '8px 10px',
                borderRadius: 12,
                background: s.status === 'running' ? 'rgba(117, 72, 231, 0.06)' : 'transparent',
              }}
            >
              <Icon size={16} color={tone.fg} style={{ marginTop: 2 }} className={s.status === 'running' ? 'spin' : undefined} />
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 13.5, fontWeight: 600, color: s.status === 'waiting' ? 'var(--color-text-secondary)' : 'var(--color-text-primary)' }}>
                  {i + 1}. {step.label}
                </div>
                {step.human && s.status === 'running' && (
                  <div style={{ fontSize: 12.5, marginTop: 2 }}>
                    <Link to="/agents/beta" style={{ color: 'var(--color-accent-text)', fontWeight: 700 }}>
                      Open beta →
                    </Link>
                    <span className="muted"> waiting for you</span>
                  </div>
                )}
                {s.detail && <div style={{ fontSize: 12, color: tone.fg, marginTop: 2 }}>{s.detail}</div>}
              </div>
              <span className="chip" style={{ background: tone.bg, color: tone.fg, fontSize: 11 }}>
                {tone.label}
              </span>
            </li>
          );
        })}
      </ol>

      {note && (
        <div
          role="status"
          style={{
            fontSize: 12.5,
            padding: '8px 12px',
            borderRadius: 10,
            background: note.tone === 'ok' ? 'var(--color-state-healthy-bg)' : 'var(--color-state-killed-bg)',
            color: note.tone === 'ok' ? 'var(--color-state-healthy)' : 'var(--color-state-killed)',
          }}
        >
          {note.text}
        </div>
      )}

      <div style={{ display: 'flex', gap: 8 }}>
        {running ? (
          <button type="button" className="btn" aria-label="Stop demo" onClick={stop}>
            <Square size={13} /> Stop
          </button>
        ) : (
          <button type="button" className="btn-primary" aria-label="Start demo" onClick={start} disabled={resetting}>
            <Play size={13} fill="currentColor" /> Start
          </button>
        )}
        <button type="button" className="btn" aria-label="Reset demo" disabled={running || resetting} onClick={reset}>
          <RotateCcw size={13} className={resetting ? 'spin' : undefined} /> {resetting ? 'Resetting…' : 'Reset demo'}
        </button>
      </div>
      </>)}
    </div>,
    document.body
  );
};
