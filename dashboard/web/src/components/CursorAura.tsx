import React, { useEffect, useRef } from 'react';

/**
 * Cursor dot + ring. Position is written straight to the DOM from a rAF loop, so moving the
 * mouse never triggers a React re-render (the old state-per-mousemove version caused jank).
 */
export const CursorAura: React.FC = () => {
  const dot = useRef<HTMLDivElement>(null);
  const ring = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let x = 0;
    let y = 0;
    let raf = 0;
    let shown = false;

    const paint = () => {
      raf = 0;
      const t = `translate3d(${x}px, ${y}px, 0) translate(-50%, -50%)`;
      if (dot.current) dot.current.style.transform = t;
      if (ring.current) ring.current.style.transform = t;
    };
    const onMove = (e: MouseEvent) => {
      x = e.clientX;
      y = e.clientY;
      if (!shown) {
        shown = true;
        if (dot.current) dot.current.style.opacity = '1';
        if (ring.current) ring.current.style.opacity = '1';
      }
      if (!raf) raf = requestAnimationFrame(paint);
    };
    const onDown = () => ring.current?.setAttribute('data-down', 'true');
    const onUp = () => ring.current?.removeAttribute('data-down');

    window.addEventListener('mousemove', onMove, { passive: true });
    window.addEventListener('mousedown', onDown);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mousedown', onDown);
      window.removeEventListener('mouseup', onUp);
      if (raf) cancelAnimationFrame(raf);
    };
  }, []);

  return (
    <>
      <div
        ref={dot}
        id="cs-cursor-dot"
        aria-hidden="true"
        style={{
          position: 'fixed',
          top: 0,
          left: 0,
          width: 7,
          height: 7,
          opacity: 0,
          backgroundColor: '#00F0FF',
          borderRadius: '50%',
          pointerEvents: 'none',
          zIndex: 99999999,
          willChange: 'transform',
        }}
      />
      <div
        ref={ring}
        id="cs-cursor-aura"
        className="cs-ring"
        aria-hidden="true"
        style={{
          position: 'fixed',
          top: 0,
          left: 0,
          width: 34,
          height: 34,
          opacity: 0,
          pointerEvents: 'none',
          zIndex: 99999998,
          willChange: 'transform',
        }}
      />
    </>
  );
};
