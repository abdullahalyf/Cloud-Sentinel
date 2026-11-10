import React, { useState } from 'react';
import { NavLink } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { LayoutDashboard, Cpu, ShieldAlert, Activity, DollarSign, Network, ShieldCheck, PanelLeft, Play } from 'lucide-react';
import { api } from '../api/client';
import { livePoll } from '../utils/live';
import { DemoPanel } from './DemoPanel';
import { ProgressRing } from './ui';

export const LeftNav: React.FC = () => {
  const [collapsed, setCollapsed] = useState(false);
  const [demoOpen, setDemoOpen] = useState(false);

  const { data: pendingCalls } = useQuery({ queryKey: ['tool-calls', 'pending'], queryFn: () => api.getToolCalls('pending'), refetchInterval: livePoll });
  const { data: pendingHeals } = useQuery({ queryKey: ['heal-proposals', 'pending'], queryFn: () => api.getHealProposals('pending'), refetchInterval: livePoll });
  const { data: health } = useQuery({ queryKey: ['health'], queryFn: api.getHealth, refetchInterval: livePoll });
  const { data: fleet } = useQuery({ queryKey: ['fleet'], queryFn: api.getFleet, refetchInterval: livePoll });

  const pendingCount = (pendingCalls?.items?.length || 0) + (pendingHeals?.items?.length || 0);
  const isDemo = health?.mode === 'fake' || health?.mode === 'mock' || import.meta.env.VITE_DEMO === '1';
  const agents = fleet?.agents ?? [];
  const spend = agents.reduce((s, a) => s + a.spend_usd, 0);
  const budget = agents.reduce((s, a) => s + a.budget_usd, 0);
  const halted = agents.filter((a) => a.state === 'paused' || a.state === 'killed').length;

  const sections: { title: string; items: { to: string; label: string; icon: React.ReactNode; badge?: number }[] }[] = [
    {
      title: 'Operate',
      items: [
        { to: '/fleet', label: 'Fleet Overview', icon: <LayoutDashboard size={18} /> },
        { to: '/agents/beta', label: 'Agent Details', icon: <Cpu size={18} /> },
        { to: '/approvals', label: 'Approvals Inbox', icon: <ShieldAlert size={18} />, badge: pendingCount > 0 ? pendingCount : undefined },
        { to: '/incidents', label: 'Incidents Replay', icon: <Activity size={18} /> },
      ],
    },
    {
      title: 'Money & proof',
      items: [
        { to: '/cost', label: 'Cost & ROI', icon: <DollarSign size={18} /> },
        { to: '/graph', label: 'Fleet Graph', icon: <Network size={18} /> },
      ],
    },
  ];

  return (
    <nav role="navigation" aria-label="Main Navigation" className={`sb ${collapsed ? 'collapsed' : ''}`}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '0 4px 10px' }}>
        <span style={{ width: 38, height: 38, borderRadius: 12, background: 'var(--accent-gradient)', color: '#fff', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, boxShadow: '0 8px 18px -8px rgba(117,72,231,0.9)' }}>
          <ShieldCheck size={20} />
        </span>
        <div className="sb-hide" style={{ minWidth: 0, flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <strong style={{ fontSize: 17, fontWeight: 700, letterSpacing: '-0.02em' }}>CloudSentinel</strong>
            <span className="count-badge" style={{ height: 18, fontSize: 10 }}>v2</span>
          </div>
          <div style={{ fontSize: 11.5, color: 'var(--color-text-muted)' }}>Agent control tower</div>
        </div>
        <button type="button" className="corner-btn sb-hide" aria-label="Collapse sidebar" onClick={() => setCollapsed(true)} style={{ borderRadius: 10 }}>
          <PanelLeft size={15} />
        </button>
      </div>
      {collapsed && (
        <button type="button" className="corner-btn" aria-label="Expand sidebar" onClick={() => setCollapsed(false)} style={{ borderRadius: 10, alignSelf: 'center', marginBottom: 6 }}>
          <PanelLeft size={15} />
        </button>
      )}

      {isDemo && (
        <button type="button" className="btn" aria-label="Run 3 AM Demo Incident" aria-expanded={demoOpen} onClick={() => setDemoOpen((o) => !o)} style={{ height: 44, borderRadius: 14, justifyContent: collapsed ? 'center' : 'flex-start' }}>
          <Play size={15} color="var(--color-accent)" fill="var(--color-accent)" />
          <span className="sb-hide" style={{ flex: 1, textAlign: 'left' }}>Run the 3 AM demo</span>
          <span className="kbd sb-hide">Demo</span>
        </button>
      )}

      {sections.map((sec) => (
        <div key={sec.title} style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <div className="sb-section sb-hide">{sec.title}</div>
          {sec.items.map((it) => (
            <NavLink key={it.to} to={it.to} aria-label={it.label} title={collapsed ? it.label : undefined} className={({ isActive }) => `sb-item ${isActive ? 'active' : ''}`} style={{ justifyContent: collapsed ? 'center' : undefined }}>
              {it.icon}
              <span className="sb-hide" style={{ flex: 1 }}>{it.label}</span>
              {it.badge !== undefined && <span className="count-badge sb-hide">{it.badge}</span>}
            </NavLink>
          ))}
        </div>
      ))}

      <div style={{ flex: 1 }} />

      <div className="card sb-hide" style={{ display: 'flex', alignItems: 'center', gap: 12, padding: 12, borderRadius: 16 }}>
        <ProgressRing value={budget > 0 ? spend / budget : 0} label="Fleet budget used" />
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>Fleet budget used</div>
          <div style={{ fontSize: 15, fontWeight: 700 }}>${spend.toFixed(2)}</div>
          <div style={{ fontSize: 11.5, color: 'var(--color-text-muted)' }}>
            of ${budget.toFixed(2)} · {halted} halted
          </div>
        </div>
      </div>

      {demoOpen && isDemo && <DemoPanel onClose={() => setDemoOpen(false)} />}
    </nav>
  );
};
