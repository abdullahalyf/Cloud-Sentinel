import React from 'react';
import type { ActionRow, AgentView, RoiReport } from '../api/types';
import { StateBadge } from './StateBadge';
import { ago, budgetUsed, compareSpend, fmtUsd, runway, type RunwayTone } from '../utils/costView';

const TONE_COLOR: Record<RunwayTone, string> = {
  ok: 'var(--color-state-healthy)',
  warn: 'var(--color-state-suspicious)',
  danger: 'var(--color-state-killed)',
  stopped: 'var(--color-text-muted)',
  idle: 'var(--color-text-muted)',
};
/** The bar shows how much budget is gone: red only when nearly spent, grey once the breaker stopped the agent. */
const barColor = (pct: number, tone: RunwayTone): string =>
  tone === 'stopped' ? 'var(--color-text-muted)' : pct >= 90 ? 'var(--chart-red)' : pct >= 70 ? 'var(--color-state-suspicious)' : 'var(--chart-violet)';

const Bar: React.FC<{ frac: number; color: string; height?: number }> = ({ frac, color, height = 8 }) => (
  <span style={{ display: 'block', width: '100%', height, borderRadius: height, background: 'var(--color-fill)' }}>
    <span className="meter-fill" style={{ display: 'block', height: '100%', borderRadius: height, width: `${Math.max(frac > 0 ? 1.5 : 0, frac * 100)}%`, background: color }} />
  </span>
);

/** One card per agent: how much of its budget is gone, how long the rest lasts, and what the circuit breaker did. */
export const AgentBudgetCards: React.FC<{ agents: AgentView[]; roi: RoiReport }> = ({ agents, roi }) => {
  if (agents.length === 0) return <p className="muted">No agents reporting yet.</p>;
  return (
    <div data-testid="agent-budget-cards" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 440px), 1fr))', gap: 16 }}>
      {agents.map((a) => {
        const used = budgetUsed(a.spend_usd, a.budget_usd);
        const run = runway(a);
        const acts = roi.saved_by_action.filter((s) => s.agent_id === a.agent_id);
        const saved = acts.reduce((n, s) => n + s.usd, 0);
        return (
          <article key={a.agent_id} aria-label={`Budget for ${a.agent_id}`} style={{ border: '1px solid var(--color-border)', borderRadius: 16, padding: 18, display: 'flex', flexDirection: 'column', gap: 12 }}>
            <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10 }}>
              <strong style={{ fontSize: 15 }}>{a.agent_id}</strong>
              <StateBadge state={a.state} />
            </header>
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 8 }}>
                <span style={{ fontSize: 22, fontWeight: 700 }}>{fmtUsd(a.spend_usd)}</span>
                <span className="muted" style={{ fontSize: 13 }}>of {fmtUsd(a.budget_usd)} · {used.pct}% used</span>
              </div>
              <Bar frac={used.frac} color={barColor(used.pct, run.tone)} />
            </div>
            <p style={{ margin: 0, fontSize: 13, color: TONE_COLOR[run.tone], fontWeight: 600 }}>{run.text}</p>
            <p className="muted" style={{ margin: 0, fontSize: 12.5, borderTop: '1px solid var(--color-border)', paddingTop: 10 }}>
              {acts.length === 0
                ? 'No interventions'
                : `${acts.map((s) => s.action).join(', ')} · saved ${fmtUsd(saved)}`}
            </p>
          </article>
        );
      })}
    </div>
  );
};

/** Actual spend next to what it would have been, then the interventions that made the difference. */
export const SavingsPanel: React.FC<{ roi: RoiReport; actions: ActionRow[] }> = ({ roi, actions }) => {
  const cmp = compareSpend(roi.total_spend_usd, roi.saved_usd);
  const rows = [...roi.saved_by_action].sort((a, b) => b.usd - a.usd);
  const reason = (id: number) => actions.find((x) => x.id === id);
  return (
    <div data-testid="savings-panel" style={{ display: 'grid', gridTemplateColumns: 'minmax(260px, 1fr) minmax(300px, 1.3fr)', gap: 28 }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, marginBottom: 6 }}>
            <span>Without Cloud-Sentinel</span>
            <strong>{fmtUsd(cmp.wouldHave)}</strong>
          </div>
          <Bar frac={cmp.wouldHave > 0 ? 1 : 0} color="var(--chart-indigo)" height={14} />
        </div>
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, marginBottom: 6 }}>
            <span>What was actually spent</span>
            <strong>{fmtUsd(cmp.actual)}</strong>
          </div>
          <Bar frac={cmp.wouldHave > 0 ? cmp.actual / cmp.wouldHave : 0} color="var(--chart-cyan)" height={14} />
        </div>
        <p className="muted" style={{ margin: 0, fontSize: 13, lineHeight: 1.5 }}>
          {cmp.saved > 0
            ? `The circuit breaker prevented ${fmtUsd(cmp.saved)}, ${(cmp.savedShare * 100).toFixed(1)}% of what the fleet would have spent over the next ${roi.horizon_minutes} min.`
            : 'Nothing has been stopped yet, so spend matches the projection.'}
        </p>
      </div>
      <div>
        <h3 className="kpi-label" style={{ margin: '0 0 8px' }}>What it did</h3>
        {rows.length === 0 ? (
          <p className="muted" style={{ margin: 0 }}>No interventions yet.</p>
        ) : (
          <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
            {rows.map((s) => {
              const act = reason(s.action_id);
              return (
                <li key={s.action_id} style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: 12, padding: '10px 0', borderTop: '1px solid var(--color-border)' }}>
                  <span style={{ minWidth: 0 }}>
                    <strong style={{ fontSize: 13.5 }}>{s.action} {s.agent_id}</strong>
                    <span className="muted" style={{ fontSize: 12.5, display: 'block' }}>
                      {act?.reason ? act.reason : s.actor}
                      {act ? ` · ${ago(act.created_at)}` : ''}
                    </span>
                  </span>
                  <strong style={{ color: 'var(--color-state-healthy)', fontSize: 13.5 }}>+{fmtUsd(s.usd)}</strong>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
};
