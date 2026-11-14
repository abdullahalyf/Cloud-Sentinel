import React, { useEffect, useState } from 'react';

/** Deterministic helpers + SVG path builders shared by the Fleet and Cost charts. */

export function hashString(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export interface Pt {
  x: number;
  y: number;
}

/** Smooth Catmull-Rom → cubic Bézier path through points. */
export function smoothPath(pts: Pt[]): string {
  if (pts.length === 0) return '';
  if (pts.length === 1) return `M ${pts[0].x.toFixed(1)} ${pts[0].y.toFixed(1)}`;
  let d = `M ${pts[0].x.toFixed(1)} ${pts[0].y.toFixed(1)}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] ?? pts[i];
    const p1 = pts[i];
    const p2 = pts[i + 1];
    const p3 = pts[i + 2] ?? p2;
    const c1x = p1.x + (p2.x - p0.x) / 6;
    const c1y = p1.y + (p2.y - p0.y) / 6;
    const c2x = p2.x - (p3.x - p1.x) / 6;
    const c2y = p2.y - (p3.y - p1.y) / 6;
    d += ` C ${c1x.toFixed(1)} ${c1y.toFixed(1)}, ${c2x.toFixed(1)} ${c2y.toFixed(1)}, ${p2.x.toFixed(1)} ${p2.y.toFixed(1)}`;
  }
  return d;
}

export function areaFromLine(line: string, last: Pt, first: Pt, baseY: number): string {
  return `${line} L ${last.x.toFixed(1)} ${baseY} L ${first.x.toFixed(1)} ${baseY} Z`;
}

/** Seeded waveform ending exactly at `end`, fluctuating around it. */
export function seededWave(seed: string, n: number, end: number, volatility = 0.22): number[] {
  const rnd = mulberry32(hashString(seed));
  const out: number[] = [];
  let drift = 0;
  for (let i = 0; i < n; i++) {
    drift = drift * 0.6 + (rnd() - 0.5) * volatility * 2;
    const season = Math.sin(i * 0.55 + rnd()) * volatility * 0.6;
    out.push(Math.max(0, end * (1 + drift + season)));
  }
  out[n - 1] = end;
  return out;
}

/** Seeded sparse spikes (zero baseline) for event-style bars. */
export function seededSpikes(seed: string, n: number, peak: number, count = 2): number[] {
  const rnd = mulberry32(hashString(seed));
  const out = new Array<number>(n).fill(0);
  for (let k = 0; k < count; k++) {
    const idx = Math.floor(n * (0.3 + 0.32 * k) + rnd() * 3);
    out[Math.min(n - 2, idx)] = peak * (0.7 + rnd() * 0.3);
  }
  return out;
}

/**
 * Rolling live series: starts as a deterministic seeded history ending at the current value,
 * then appends one real sample per data refresh (`stamp`, e.g. react-query dataUpdatedAt).
 */
export function useRollingSeries(
  value: number | undefined,
  stamp: number,
  seed: string,
  n = 36,
  mode: 'wave' | 'spikes' = 'wave'
): number[] {
  const [series, setSeries] = useState<number[]>([]);
  useEffect(() => {
    if (value === undefined || !Number.isFinite(value)) return;
    setSeries((prev) => {
      if (prev.length === 0) {
        return mode === 'spikes'
          ? seededSpikes(seed, n, Math.max(value, 1))
          : seededWave(seed, n, value);
      }
      return [...prev.slice(1), value];
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stamp, value]);
  return series;
}

export function fmtCompact(v: number): string {
  const a = Math.abs(v);
  if (a >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (a >= 1e3) return `${(v / 1e3).toFixed(1)}k`;
  return a >= 100 ? v.toFixed(0) : a >= 1 ? v.toFixed(1) : v.toFixed(2);
}

interface MiniSparkProps {
  data: number[];
  color: string;
  id: string;
  width?: number;
  height?: number;
}

/** Tiny area sparkline used in KPI tiles. */
export const MiniSpark: React.FC<MiniSparkProps> = ({
  data,
  color,
  id,
  width = 120,
  height = 32,
}) => {
  if (data.length < 2) return <div style={{ height }} />;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const span = max - min || 1;
  const pts = data.map((v, i) => ({
    x: (i / (data.length - 1)) * width,
    y: height - 4 - ((v - min) / span) * (height - 8),
  }));
  const line = smoothPath(pts);
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      style={{ width: '100%', height, display: 'block' }}
      aria-hidden="true"
    >
      <defs>
        <linearGradient id={`ms-${id}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.35" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={areaFromLine(line, pts[pts.length - 1], pts[0], height)} fill={`url(#ms-${id})`} />
      <path d={line} fill="none" stroke={color} strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
};
