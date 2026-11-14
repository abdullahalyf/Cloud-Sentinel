import { describe, expect, it } from 'vitest';
import { ago, budgetUsed, compareSpend, fmtRoi, fmtUsd, runway } from '../costView';

describe('fmtUsd', () => {
  it('uses 2 decimals from $1, 3 under $1, 4 under a cent', () => {
    expect(fmtUsd(132.12)).toBe('$132.12');
    expect(fmtUsd(0.0779)).toBe('$0.078');
    expect(fmtUsd(0.0021)).toBe('$0.0021');
    expect(fmtUsd(12500)).toBe('$12.5k');
  });
});

describe('fmtRoi', () => {
  it('writes big returns with separators and a real multiplication sign', () => {
    expect(fmtRoi(1696.4)).toBe('1,696×');
    expect(fmtRoi(12.44)).toBe('12.4×');
    expect(fmtRoi(0)).toBe('0×');
    expect(fmtRoi(NaN)).toBe('0×');
  });
});

describe('compareSpend', () => {
  it('adds what was saved back onto what was spent', () => {
    const c = compareSpend(0.3, 132.12);
    expect(c.wouldHave).toBeCloseTo(132.42);
    expect(c.savedShare).toBeCloseTo(0.9977, 3);
  });
  it('does not divide by zero and ignores negatives', () => {
    expect(compareSpend(0, 0).savedShare).toBe(0);
    expect(compareSpend(-5, -1).wouldHave).toBe(0);
  });
});

describe('runway', () => {
  const base = { budget_usd: 0.5, spend_usd: 0.0754, usd_per_min: 0.01435 };
  it('says stopped for killed and paused agents whatever the rate', () => {
    expect(runway({ ...base, state: 'killed', usd_per_min: 5 })).toEqual({ text: 'Stopped by the circuit breaker', tone: 'stopped' });
    expect(runway({ ...base, state: 'paused' }).tone).toBe('stopped');
  });
  it('reports idle when nothing is burning', () => {
    expect(runway({ ...base, state: 'healthy', usd_per_min: 0 }).tone).toBe('idle');
  });
  it('reports hours when the budget lasts a while', () => {
    const r = runway({ ...base, state: 'healthy' }); // 0.4246 / 0.01435 = 29.6 min
    expect(r.tone).toBe('danger');
    expect(r.text).toContain('30 min');
    const slow = runway({ ...base, state: 'healthy', usd_per_min: 0.001 }); // ~7 h
    expect(slow.text).toBe('Lasts ~7 h at this rate');
    expect(slow.tone).toBe('ok');
  });
  it('reports days for very long runways and "used up" when over budget', () => {
    expect(runway({ ...base, state: 'healthy', usd_per_min: 0.0001 }).text).toContain('days');
    expect(runway({ ...base, state: 'healthy', spend_usd: 0.6 }).text).toBe('Budget used up');
  });
});

describe('budgetUsed', () => {
  it('clamps the bar but keeps the true percentage', () => {
    expect(budgetUsed(0.25, 0.5)).toEqual({ frac: 0.5, pct: 50 });
    expect(budgetUsed(0.75, 0.5)).toEqual({ frac: 1, pct: 150 });
    expect(budgetUsed(1, 0)).toEqual({ frac: 0, pct: 0 });
  });
});

describe('ago', () => {
  const now = Date.parse('2026-11-14T12:00:00Z');
  it('formats minutes, hours and days', () => {
    expect(ago('2026-11-14T11:59:50Z', now)).toBe('just now');
    expect(ago('2026-11-14T11:30:00Z', now)).toBe('30 min ago');
    expect(ago('2026-11-14T09:00:00Z', now)).toBe('3 h ago');
    expect(ago('2026-11-10T12:00:00Z', now)).toBe('4 d ago');
    expect(ago('nonsense', now)).toBe('');
  });
});
