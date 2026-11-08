import { livePoll } from '../lib/live';
import React from 'react';
import { NavLink } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { LayoutDashboard, Cpu, ShieldAlert, Activity, DollarSign } from 'lucide-react';
import { api } from '../api/client';

export const LeftNav: React.FC = () => {
  const { data: pendingCalls } = useQuery({
    queryKey: ['tool-calls', 'pending'],
    queryFn: () => api.getToolCalls('pending'),
    refetchInterval: livePoll,
  });

  const { data: pendingHeals } = useQuery({
    queryKey: ['heal-proposals', 'pending'],
    queryFn: () => api.getHealProposals('pending'),
    refetchInterval: livePoll,
  });

  const pendingCount = (pendingCalls?.items?.length || 0) + (pendingHeals?.items?.length || 0);

  const navItems = [
    { to: '/fleet', label: 'Fleet Overview', icon: <LayoutDashboard size={18} /> },
    { to: '/agents/beta', label: 'Agent Details', icon: <Cpu size={18} /> },
    {
      to: '/approvals',
      label: 'Approvals Inbox',
      icon: <ShieldAlert size={18} />,
      badge: pendingCount > 0 ? pendingCount : undefined,
    },
    { to: '/incidents', label: 'Incidents Replay', icon: <Activity size={18} /> },
    { to: '/cost', label: 'Cost & ROI', icon: <DollarSign size={18} /> },
  ];

  return (
    <nav
      role="navigation"
      aria-label="Main Navigation"
      style={{
        width: '240px',
        flexShrink: 0,
        backgroundColor: 'var(--color-surface)',
        borderRight: '1px solid var(--color-border)',
        padding: 'var(--space-4) 0',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        height: 'calc(100vh - 56px)',
        position: 'sticky',
        top: '56px',
      }}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-1)', padding: '0 var(--space-3)' }}>
        <div
          style={{
            fontSize: 'var(--type-micro-size)',
            fontFamily: 'var(--font-mono)',
            textTransform: 'uppercase',
            color: 'var(--color-text-muted)',
            padding: 'var(--space-2) var(--space-3)',
            letterSpacing: '0.05em',
          }}
        >
          Operations
        </div>

        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            style={({ isActive }) => ({
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: 'var(--space-2) var(--space-3)',
              borderRadius: 'var(--radius-sm)',
              fontSize: 'var(--type-body-sm-size)',
              fontWeight: isActive ? 600 : 500,
              color: isActive ? 'var(--color-text-primary)' : 'var(--color-text-secondary)',
              backgroundColor: isActive ? 'var(--color-surface-elevated)' : 'transparent',
              borderLeft: isActive ? '3px solid var(--color-accent)' : '3px solid transparent',
              transition: 'all var(--transition-fast)',
            })}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
              {item.icon}
              <span>{item.label}</span>
            </div>

            {item.badge !== undefined && (
              <span
                className="tabular-nums"
                aria-label={`${item.badge} pending approvals`}
                style={{
                  fontSize: 'var(--type-micro-size)',
                  fontWeight: 700,
                  backgroundColor: 'var(--color-accent)',
                  color: 'var(--color-canvas)',
                  padding: '1px 6px',
                  borderRadius: '10px',
                  minWidth: '18px',
                  textAlign: 'center',
                }}
              >
                {item.badge}
              </span>
            )}
          </NavLink>
        ))}
      </div>

      {/* Footer Info */}
      <div
        style={{
          padding: 'var(--space-3) var(--space-4)',
          borderTop: '1px solid var(--color-border)',
          fontSize: 'var(--type-micro-size)',
          color: 'var(--color-text-muted)',
        }}
      >
        <div>Mission Control Tower</div>
        <div style={{ marginTop: 'var(--space-1)' }}>C2 API: Port 8000</div>
      </div>
    </nav>
  );
};
