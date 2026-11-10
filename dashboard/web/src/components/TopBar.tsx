import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Bell, Search, ChevronDown } from 'lucide-react';
import { api } from '../api/client';
import { livePoll } from '../utils/live';

const PAGES = [
  { label: 'Fleet Overview', to: '/fleet' },
  { label: 'Approvals Inbox', to: '/approvals' },
  { label: 'Incidents Replay', to: '/incidents' },
  { label: 'Cost & ROI', to: '/cost' },
  { label: 'Fleet Graph', to: '/graph' },
];

export function searchItems(q: string, agentIds: string[]): { label: string; to: string; kind: 'agent' | 'page' }[] {
  const s = q.trim().toLowerCase();
  if (!s) return [];
  return [
    ...agentIds.filter((id) => id.toLowerCase().includes(s)).map((id) => ({ label: id, to: `/agents/${id}`, kind: 'agent' as const })),
    ...PAGES.filter((p) => p.label.toLowerCase().includes(s)).map((p) => ({ ...p, kind: 'page' as const })),
  ].slice(0, 8);
}

export const TopBar: React.FC = () => {
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const [q, setQ] = useState('');
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);

  const { data: health } = useQuery({ queryKey: ['health'], queryFn: api.getHealth, refetchInterval: livePoll });
  const { data: fleet } = useQuery({ queryKey: ['fleet'], queryFn: api.getFleet, refetchInterval: livePoll });
  const { data: pendingCalls } = useQuery({ queryKey: ['tool-calls', 'pending'], queryFn: () => api.getToolCalls('pending'), refetchInterval: livePoll });
  const { data: pendingHeals } = useQuery({ queryKey: ['heal-proposals', 'pending'], queryFn: () => api.getHealProposals('pending'), refetchInterval: livePoll });
  const pending = (pendingCalls?.items?.length || 0) + (pendingHeals?.items?.length || 0);

  const results = useMemo(() => searchItems(q, (fleet?.agents ?? []).map((a) => a.agent_id)), [q, fleet]);
  const isMac = typeof navigator !== 'undefined' && /Mac/i.test(navigator.platform);

  // Ctrl/⌘ K focuses the search
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        inputRef.current?.focus();
        setOpen(true);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const go = (to: string) => {
    navigate(to);
    setQ('');
    setOpen(false);
    inputRef.current?.blur();
  };

  const today = new Date().toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' });
  const ok = health?.ok !== false && !!health;

  return (
    <header role="banner" style={{ position: 'sticky', top: 0, zIndex: 15, display: 'flex', alignItems: 'center', gap: 12, padding: '16px 28px 10px', background: 'var(--color-header-glass)', backdropFilter: 'saturate(1.2)' }}>
      <div style={{ position: 'relative', width: 'min(420px, 40vw)' }}>
        <Search size={16} color="var(--color-text-muted)" style={{ position: 'absolute', left: 14, top: 12 }} />
        <input
          ref={inputRef}
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setOpen(true);
            setActive(0);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 120)}
          onKeyDown={(e) => {
            if (e.key === 'ArrowDown') setActive((a) => Math.min(results.length - 1, a + 1));
            else if (e.key === 'ArrowUp') setActive((a) => Math.max(0, a - 1));
            else if (e.key === 'Enter' && results[active]) go(results[active].to);
            else if (e.key === 'Escape') inputRef.current?.blur();
          }}
          placeholder="Search agents and pages"
          aria-label="Search agents and pages"
          style={{ width: '100%', height: 42, padding: '0 64px 0 40px', borderRadius: 14, border: 'none', background: 'var(--color-surface)', boxShadow: 'var(--ring)', fontSize: 13.5, color: 'var(--color-text-primary)', outline: 'none' }}
        />
        <span className="kbd" style={{ position: 'absolute', right: 10, top: 10 }}>{isMac ? '⌘K' : 'Ctrl K'}</span>
        {open && results.length > 0 && (
          <div role="listbox" aria-label="Search results" className="card pop-in" style={{ position: 'absolute', top: 48, left: 0, right: 0, padding: 6, zIndex: 30, boxShadow: 'var(--shadow-pop)' }}>
            {results.map((r, i) => (
              <button
                key={r.to}
                type="button"
                role="option"
                aria-selected={i === active}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => go(r.to)}
                style={{ width: '100%', display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '9px 10px', borderRadius: 10, background: i === active ? 'var(--color-fill)' : 'transparent', fontSize: 13.5, fontWeight: 600, textAlign: 'left' }}
              >
                {r.label}
                <span className="muted" style={{ fontSize: 12 }}>{r.kind === 'agent' ? 'Agent' : 'Page'}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      <div style={{ flex: 1 }} />

      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontSize: 13.5, fontWeight: 600, color: 'var(--color-text-secondary)' }}>
        <span className="pulse-dot" style={{ width: 7, height: 7, borderRadius: '50%', background: ok ? 'var(--color-state-healthy)' : 'var(--color-state-killed)', color: ok ? 'var(--color-state-healthy)' : 'var(--color-state-killed)' }} />
        <span>{today}</span>
      </span>
      {health && (
        <span className="chip" style={{ background: 'var(--color-surface)', boxShadow: 'var(--ring)', color: 'var(--color-text-secondary)' }} title="Brain mode and judge">
          {health.mode} · judge {health.judge}
        </span>
      )}

      <Link to="/approvals" aria-label={`Approvals: ${pending} waiting`} className="corner-btn" style={{ width: 42, height: 42, borderRadius: 13, background: 'var(--color-surface)', boxShadow: 'var(--ring)', position: 'relative' }}>
        <Bell size={17} />
        {pending > 0 && (
          <span style={{ position: 'absolute', top: -4, right: -4, minWidth: 18, height: 18, padding: '0 5px', borderRadius: 9, background: 'var(--color-accent)', color: '#fff', fontSize: 10.5, fontWeight: 700, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 0 0 2px var(--color-canvas)' }}>
            {pending}
          </span>
        )}
      </Link>

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, height: 42, padding: '0 12px 0 6px', borderRadius: 14, background: 'var(--color-surface)', boxShadow: 'var(--ring)' }}>
        <span className="avatar">OP</span>
        <div style={{ lineHeight: 1.15 }}>
          <div style={{ fontSize: 13, fontWeight: 700 }}>Operator</div>
          <div style={{ fontSize: 11.5, color: 'var(--color-text-muted)' }}>dashboard · C2</div>
        </div>
        <ChevronDown size={15} color="var(--color-text-muted)" />
      </div>
    </header>
  );
};
