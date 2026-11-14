import type { AgentState } from '../api/types';

/** Pure helpers for the Cost & ROI page. Unit-tested in __tests__/costView.test.ts. */

/** "$132.12", "$0.078", "$0.0021": enough digits to be honest about small amounts, never a wall of zeros. */
export function fmtUsd(v: number): string {
  const a = Math.abs(v);
  if (a >= 1000) return `$${(v / 1000).toFixed(1)}k`;
  if (a >= 1) return `$${v.toFixed(2)}`;
  if (a >= 0.01) return `$${v.toFixed(3)}`;
  return `$${v.toFixed(4)}`;
}

/** "1,696×" for big returns, "12.4×" for small ones. */
export function fmtRoi(x: number): string {
  if (!Number.isFinite(x) || x <= 0) return '0×';
  return x >= 100 ? `${Math.round(x).toLocaleString('en-US')}×` : `${x.toFixed(1)}×`;
}

export interface SpendComparison {
  actual: number;
  wouldHave: number;
  saved: number;
  /** share of the projected spend that the circuit breaker prevented, 0..1 */
  savedShare: number;
}

/** What the fleet actually spent next to what it would have spent without the circuit breaker. */
export function compareSpend(actual: number, saved: number): SpendComparison {
  const a = Math.max(0, actual);
  const s = Math.max(0, saved);
  const wouldHave = a + s;
  return { actual: a, wouldHave, saved: s, savedShare: wouldHave > 0 ? s / wouldHave : 0 };
}

export type RunwayTone = 'ok' | 'warn' | 'danger' | 'stopped' | 'idle';

export interface Runway {
  text: string;
  tone: RunwayTone;
}

/** One plain sentence about how long an agent's budget lasts. */
export function runway(a: { state: AgentState; budget_usd: number; spend_usd: number; usd_per_min: number }): Runway {
  if (a.state === 'killed') return { text: 'Stopped by the circuit breaker', tone: 'stopped' };
  if (a.state === 'paused') return { text: 'Paused by the circuit breaker', tone: 'stopped' };
  const left = a.budget_usd - a.spend_usd;
  if (a.budget_usd > 0 && left <= 0) return { text: 'Budget used up', tone: 'danger' };
  if (!(a.usd_per_min > 0)) return { text: 'Not spending right now', tone: 'idle' };
  const mins = left / a.usd_per_min;
  if (mins < 60) return { text: `Runs out in ~${Math.max(1, Math.round(mins))} min at this rate`, tone: 'danger' };
  const hours = mins / 60;
  if (hours < 48) return { text: `Lasts ~${Math.round(hours)} h at this rate`, tone: hours < 6 ? 'warn' : 'ok' };
  return { text: `Lasts ~${Math.round(hours / 24)} days at this rate`, tone: 'ok' };
}

/** Fraction of the budget used, clamped to 0..1 for the bar (the text still shows the real percentage). */
export function budgetUsed(spend: number, budget: number): { frac: number; pct: number } {
  if (!(budget > 0)) return { frac: 0, pct: 0 };
  const raw = spend / budget;
  return { frac: Math.min(1, Math.max(0, raw)), pct: Math.round(raw * 100) };
}

/** "5 min ago", "2 h ago", "3 d ago" for the interventions list. */
export function ago(iso: string, now = Date.now()): string {
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return '';
  const m = Math.max(0, Math.round((now - t) / 60_000));
  if (m < 1) return 'just now';
  if (m < 60) return `${m} min ago`;
  if (m < 48 * 60) return `${Math.round(m / 60)} h ago`;
  return `${Math.round(m / 1440)} d ago`;
}
