import React, { useEffect, useState } from 'react';

export const CursorAura: React.FC = () => {
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);
  const [isMouseDown, setIsMouseDown] = useState(false);

  useEffect(() => {
    if (typeof window === 'undefined') return;

    const handleMouseMove = (e: MouseEvent) => {
      setPos({ x: e.clientX, y: e.clientY });
    };

    const handleMouseDown = () => setIsMouseDown(true);
    const handleMouseUp = () => setIsMouseDown(false);

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mousedown', handleMouseDown);
    window.addEventListener('mouseup', handleMouseUp);

    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mousedown', handleMouseDown);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, []);

  if (!pos) return null;

  return (
    <>
      {/* Precision Core Dot */}
      <div
        id="cs-cursor-dot"
        aria-hidden="true"
        style={{
          position: 'fixed',
          top: 0,
          left: 0,
          width: '7px',
          height: '7px',
          backgroundColor: '#00F0FF',
          borderRadius: '50%',
          pointerEvents: 'none',
          zIndex: 99999999,
          boxShadow: '0 0 10px #00F0FF, 0 0 20px #00F0FF',
          transform: `translate3d(${pos.x}px, ${pos.y}px, 0) translate(-50%, -50%)`,
          transition: 'transform 0.04s ease-out',
        }}
      />

      {/* Cybernetic AI Aura */}
      <div
        id="cs-cursor-aura"
        aria-hidden="true"
        style={{
          position: 'fixed',
          top: 0,
          left: 0,
          width: isMouseDown ? '24px' : '34px',
          height: isMouseDown ? '24px' : '34px',
          border: isMouseDown ? '2px solid #EF4444' : '1.6px dashed #00F0FF',
          backgroundColor: isMouseDown ? 'rgba(239, 68, 68, 0.2)' : 'transparent',
          borderRadius: '50%',
          pointerEvents: 'none',
          zIndex: 99999998,
          boxShadow: isMouseDown ? '0 0 25px #EF4444' : '0 0 16px rgba(0, 240, 255, 0.4)',
          transform: `translate3d(${pos.x}px, ${pos.y}px, 0) translate(-50%, -50%)`,
          transition:
            'width 0.18s, height 0.18s, border 0.18s, background-color 0.18s, box-shadow 0.18s',
        }}
      />
    </>
  );
};
