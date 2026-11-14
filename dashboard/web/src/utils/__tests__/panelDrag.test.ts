import { describe, expect, it } from 'vitest';
import { clampPanel, dragTo } from '../panelDrag';

const view = { w: 1000, h: 700 };
const size = { w: 400, h: 300 };

describe('clampPanel', () => {
  it('leaves a position that fits untouched', () => {
    expect(clampPanel({ left: 264, top: 72 }, size, view)).toEqual({ left: 264, top: 72 });
  });
  it('keeps the panel inside every edge', () => {
    expect(clampPanel({ left: -50, top: -20 }, size, view)).toEqual({ left: 8, top: 8 });
    expect(clampPanel({ left: 900, top: 650 }, size, view)).toEqual({ left: 592, top: 392 });
  });
  it('still returns a usable spot when the window is smaller than the panel', () => {
    expect(clampPanel({ left: 300, top: 300 }, size, { w: 300, h: 200 })).toEqual({ left: 8, top: 8 });
  });
});

describe('dragTo', () => {
  it('moves the panel by the distance the pointer travelled', () => {
    expect(dragTo({ left: 264, top: 72 }, { x: 100, y: 100 }, { x: 160, y: 90 })).toEqual({ left: 324, top: 62 });
  });
});
