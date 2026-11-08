import React, { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ShieldCheck, Play, Cpu, DollarSign } from 'lucide-react';
import { api } from '../api/client';

export const TopBar: React.FC = () => {
  const [timeStr, setTimeStr] = useState<string>('');

  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      setTimeStr(now.toUTCString().split(' ')[4] + ' UTC');
    };
    updateTime();
    const interval = setInterval(updateTime, 1000);
    return () => clearInterval(interval);
  }, []);

  const { data: health } = useQuery({
    queryKey: ['health'],
    queryFn: api.getHealth,
    refetchInterval: 1000,
  });

  const { data: roi } = useQuery({
    queryKey: ['roi'],
    queryFn: api.getRoi,
    refetchInterval: 1000,
  });

  const isDemo =
    health?.mode === 'fake' || health?.mode === 'mock' || import.meta.env.VITE_DEMO === '1';

  return (
    <header
      role="banner"
      style={{
        position: 'sticky',
        top: 0,
        zIndex: 100,
        height: '56px',
        width: '100%',
        backgroundColor: 'var(--color-header-glass)',
        backdropFilter: 'blur(12px)',
        WebkitBackdropFilter: 'blur(12px)',
        borderBottom: '1px solid var(--color-border)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 var(--space-4)',
      }}
    >
      {/* Brand & Wordmark */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: '28px',
            height: '28px',
            borderRadius: 'var(--radius-sm)',
            backgroundColor: 'var(--color-state-healthy-bg)',
            color: 'var(--color-state-healthy)',
          }}
        >
          <ShieldCheck size={18} />
        </div>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 'var(--space-2)' }}>
          <span style={{ fontWeight: 700, fontSize: 'var(--type-body-size)', letterSpacing: '-0.02em' }}>
            CloudSentinel
          </span>
          <span
            className="tabular-nums"
            style={{
              fontSize: 'var(--type-micro-size)',
              color: 'var(--color-text-muted)',
              backgroundColor: 'var(--color-surface-elevated)',
              padding: '1px 6px',
              borderRadius: 'var(--radius-sm)',
            }}
          >
            v2
          </span>
        </div>
      </div>

      {/* Telemetry Center Status */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-4)' }}>
        {/* System Mode */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 'var(--space-2)',
            fontSize: 'var(--type-micro-size)',
            fontFamily: 'var(--font-mono)',
            backgroundColor: 'var(--color-surface)',
            border: '1px solid var(--color-border)',
            padding: 'var(--space-1) var(--space-3)',
            borderRadius: 'var(--radius-sm)',
          }}
        >
          <span
            style={{
              width: '6px',
              height: '6px',
              borderRadius: '50%',
              backgroundColor: 'var(--color-state-healthy)',
            }}
          />
          <span style={{ color: 'var(--color-text-muted)', textTransform: 'uppercase' }}>Mode:</span>
          <span style={{ color: 'var(--color-text-primary)', fontWeight: 600 }}>
            {health?.mode || 'connecting...'}
          </span>
        </div>

        {/* Judge Engine */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 'var(--space-2)',
            fontSize: 'var(--type-micro-size)',
            fontFamily: 'var(--font-mono)',
            backgroundColor: 'var(--color-surface)',
            border: '1px solid var(--color-border)',
            padding: 'var(--space-1) var(--space-3)',
            borderRadius: 'var(--radius-sm)',
          }}
        >
          <Cpu size={12} color="var(--color-telemetry-cyan)" />
          <span style={{ color: 'var(--color-text-muted)', textTransform: 'uppercase' }}>Judge:</span>
          <span style={{ color: 'var(--color-text-primary)', fontWeight: 600 }}>
            {health?.judge || '...'}
          </span>
        </div>

        {/* Hero $ Saved Chip */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 'var(--space-1)',
            fontSize: 'var(--type-body-sm-size)',
            fontFamily: 'var(--font-mono)',
            backgroundColor: 'var(--color-state-healthy-bg)',
            border: '1px solid var(--color-state-healthy-border)',
            padding: 'var(--space-1) var(--space-3)',
            borderRadius: 'var(--radius-sm)',
            color: 'var(--color-state-healthy)',
            fontWeight: 700,
          }}
        >
          <DollarSign size={14} />
          <span>Saved:</span>
          <span className="tabular-nums">
            ${(roi?.saved_usd || 0).toFixed(4)}
          </span>
        </div>
      </div>

      {/* Right Controls: Demo Button & Clock */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
        {isDemo && (
          <button
            type="button"
            aria-label="Run 3 AM Demo Incident"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 'var(--space-1)',
              padding: 'var(--space-1) var(--space-3)',
              backgroundColor: 'var(--color-accent)',
              color: 'var(--color-canvas)',
              fontSize: 'var(--type-micro-size)',
              fontWeight: 700,
              borderRadius: 'var(--radius-sm)',
              textTransform: 'uppercase',
              letterSpacing: '0.05em',
            }}
          >
            <Play size={12} fill="currentColor" />
            Demo Mode
          </button>
        )}

        <div
          className="tabular-nums"
          aria-label="Current UTC Time"
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 'var(--type-micro-size)',
            color: 'var(--color-text-muted)',
            backgroundColor: 'var(--color-surface)',
            border: '1px solid var(--color-border)',
            padding: 'var(--space-1) var(--space-3)',
            borderRadius: 'var(--radius-sm)',
          }}
        >
          {timeStr || '00:00:00 UTC'}
        </div>
      </div>
    </header>
  );
};
