import { useEffect, useRef, useState } from 'react';

/**
 * Animates a number toward `target`. The first real value (including the jump from 0 when data first loads) is shown immediately;
 * later changes count up/down over `ms`. Honors prefers-reduced-motion.
 */
export function useCountUp(target: number, ms = 600): number {
  const [value, setValue] = useState(target);
  const from = useRef(target);
  const shown = useRef(target);

  useEffect(() => {
    const reduce =
      typeof window !== 'undefined' &&
      typeof window.matchMedia === 'function' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduce || from.current === target || from.current === 0) {
      shown.current = target;
      from.current = target;
      setValue(target);
      return;
    }
    const start = performance.now();
    const origin = shown.current;
    let raf = 0;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / ms);
      const eased = 1 - Math.pow(1 - t, 3);
      shown.current = origin + (target - origin) * eased;
      setValue(shown.current);
      if (t < 1) raf = requestAnimationFrame(tick);
      else from.current = target;
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, ms]);

  return value;
}
