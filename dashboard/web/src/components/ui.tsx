import React from 'react';
import { Link } from 'react-router-dom';
import { ArrowUpRight } from 'lucide-react';
import { MiniSpark } from './charts';

/** Shared layout pieces: page header, card header, segmented control, tabs, KPI cards, rings. */

/** A card that is a link when it has somewhere to go, and a plain region when it does not. */
const Wrap: React.FC<{ to?: string; label: string; className?: string; testId?: string; style?: React.CSSProperties; children: React.ReactNode }> = ({
  to,
  label,
  className,
  testId,
  style,
  children,
}) =>
  to ? (
    <Link to={to} aria-label={label} data-testid={testId} className={className} style={style}>
      {children}
    </Link>
  ) : (
    <section aria-label={label} data-testid={testId} className={className} style={style}>
      {children}
    </section>
  );

export function greeting(d = new Date()): string {
  const h = d.getHours();
  return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
}

export const PageHeader: React.FC<{
  eyebrow?: React.ReactNode;
  title: React.ReactNode;
  summary?: React.ReactNode;
  actions?: React.ReactNode;
  children?: React.ReactNode; // tabs
}> = ({ eyebrow, title, summary, actions, children }) => (
  <header style={{ paddingTop: 18 }}>
    <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap' }}>
      <div style={{ minWidth: 0 }}>
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        {summary && <p className="page-summary">{summary}</p>}
      </div>
      {actions && <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>{actions}</div>}
    </div>
    {children}
  </header>
);

export const CardHeader: React.FC<{
  title: React.ReactNode;
  sub?: React.ReactNode;
  to?: string;
  toLabel?: string;
  right?: React.ReactNode;
}> = ({ title, sub, to, toLabel, right }) => (
  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, marginBottom: 16 }}>
    <div style={{ minWidth: 0 }}>
      <h2 className="card-title">{title}</h2>
      {sub && <p className="card-sub">{sub}</p>}
    </div>
    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
      {right}
      {to && (
        <Link to={to} className="corner-btn" aria-label={toLabel ?? 'Open'}>
          <ArrowUpRight size={15} />
        </Link>
      )}
    </div>
  </div>
);

export function Segmented<T extends string | number>({
  options,
  value,
  onChange,
  label,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={String(o.value)} type="button" aria-pressed={o.value === value} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
  label,
}: {
  tabs: { value: T; label: string; count?: number }[];
  value: T;
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div className="tabs" role="tablist" aria-label={label}>
      {tabs.map((t) => (
        <button key={t.value} type="button" role="tab" aria-selected={t.value === value} onClick={() => onChange(t.value)}>
          {t.label}
          {t.count !== undefined && <span className="count-badge">{t.count}</span>}
        </button>
      ))}
    </div>
  );
}

/** Percent change between the first and last value of a series (null when not meaningful). */
export function deltaPct(series: number[]): number | null {
  if (series.length < 2) return null;
  const a = series[0];
  const b = series[series.length - 1];
  if (!Number.isFinite(a) || !Number.isFinite(b) || a === 0) return null;
  return ((b - a) / Math.abs(a)) * 100;
}

export const Delta: React.FC<{ pct: number | null; goodWhenUp?: boolean }> = ({ pct, goodWhenUp = true }) => {
  if (pct === null) return null;
  const up = pct >= 0;
  const good = up === goodWhenUp;
  return (
    <span className={`delta ${good ? 'up' : 'down'}`} title="Change across the samples on screen">
      {up ? '↑' : '↓'} {Math.abs(pct).toFixed(1)}%
    </span>
  );
};

export const KpiCard: React.FC<{
  label: string;
  icon: React.ReactNode;
  value: React.ReactNode;
  spark?: number[];
  delta?: number | null;
  goodWhenUp?: boolean;
  foot?: React.ReactNode;
  to?: string;
  testId?: string;
}> = ({ label, icon, value, spark, delta = null, goodWhenUp, foot, to, testId }) => (
  <Wrap to={to} label={label} className={`card card-pad ${to ? 'card-hover' : ''}`} testId={testId} style={{ display: 'flex', flexDirection: 'column', gap: 10, minWidth: 0 }}>
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <span style={{ color: 'var(--color-accent-text)', display: 'inline-flex' }}>{icon}</span>
      <span className="kpi-label">{label}</span>
    </div>
    <div className="kpi-value">{value}</div>
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 'auto' }}>
      <Delta pct={delta} goodWhenUp={goodWhenUp} />
      {foot}
      {spark && spark.length > 1 && (
        <div style={{ flex: 1, minWidth: 0 }}>
          <MiniSpark data={spark} color="var(--chart-violet)" id={`kpi-${label.replace(/\W/g, '')}`} height={26} />
        </div>
      )}
    </div>
  </Wrap>
);

/** The solid accent card (the one number that matters most). */
export const HeroCard: React.FC<{
  label: string;
  icon: React.ReactNode;
  value: React.ReactNode;
  foot: React.ReactNode;
  progress?: number; // 0..1
  to?: string;
  testId?: string;
}> = ({ label, icon, value, foot, progress, to, testId }) => (
  <Wrap
    to={to}
    label={label}
    testId={testId}
    className={to ? 'card-hover' : ''}
    style={{
      background: 'var(--accent-gradient)',
      color: '#fff',
      borderRadius: 'var(--radius-lg)',
      padding: '20px 22px 22px',
      boxShadow: '0 22px 40px -22px rgba(117, 72, 231, 0.95)',
      display: 'flex',
      flexDirection: 'column',
      gap: 10,
      minWidth: 0,
    }}
  >
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13.5, fontWeight: 600 }}>
      {icon}
      {label}
    </div>
    <div style={{ fontSize: 32, lineHeight: 1.1, fontWeight: 600, letterSpacing: '-0.02em' }}>{value}</div>
    <div style={{ fontSize: 12.5, fontWeight: 600, opacity: 0.92 }}>{foot}</div>
    {progress !== undefined && (
      <div style={{ height: 4, borderRadius: 2, background: 'rgba(255,255,255,0.28)', overflow: 'hidden', marginTop: 4 }}>
        <div className="meter-fill" style={{ width: `${Math.max(0, Math.min(1, progress)) * 100}%`, height: '100%', background: '#fff', borderRadius: 2 }} />
      </div>
    )}
  </Wrap>
);

export const ProgressRing: React.FC<{ value: number; size?: number; stroke?: number; label?: string }> = ({
  value,
  size = 46,
  stroke = 4,
  label,
}) => {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const v = Math.max(0, Math.min(1, value));
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={label ?? `${Math.round(v * 100)} percent`}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--color-fill-strong)" strokeWidth={stroke} />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        stroke="var(--color-accent)"
        strokeWidth={stroke}
        strokeLinecap="round"
        strokeDasharray={`${v * c} ${c}`}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
        style={{ transition: 'stroke-dasharray 600ms ease' }}
      />
      <text x="50%" y="54%" textAnchor="middle" dominantBaseline="middle" fontSize={11} fontWeight={700} fill="var(--color-text-primary)">
        {Math.round(v * 100)}%
      </text>
    </svg>
  );
};

/** "35 min ago" style relative time. */
export function ago(iso: string | number | undefined, now = Date.now()): string {
  if (iso === undefined || iso === '') return '';
  const t = typeof iso === 'number' ? (iso > 1e11 ? iso : iso * 1000) : new Date(iso).getTime();
  if (!Number.isFinite(t)) return '';
  const s = Math.max(0, Math.round((now - t) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}
