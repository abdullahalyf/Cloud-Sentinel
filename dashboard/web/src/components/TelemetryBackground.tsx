import React, { useEffect } from 'react';

/**
 * Live Telemetry Grid Canvas: obsidian base, 32px architectural micro-grid under a radial
 * vignette, light packets travelling along grid lines, and a slowly breathing aurora.
 * Beams use fixed negative delays so their positions are deterministic; browsers driven by
 * automation (navigator.webdriver) freeze them mid-flight for stable screenshots.
 * prefers-reduced-motion hides the beams entirely (see base.css).
 */
const CELL = 32;
const CYAN = '#06B6D4';
const INDIGO = '#6366F1';
const EMERALD = '#10B981';

interface Beam {
  axis: 'h' | 'v';
  line: number; // grid line index
  color: string;
  dur: number; // seconds
  delay: number; // seconds (negative = already in flight)
}

const BEAMS: Beam[] = [
  { axis: 'h', line: 4, color: CYAN, dur: 14, delay: -3 },
  { axis: 'h', line: 11, color: INDIGO, dur: 19, delay: -11 },
  { axis: 'h', line: 17, color: EMERALD, dur: 16, delay: -6 },
  { axis: 'v', line: 6, color: EMERALD, dur: 13, delay: -4 },
  { axis: 'v', line: 15, color: CYAN, dur: 18, delay: -12 },
  { axis: 'v', line: 29, color: INDIGO, dur: 15, delay: -2 },
  { axis: 'v', line: 52, color: EMERALD, dur: 16, delay: -8 },
];

export const TelemetryBackground: React.FC = () => {
  useEffect(() => {
    const automated = typeof navigator !== 'undefined' && navigator.webdriver === true;
    document.documentElement.dataset.static = automated ? 'true' : 'false';
  }, []);

  return (
    <>
      <div className="tg-aurora" aria-hidden="true" data-testid="telemetry-aurora" />
      <div className="tg-layer" aria-hidden="true" data-testid="telemetry-grid">
        <svg className="tg-grid" xmlns="http://www.w3.org/2000/svg">
          <defs>
            <pattern id="tg-cell" width={CELL} height={CELL} patternUnits="userSpaceOnUse">
              <path
                d={`M ${CELL} 0 H 0 V ${CELL}`}
                fill="none"
                stroke="rgba(255,255,255,0.035)"
                strokeWidth="1"
              />
            </pattern>
          </defs>
          <rect width="100%" height="100%" fill="#05070B" />
          <rect width="100%" height="100%" fill="url(#tg-cell)" />
        </svg>
        {BEAMS.map((b, i) => (
          <span
            key={i}
            className={`tg-beam tg-beam-${b.axis}`}
            style={
              {
                [b.axis === 'h' ? 'top' : 'left']: `${b.line * CELL}px`,
                '--c': b.color,
                '--dur': `${b.dur}s`,
                '--delay': `${b.delay}s`,
              } as React.CSSProperties
            }
          />
        ))}
      </div>
      <div className="tg-vignette" aria-hidden="true" />
    </>
  );
};
