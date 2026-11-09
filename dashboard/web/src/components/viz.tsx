import React, { useMemo, useState } from 'react';

/**
 * Chart vocabulary (light theme): a Gantt-style session replay with a scrubber and tooltip card,
 * grouped bars with a hover card, and area-line charts with open dots at the knots.
 * Everything is plain SVG + one HTML tooltip card. Colors come from the --chart-* tokens.
 */

/* ───────── shared bits ───────── */

export const TooltipCard: React.FC<{
  left: string;
  top?: number | string;
  flip?: boolean;
  children: React.ReactNode;
}> = ({ left, top = 8, flip, children }) => (
  <div
    role="tooltip"
    className="pop-in"
    style={{
      position: 'absolute',
      left,
      top,
      transform: flip ? 'translateX(calc(-100% - 14px))' : 'translateX(14px)',
      pointerEvents: 'none',
      zIndex: 5,
      minWidth: 170,
      padding: '12px 14px',
      background: 'rgba(250, 250, 255, 0.97)',
      borderRadius: 14,
      boxShadow: 'var(--shadow-pop)',
      border: '1px solid var(--color-border)',
      fontSize: 12.5,
      lineHeight: '18px',
      color: 'var(--color-text-primary)',
    }}
  >
    {children}
  </div>
);

export const Legend: React.FC<{ items: { color: string; label: string }[] }> = ({ items }) => (
  <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', fontSize: 13, color: 'var(--color-text-secondary)' }}>
    {items.map((it) => (
      <span key={it.label} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
        <span style={{ width: 10, height: 10, borderRadius: '50%', background: it.color }} />
        {it.label}
      </span>
    ))}
  </div>
);

const MONO: React.CSSProperties = { fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' };

/* ───────── Gantt-style session replay ───────── */

export type GanttKind = 'tool' | 'error' | 'llm' | 'action';

export interface GanttBar {
  id: string;
  start: number; // ms (any epoch)
  end: number;
  kind: GanttKind;
  label: string;
  detail?: string;
  who?: string;
}

const KIND_FILL: Record<GanttKind, string> = {
  tool: 'url(#g-tool)',
  error: 'url(#g-error)',
  llm: 'url(#g-llm)',
  action: 'url(#g-action)',
};
const KIND_SOLID: Record<GanttKind, string> = {
  tool: 'var(--chart-amber)',
  error: 'var(--chart-red)',
  llm: 'var(--chart-cyan)',
  action: 'var(--chart-indigo)',
};
export const KIND_NAME: Record<GanttKind, string> = { tool: 'Tool', error: 'Error', llm: 'LLM', action: 'Action' };

const G_W = 900;
const G_PAD = { l: 8, r: 8, t: 14 };
const ROW = 26;

export function pickBars(bars: GanttBar[], max = 12): GanttBar[] {
  return [...bars].sort((a, b) => a.start - b.start).slice(-max);
}

export function fmtSecs(ms: number): string {
  return `${(ms / 1000).toFixed(2)}s`;
}

interface GanttProps {
  bars: GanttBar[];
  title?: string;
  /** controlled playhead (epoch ms). When given, hovering does not move it. */
  scrub?: number | null;
  onScrub?: (t: number) => void;
  kinds?: GanttKind[];
  /** time window [start, end] in ms; defaults to the span of the bars */
  domain?: [number, number];
  testId?: string;
}

export const GanttReplay: React.FC<GanttProps> = ({ bars, title = 'Session replay', scrub, onScrub, kinds, domain, testId }) => {
  const rows = useMemo(() => pickBars(bars), [bars]);
  const [hoverT, setHoverT] = useState<number | null>(null);
  if (rows.length === 0) return null;

  const t0 = domain ? domain[0] : Math.min(...rows.map((b) => b.start));
  const t1 = domain ? Math.max(domain[1], t0 + 1000) : Math.max(t0 + 1000, ...rows.map((b) => b.end));
  const span = t1 - t0;
  const innerW = G_W - G_PAD.l - G_PAD.r;
  const xAt = (t: number) => G_PAD.l + ((t - t0) / span) * innerW;
  const plotH = rows.length * ROW + 10;
  const stripY = G_PAD.t + plotH + 18;
  const H = stripY + 34;

  const controlled = scrub !== undefined && scrub !== null;
  const t = controlled ? (scrub as number) : hoverT; // playhead
  const tipT = hoverT; // the tooltip only follows the pointer
  const active = tipT === null ? null : rows.find((b) => tipT >= b.start && tipT <= b.end) ?? [...rows].reverse().find((b) => b.start <= tipT) ?? rows[0];
  const grid = Array.from({ length: 21 }, (_, i) => G_PAD.l + (i / 20) * innerW);

  const move = (e: React.MouseEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const vx = ((e.clientX - r.left) / r.width) * G_W;
    setHoverT(t0 + Math.max(0, Math.min(1, (vx - G_PAD.l) / innerW)) * span);
  };

  return (
    <div style={{ position: 'relative' }} data-testid={testId}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6, flexWrap: 'wrap', gap: 8 }}>
        <span style={{ fontSize: 15, fontWeight: 600 }}>{title}</span>
        <Legend
          items={(kinds ?? (['tool', 'error', 'llm', 'action'] as GanttKind[])).map((k) => ({ color: KIND_SOLID[k], label: KIND_NAME[k] }))}
        />
      </div>
      <svg
        viewBox={`0 0 ${G_W} ${H}`}
        role="img"
        aria-label={`${title}: ${rows.length} events over ${fmtSecs(span)}`}
        style={{ width: '100%', height: 'auto', display: 'block' }}
        onMouseMove={move}
        onMouseLeave={() => setHoverT(null)}
        onClick={() => hoverT !== null && onScrub?.(hoverT)}
      >
        <defs>
          <linearGradient id="g-tool" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" style={{ stopColor: '#ffd36b' }} />
            <stop offset="100%" style={{ stopColor: 'var(--chart-amber)' }} />
          </linearGradient>
          <linearGradient id="g-error" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" style={{ stopColor: '#f5532b' }} />
            <stop offset="100%" style={{ stopColor: '#f0405f' }} />
          </linearGradient>
          <linearGradient id="g-llm" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" style={{ stopColor: '#2ad8f0' }} />
            <stop offset="100%" style={{ stopColor: 'var(--chart-cyan)' }} />
          </linearGradient>
          <linearGradient id="g-action" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" style={{ stopColor: '#5a3df0' }} />
            <stop offset="100%" style={{ stopColor: 'var(--chart-indigo)' }} />
          </linearGradient>
        </defs>

        {grid.map((x, i) => (
          <line key={i} x1={x} x2={x} y1={G_PAD.t} y2={G_PAD.t + plotH} stroke="rgba(25,18,34,0.06)" />
        ))}

        {rows.map((b, i) => {
          const x = xAt(b.start);
          const w = Math.max(8, xAt(b.end) - x);
          return (
            <rect
              key={b.id}
              className="reveal-x"
              style={{ animationDelay: `${i * 70}ms` }}
              x={x}
              y={G_PAD.t + 6 + i * ROW}
              width={w}
              height={ROW - 8}
              rx={3}
              fill={KIND_FILL[b.kind]}
              opacity={active && active.id !== b.id ? 0.55 : 1}
            />
          );
        })}

        {/* bottom strip: one thin segment per event, coloured by kind */}
        <line x1={G_PAD.l} x2={G_W - G_PAD.r} y1={stripY} y2={stripY} stroke="rgba(25,18,34,0.1)" strokeWidth="3" strokeLinecap="round" />
        {rows.map((b) => (
          <line
            key={`s-${b.id}`}
            x1={xAt(b.start)}
            x2={Math.max(xAt(b.start) + 4, xAt(b.end))}
            y1={stripY}
            y2={stripY}
            stroke={KIND_SOLID[b.kind]}
            strokeWidth="3"
            strokeLinecap="round"
          />
        ))}
        <text x={G_PAD.l} y={stripY + 22} fontSize="11" fontWeight="600" fill="var(--color-text-muted)" style={MONO}>
          0.00s
        </text>
        <text x={G_W - G_PAD.r} y={stripY + 22} fontSize="11" fontWeight="600" textAnchor="end" fill="var(--color-text-muted)" style={MONO}>
          {fmtSecs(span)}
        </text>

        {t !== null && (
          <g pointerEvents="none">
            <line x1={xAt(t)} x2={xAt(t)} y1={G_PAD.t} y2={stripY} stroke="var(--chart-indigo)" strokeWidth="2" />
            <circle cx={xAt(t)} cy={stripY} r="5" fill="var(--chart-indigo)" />
          </g>
        )}
      </svg>

      {tipT !== null && active && (
        <TooltipCard left={`${(xAt(tipT) / G_W) * 100}%`} top={34} flip={xAt(tipT) > G_W * 0.62}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontWeight: 600, marginBottom: 8 }}>
            <span style={{ width: 12, height: 12, borderRadius: 4, background: KIND_SOLID[active.kind] }} />
            {KIND_NAME[active.kind]}
            {active.who && <span style={{ color: 'var(--color-text-muted)', fontWeight: 500 }}>{active.who}</span>}
          </div>
          <div style={{ fontWeight: 600, marginBottom: 2 }}>{active.label}</div>
          {active.detail && <div style={{ color: 'var(--color-text-secondary)', maxWidth: 260, marginBottom: 6 }}>{active.detail}</div>}
          <div style={{ display: 'grid', gridTemplateColumns: 'auto auto', columnGap: 18, color: 'var(--color-text-muted)' }}>
            <span>Start - End</span>
            <span style={{ ...MONO, color: 'var(--color-text-primary)', fontWeight: 600, textAlign: 'right' }}>
              {fmtSecs(active.start - t0)} - {fmtSecs(active.end - t0)}
            </span>
            <span>Duration</span>
            <span style={{ ...MONO, color: 'var(--color-text-primary)', fontWeight: 600, textAlign: 'right' }}>
              {fmtSecs(active.end - active.start)}
            </span>
          </div>
        </TooltipCard>
      )}
    </div>
  );
};

/* ───────── Area-line chart with open dots at the knots ───────── */

export interface LineSeries {
  name: string;
  color: string; // css color / var()
  values: number[];
  dashed?: boolean;
  fill?: boolean;
}

interface LineProps {
  series: LineSeries[];
  xLabels: string[];
  format: (v: number) => string;
  markers?: { index: number; label: string }[];
  /** maps a value to 0..1 of the plot height (defaults to linear over 0..max) */
  scale?: (v: number) => number;
  /** y-axis tick values and labels */
  ticks?: { value: number; label: string }[];
  knots?: number;
  height?: number;
  title?: string;
  testId?: string;
}

const L_W = 760;
const L_PAD = { l: 78, r: 16, t: 14, b: 26 };

export const LineAreaChart: React.FC<LineProps> = ({ series, xLabels, format, markers = [], scale, ticks, knots = 6, height = 280, title, testId }) => {
  const [hover, setHover] = useState<number | null>(null);
  const n = Math.max(...series.map((s) => s.values.length), 0);
  if (n < 2) return <div style={{ height }} />;

  const innerW = L_W - L_PAD.l - L_PAD.r;
  const innerH = height - L_PAD.t - L_PAD.b;
  const base = L_PAD.t + innerH;
  const max = Math.max(1e-9, ...series.flatMap((s) => s.values)) * 1.08;
  const norm = scale ?? ((v: number) => v / max);
  const xAt = (i: number) => L_PAD.l + (i / (n - 1)) * innerW;
  const yAt = (v: number) => base - norm(v) * innerH;
  const yTicks = ticks ?? [0, 0.5, 1].map((f) => ({ value: f * max, label: format(f * max) }));
  const knotIdx = Array.from({ length: knots }, (_, k) => Math.round((k / (knots - 1)) * (n - 1)));

  const move = (e: React.MouseEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const vx = ((e.clientX - r.left) / r.width) * L_W;
    setHover(Math.max(0, Math.min(n - 1, Math.round(((vx - L_PAD.l) / innerW) * (n - 1)))));
  };

  return (
    <div style={{ position: 'relative' }} data-testid={testId}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8, marginBottom: 6 }}>
        {title && <span style={{ fontSize: 15, fontWeight: 600 }}>{title}</span>}
        <Legend items={series.map((s) => ({ color: s.color, label: s.name }))} />
      </div>
      <svg
        viewBox={`0 0 ${L_W} ${height}`}
        role="img"
        aria-label={title ?? series.map((s) => s.name).join(' vs ')}
        style={{ width: '100%', height: 'auto', display: 'block' }}
        onMouseMove={move}
        onMouseLeave={() => setHover(null)}
      >
        <defs>
          {series.map((s, i) => (
            <linearGradient key={i} id={`la-${testId ?? 'c'}-${i}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" style={{ stopColor: s.color, stopOpacity: 0.16 }} />
              <stop offset="100%" style={{ stopColor: s.color, stopOpacity: 0.02 }} />
            </linearGradient>
          ))}
        </defs>
        {yTicks.map((tk) => (
          <g key={tk.label + tk.value}>
            <line x1={L_PAD.l} x2={L_W - L_PAD.r} y1={yAt(tk.value)} y2={yAt(tk.value)} stroke={tk.value === 0 ? 'rgba(25,18,34,0.28)' : 'rgba(25,18,34,0.07)'} />
            <text x={L_PAD.l - 8} y={yAt(tk.value) + 4} textAnchor="end" fontSize="11" fill="var(--color-text-muted)" style={MONO}>
              {tk.label}
            </text>
          </g>
        ))}
        <text x={L_PAD.l} y={height - 6} fontSize="11" fill="var(--color-text-muted)" style={MONO}>
          {xLabels[0]}
        </text>
        <text x={L_W - L_PAD.r} y={height - 6} textAnchor="end" fontSize="11" fill="var(--color-text-muted)" style={MONO}>
          {xLabels[xLabels.length - 1]}
        </text>

        {series.map((s, si) => {
          const pts = s.values.map((v, i) => `${i === 0 ? 'M' : 'L'} ${xAt(i).toFixed(1)} ${yAt(v).toFixed(1)}`).join(' ');
          const last = s.values.length - 1;
          return (
            <g key={s.name}>
              {s.fill !== false && (
                <path className="fade-in" d={`${pts} L ${xAt(last)} ${base} L ${xAt(0)} ${base} Z`} fill={`url(#la-${testId ?? 'c'}-${si})`} />
              )}
              <path
                className={s.dashed ? undefined : 'draw-line'}
                pathLength={s.dashed ? undefined : 1}
                d={pts}
                fill="none"
                stroke={s.color}
                strokeWidth="2.2"
                strokeLinejoin="round"
                strokeLinecap="round"
                strokeDasharray={s.dashed ? '6 5' : undefined}
              />
              {knotIdx
                .filter((i) => i < s.values.length)
                .map((i) => (
                  <circle key={i} className="fade-in" cx={xAt(i)} cy={yAt(s.values[i])} r="4" fill="var(--color-surface)" stroke={s.color} strokeWidth="1.6" />
                ))}
            </g>
          );
        })}

        {(() => {
          let lastLabelX = -1e9;
          return [...markers]
            .sort((a, b) => a.index - b.index)
            .map((m, mi) => {
              const x = xAt(m.index);
              const showLabel = x - lastLabelX > 96;
              if (showLabel) lastLabelX = x;
              return (
                <g key={`${m.label}-${m.index}-${mi}`}>
                  <line x1={x} x2={x} y1={L_PAD.t} y2={base} stroke="var(--chart-amber)" strokeDasharray="3 4" />
                  {showLabel && (
                    <text x={x + 6} y={L_PAD.t + 11} fontSize="11" fontWeight="600" fill="var(--color-amber)">
                      {m.label}
                    </text>
                  )}
                </g>
              );
            });
        })()}

        {hover !== null && (
          <g pointerEvents="none">
            <line x1={xAt(hover)} x2={xAt(hover)} y1={L_PAD.t} y2={base} stroke="rgba(25,18,34,0.25)" />
            {series.map((s) => s.values[hover] !== undefined && (
              <circle key={s.name} cx={xAt(hover)} cy={yAt(s.values[hover])} r="5" fill={s.color} stroke="var(--color-surface)" strokeWidth="2" />
            ))}
          </g>
        )}
      </svg>

      {hover !== null && (
        <TooltipCard left={`${(xAt(hover) / L_W) * 100}%`} top={30} flip={hover > n * 0.6}>
          <div style={{ color: 'var(--color-text-muted)', marginBottom: 6 }}>{xLabels[hover] ?? ''}</div>
          {series.map((s) => (
            <div key={s.name} style={{ display: 'flex', justifyContent: 'space-between', gap: 16, alignItems: 'center' }}>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                <span style={{ width: 9, height: 9, borderRadius: '50%', background: s.color }} />
                {s.name}
              </span>
              <span style={{ ...MONO, fontWeight: 600 }}>{s.values[hover] !== undefined ? format(s.values[hover]) : '-'}</span>
            </div>
          ))}
        </TooltipCard>
      )}
    </div>
  );
};

/* ───────── Grouped bars with a hover card ───────── */

export interface BarGroup {
  label: string;
  bars: { name: string; color: string; value: number }[];
  note?: string;
}

interface BarsProps {
  groups: BarGroup[];
  format: (v: number) => string;
  height?: number;
  title?: string;
  testId?: string;
}

const B_W = 640;

export const GroupedBars: React.FC<BarsProps> = ({ groups, format, height = 250, title, testId }) => {
  const [hover, setHover] = useState<number | null>(null);
  if (groups.length === 0) return <div style={{ height }} />;
  const pad = { l: 8, r: 8, t: 16, b: 34 };
  const innerH = height - pad.t - pad.b;
  const base = pad.t + innerH;
  const max = Math.max(1e-9, ...groups.flatMap((g) => g.bars.map((b) => b.value)));
  const slot = (B_W - pad.l - pad.r) / groups.length;
  const barW = Math.min(52, slot / 3.2);
  const names = Array.from(new Map(groups.flatMap((g) => g.bars).map((b) => [b.name, b.color]))).map(([label, color]) => ({ label, color }));

  return (
    <div style={{ position: 'relative' }} data-testid={testId}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8, marginBottom: 6 }}>
        {title && <span style={{ fontSize: 15, fontWeight: 600 }}>{title}</span>}
        <Legend items={names} />
      </div>
      <svg
        viewBox={`0 0 ${B_W} ${height}`}
        role="img"
        aria-label={title ?? 'Grouped bars'}
        style={{ width: '100%', height: 'auto', display: 'block' }}
        onMouseLeave={() => setHover(null)}
      >
        {groups.map((g, gi) => {
          const cx = pad.l + slot * gi + slot / 2;
          const gw = g.bars.length * barW + (g.bars.length - 1) * 4 + 28;
          return (
            <g key={g.label} onMouseEnter={() => setHover(gi)}>
              <rect x={cx - slot / 2} y={0} width={slot} height={height} fill="transparent" />
              {hover === gi && (
                <rect x={cx - gw / 2} y={pad.t - 6} width={gw} height={innerH + 38} rx={18} fill="rgba(117,72,231,0.09)" />
              )}
              {g.bars.map((b, bi) => {
                const h = Math.max(b.value > 0 ? 3 : 0, (b.value / max) * innerH);
                const x = cx - gw / 2 + 14 + bi * (barW + 4);
                return (
                  <rect
                    key={b.name}
                    className="bar-rise"
                    style={{ animationDelay: `${gi * 90 + bi * 50}ms` }}
                    x={x}
                    y={base - h}
                    width={barW}
                    height={h}
                    rx={4}
                    fill={b.color}
                  />
                );
              })}
              <text x={cx} y={height - 10} textAnchor="middle" fontSize="13" fill="var(--color-text-secondary)" fontWeight={hover === gi ? 600 : 400}>
                {g.label}
              </text>
            </g>
          );
        })}
        <line x1={pad.l} x2={B_W - pad.r} y1={base} y2={base} stroke="rgba(25,18,34,0.3)" />
      </svg>

      {hover !== null && (
        <TooltipCard
          left={`${((pad.l + slot * hover + slot / 2) / B_W) * 100}%`}
          top={6}
          flip={hover >= groups.length / 2}
        >
          <div style={{ fontWeight: 600 }}>{groups[hover].label}</div>
          <div style={{ ...MONO, fontWeight: 700, fontSize: 15, margin: '2px 0 2px' }}>
            {format(groups[hover].bars.reduce((s, b) => s + b.value, 0))}
          </div>
          <div style={{ color: 'var(--color-text-muted)', marginBottom: 8 }}>{groups[hover].note ?? 'Total'}</div>
          <div style={{ display: 'flex', gap: 18 }}>
            {groups[hover].bars.map((b) => (
              <div key={b.name}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span style={{ width: 14, height: 14, borderRadius: '50%', background: b.color }} />
                  <span style={{ ...MONO, fontWeight: 600 }}>{format(b.value)}</span>
                </div>
                <div style={{ color: 'var(--color-text-muted)', marginLeft: 20 }}>{b.name}</div>
              </div>
            ))}
          </div>
        </TooltipCard>
      )}
    </div>
  );
};
