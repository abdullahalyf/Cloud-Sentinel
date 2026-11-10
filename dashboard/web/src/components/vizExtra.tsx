import React, { useState } from 'react';
import { TooltipCard, useBoxWidth } from './viz';

/** Lollipop chart with a dashed limit line, tick gauge, heatmap, and stage bars. Plain SVG. */

/* ───────── Lollipop ───────── */

export interface LollipopPoint {
  label: string;
  value: number;
}

export function downsample(values: number[], labels: string[], buckets: number): LollipopPoint[] {
  if (values.length <= buckets) return values.map((v, i) => ({ value: v, label: labels[i] ?? '' }));
  const out: LollipopPoint[] = [];
  const size = values.length / buckets;
  for (let b = 0; b < buckets; b++) {
    const from = Math.floor(b * size);
    const to = Math.max(from + 1, Math.floor((b + 1) * size));
    const slice = values.slice(from, to);
    out.push({ value: slice.reduce((s, v) => s + v, 0) / slice.length, label: labels[to - 1] ?? '' });
  }
  return out;
}

interface LollipopProps {
  points: LollipopPoint[];
  limit?: number | null;
  format: (v: number) => string;
  limitLabel?: (v: number) => string;
  height?: number;
  testId?: string;
}


export const Lollipop: React.FC<LollipopProps> = ({ points, limit, format, limitLabel, height = 290, testId }) => {
  const [hover, setHover] = useState<number | null>(null);
  const [boxRef, LW] = useBoxWidth(760);
  if (points.length === 0) return <div ref={boxRef} style={{ height }} />;
  const pad = { l: 46, r: 12, t: 14, b: 30 };
  const innerW = LW - pad.l - pad.r;
  const innerH = height - pad.t - pad.b;
  const base = pad.t + innerH;
  const max = Math.max(1e-9, limit ?? 0, ...points.map((p) => p.value)) * 1.15;
  const yAt = (v: number) => base - (v / max) * innerH;
  const slot = innerW / points.length;
  const xAt = (i: number) => pad.l + slot * i + slot / 2;
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * max);
  const last = points.length - 1;

  return (
    <div ref={boxRef} style={{ position: 'relative' }} data-testid={testId}>
      <svg viewBox={`0 0 ${LW} ${height}`} role="img" aria-label="Samples against the limit" style={{ width: '100%', height: 'auto', display: 'block' }} onMouseLeave={() => setHover(null)}>
        <defs>
          <linearGradient id="lp-stem" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" style={{ stopColor: 'var(--chart-violet)' }} />
            <stop offset="100%" style={{ stopColor: 'var(--chart-violet)', stopOpacity: 0.08 }} />
          </linearGradient>
          <linearGradient id="lp-stem-hot" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" style={{ stopColor: 'var(--chart-red)' }} />
            <stop offset="100%" style={{ stopColor: 'var(--chart-red)', stopOpacity: 0.08 }} />
          </linearGradient>
          <linearGradient id="lp-stem-low" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" style={{ stopColor: 'var(--chart-grey)' }} />
            <stop offset="100%" style={{ stopColor: 'var(--chart-grey)', stopOpacity: 0.1 }} />
          </linearGradient>
        </defs>
        {ticks.map((t, i) => (
          <g key={i}>
            <line x1={pad.l} x2={LW - pad.r} y1={yAt(t)} y2={yAt(t)} stroke={i === 0 ? 'rgba(25,18,34,0.2)' : 'rgba(25,18,34,0.06)'} />
            <text x={pad.l - 8} y={yAt(t) + 4} textAnchor="end" fontSize="11" fill="var(--color-text-muted)">
              {format(t)}
            </text>
          </g>
        ))}
        {limit !== undefined && limit !== null && limit > 0 && (
          <g>
            <line x1={pad.l} x2={LW - pad.r} y1={yAt(limit)} y2={yAt(limit)} stroke="var(--chart-red)" strokeDasharray="5 5" strokeOpacity="0.7" />
            <rect x={pad.l - 44} y={yAt(limit) - 10} width={42} height={20} rx={6} fill="var(--chart-red)" />
            <text x={pad.l - 23} y={yAt(limit) + 4} textAnchor="middle" fontSize="10.5" fontWeight="700" fill="#fff">
              {(limitLabel ?? format)(limit)}
            </text>
          </g>
        )}
        {points.map((p, i) => {
          const over = limit !== undefined && limit !== null && limit > 0 && p.value > limit;
          const quiet = p.value <= 0;
          const x = xAt(i);
          const y = yAt(p.value);
          const isNow = i === last;
          return (
            <g key={i} onMouseEnter={() => setHover(i)}>
              <rect x={x - slot / 2} y={pad.t} width={slot} height={innerH} fill="transparent" />
              <rect
                className="stem-rise"
                style={{ animationDelay: `${i * 35}ms` }}
                x={x - 2.5}
                y={y}
                width={5}
                height={Math.max(0, base - y)}
                rx={2.5}
                fill={quiet ? 'url(#lp-stem-low)' : over ? 'url(#lp-stem-hot)' : isNow ? 'url(#lp-stem-low)' : 'url(#lp-stem)'}
              />
              <circle
                className="dot-pop"
                style={{ animationDelay: `${300 + i * 35}ms` }}
                cx={x}
                cy={y}
                r={isNow ? 7 : 6}
                fill={isNow ? '#fff' : over ? 'var(--chart-red)' : 'var(--chart-violet)'}
                stroke={isNow ? 'var(--chart-violet)' : 'var(--color-surface)'}
                strokeWidth={isNow ? 3 : 2}
              />
              <text x={x} y={height - 9} textAnchor="middle" fontSize="11" fontWeight={isNow ? 700 : 500} fill={isNow ? 'var(--color-accent-text)' : 'var(--color-text-muted)'}>
                {p.label}
              </text>
            </g>
          );
        })}
      </svg>
      {hover !== null && (
        <TooltipCard left={`${(xAt(hover) / LW) * 100}%`} top={8} flip={hover > points.length * 0.6}>
          <div style={{ color: 'var(--color-text-muted)' }}>{points[hover].label}</div>
          <div style={{ fontWeight: 700, fontSize: 15 }}>{format(points[hover].value)}</div>
          {limit ? (
            <div style={{ color: points[hover].value > limit ? 'var(--color-state-killed)' : 'var(--color-state-healthy)' }}>
              {points[hover].value > limit ? 'Above the limit' : 'Within the limit'}
            </div>
          ) : null}
        </TooltipCard>
      )}
    </div>
  );
};

/* ───────── Tick gauge (radial ticks) ───────── */

export const TickGauge: React.FC<{ value: number; center: string; caption?: string; size?: number; label: string }> = ({
  value,
  center,
  caption,
  size = 176,
  label,
}) => {
  const ticks = 48;
  const v = Math.max(0, Math.min(1, value));
  const lit = Math.round(v * ticks);
  const c = size / 2;
  const r1 = size / 2 - 6;
  const r2 = r1 - 16;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={label}>
      {Array.from({ length: ticks }, (_, i) => {
        const a = (-90 + (i / ticks) * 360) * (Math.PI / 180);
        const on = i < lit;
        return (
          <line
            key={i}
            className="gauge-tick"
            style={{ animationDelay: `${i * 14}ms` }}
            x1={c + r2 * Math.cos(a)}
            y1={c + r2 * Math.sin(a)}
            x2={c + r1 * Math.cos(a)}
            y2={c + r1 * Math.sin(a)}
            stroke={on ? 'var(--chart-violet)' : 'var(--color-fill-strong)'}
            strokeWidth={3.2}
            strokeLinecap="round"
          />
        );
      })}
      <text x={c} y={c + 4} textAnchor="middle" fontSize="30" fontWeight="600" letterSpacing="-0.02em" fill="var(--color-text-primary)">
        {center}
      </text>
      {caption && (
        <text x={c} y={c + 24} textAnchor="middle" fontSize="11" fill="var(--color-text-muted)">
          {caption}
        </text>
      )}
    </svg>
  );
};

/* ───────── Heatmap ───────── */

export const Heatmap: React.FC<{
  rows: string[];
  cols: string[];
  values: number[][]; // [row][col]
  format: (v: number) => string;
  testId?: string;
}> = ({ rows, cols, values, format, testId }) => {
  const [hover, setHover] = useState<{ r: number; c: number } | null>(null);
  const max = Math.max(1e-9, ...values.flat());
  return (
    <div data-testid={testId} style={{ position: 'relative' }}>
      <div style={{ display: 'grid', gridTemplateColumns: `64px repeat(${cols.length}, minmax(0, 1fr))`, gap: 5, alignItems: 'center' }}>
        <span />
        {cols.map((c, i) => (
          <span key={i} style={{ fontSize: 11, color: 'var(--color-text-muted)', textAlign: 'center' }}>
            {c}
          </span>
        ))}
        {rows.map((r, ri) => (
          <React.Fragment key={r}>
            <span style={{ fontSize: 12.5, color: 'var(--color-text-secondary)', fontWeight: 600 }}>{r}</span>
            {cols.map((_, ci) => {
              const v = values[ri]?.[ci] ?? 0;
              const k = v / max;
              const active = hover && hover.r === ri && hover.c === ci;
              return (
                <span
                  key={ci}
                  onMouseEnter={() => setHover({ r: ri, c: ci })}
                  onMouseLeave={() => setHover(null)}
                  title={`${r} · ${cols[ci]}: ${format(v)}`}
                  className="fade-in"
                  style={{
                    height: 34,
                    borderRadius: 7,
                    background: v <= 0 ? 'var(--color-fill)' : `color-mix(in srgb, var(--chart-violet) ${Math.round(14 + k * 80)}%, var(--color-surface-elevated))`,
                    boxShadow: active ? '0 0 0 2px var(--color-navy)' : undefined,
                    animationDelay: `${(ri * cols.length + ci) * 12}ms`,
                    transition: 'box-shadow 120ms ease',
                  }}
                />
              );
            })}
          </React.Fragment>
        ))}
      </div>
    </div>
  );
};

/* ───────── Stage bars ───────── */

export const StageBars: React.FC<{ stages: { label: string; value: number; color: string }[] }> = ({ stages }) => {
  const max = Math.max(1, ...stages.map((s) => s.value));
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {stages.map((s) => (
        <div key={s.label} style={{ display: 'grid', gridTemplateColumns: '96px 1fr 34px', alignItems: 'center', gap: 14 }}>
          <span style={{ fontSize: 13.5, fontWeight: 600 }}>{s.label}</span>
          <span style={{ height: 8, borderRadius: 4, background: 'var(--color-fill)', overflow: 'hidden' }}>
            <span className="meter-fill" style={{ display: 'block', height: '100%', width: `${s.value > 0 ? Math.max(4, (s.value / max) * 100) : 0}%`, background: s.color, borderRadius: 4 }} />
          </span>
          <span style={{ textAlign: 'right', fontWeight: 700 }}>{s.value}</span>
        </div>
      ))}
    </div>
  );
};
