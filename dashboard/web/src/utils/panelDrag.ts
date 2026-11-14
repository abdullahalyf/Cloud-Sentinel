export interface PanelPos {
  left: number;
  top: number;
}

/** Keeps a floating panel fully reachable: at least `margin` px from every edge of the window. */
export function clampPanel(pos: PanelPos, size: { w: number; h: number }, view: { w: number; h: number }, margin = 8): PanelPos {
  const maxLeft = Math.max(margin, view.w - size.w - margin);
  const maxTop = Math.max(margin, view.h - size.h - margin);
  return {
    left: Math.min(Math.max(margin, pos.left), maxLeft),
    top: Math.min(Math.max(margin, pos.top), maxTop),
  };
}

/** Where the panel ends up while the pointer drags it: start position plus how far the pointer moved. */
export function dragTo(start: PanelPos, from: { x: number; y: number }, now: { x: number; y: number }): PanelPos {
  return { left: start.left + (now.x - from.x), top: start.top + (now.y - from.y) };
}
