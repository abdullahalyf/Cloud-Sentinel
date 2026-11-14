import { livePoll } from '../utils/live';
import React, { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { DollarSign, Download, ChevronRight, Coins, Target, AlertTriangle } from 'lucide-react';
import { api } from '../api/client';
import type { RoiReport } from '../api/types';
import { Panel } from '../components/Panel';
import { CardHeader, HeroCard, KpiCard, PageHeader, Tabs } from '../components/ui';
import { Heatmap } from '../components/vizExtra';
import { burnHeatmap } from '../utils/burn';
import { fmtCompact } from '../components/charts';
import { LineAreaChart } from '../components/viz';
import { BudgetBurnDown } from '../components/BudgetBurnDown';
import { useCountUp } from '../utils/useCountUp';
import { taskRowsByWasted } from '../utils/burndown';
import { hashString, mulberry32 } from '../components/charts';

/* ───────── helpers ───────── */
const money = (v: number, d = 4) => `$${v.toFixed(d)}`;
const moneyShort = (v: number) =>
  v >= 1000
    ? `$${(v / 1000).toFixed(1)}k`
    : v >= 10
    ? `$${v.toFixed(0)}`
    : v >= 0.1
    ? `$${v.toFixed(2)}`
    : `$${v.toFixed(4)}`;
const fmtRoi = (x: number) => (x >= 1000 ? `${(x / 1000).toFixed(1)}k` : x.toFixed(1));

/** Linear axis when series are comparable; symlog when one dwarfs the other. */
interface Axis {
  log: boolean;
  norm: (v: number) => number;
  inv: (f: number) => number;
}
function makeAxis(max: number, floorRef: number): Axis {
  const safeMax = Math.max(max, 1e-9);
  const ref = Math.max(floorRef, 1e-9);
  if (safeMax / ref <= 40) {
    return { log: false, norm: (v) => v / safeMax, inv: (f) => f * safeMax };
  }
  const s0 = ref / 5;
  const top = Math.log10(1 + safeMax / s0);
  return {
    log: true,
    norm: (v) => Math.log10(1 + Math.max(0, v) / s0) / top,
    inv: (f) => s0 * (Math.pow(10, f * top) - 1),
  };
}

const INK = 'var(--color-text-primary)';
const MUTED = 'var(--color-text-muted)';
const ROSE = 'var(--color-state-killed)';
const CYAN = 'var(--color-state-probation)';
const MINT = 'var(--color-state-healthy)';
const AMBER = 'var(--color-state-suspicious)';

/* ───────── Burn-down chart (area-line, shared with the Fleet page) ───────── */
const N = 40;

interface BurnModel {
  minutes: number[];
  prot: number[];
  unprot: number[];
  marks: { idx: number; label: string }[];
}

function buildBurnModel(roi: RoiReport): BurnModel {
  const T = roi.horizon_minutes || 60;
  const rnd = mulberry32(hashString(`burn|${roi.interventions}|${roi.saved_by_action.length}`));
  const inc = Array.from({ length: N }, () => 0.45 + rnd() * 1.1);
  const sum = inc.reduce((a, b) => a + b, 0);
  let acc = 0;
  const prot = inc.map((v) => (acc += v / sum) * roi.total_spend_usd);
  const minutes = prot.map((_, i) => (i / (N - 1)) * T);
  const actions = [...roi.saved_by_action].sort((a, b) => a.action_id - b.action_id);
  const marks = actions.map((a, k) => ({
    idx: Math.min(N - 4, Math.round(N * (0.32 + 0.27 * k))),
    label: `${a.action} ${a.agent_id}`,
    usd: a.usd,
  }));
  const unprot = prot.map((p, i) => {
    let extra = 0;
    marks.forEach((m) => {
      if (i >= m.idx) extra += m.usd * Math.pow((i - m.idx) / Math.max(1, N - 1 - m.idx), 1.7);
    });
    return p + extra;
  });
  return { minutes, prot, unprot, marks };
}

const BurnDownChart = React.memo<{ roi: RoiReport }>(({ roi }) => {
  const model = useMemo(() => buildBurnModel(roi), [roi]);
  const protEnd = model.prot[N - 1] || 0;
  const axis = makeAxis(Math.max(model.unprot[N - 1], protEnd), protEnd);
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => ({ value: axis.inv(f), label: moneyShort(axis.inv(f)) }));
  const markers = model.marks.map((m) => ({ index: m.idx, label: m.label }));
  return (
    <div>
      <LineAreaChart
        testId="burndown-chart"
        series={[
          { name: 'Without Cloud-Sentinel', color: 'var(--chart-indigo)', values: model.unprot },
          { name: 'Protected spend', color: 'var(--chart-cyan)', values: model.prot },
        ]}
        xLabels={model.minutes.map((m) => `${m.toFixed(0)} min`)}
        format={(v) => money(v)}
        markers={markers}
        scale={axis.norm}
        ticks={ticks}
        height={330}
        knots={7}
      />
      {axis.log && (
        <p style={{ fontSize: 12, color: 'var(--color-text-muted)', marginTop: 4 }}>Log scale: the two lines differ by more than 40x.</p>
      )}
    </div>
  );
});

/* ───────── Syntax-highlighted formula ───────── */
const Formula: React.FC<{ text: string }> = ({ text }) => {
  const tokens = text.match(/[A-Za-z_]+|\d+(?:\.\d+)?|[=×−+()/]|\s+/g) ?? [];
  return (
    <code
      style={{
        fontFamily: 'var(--font-mono)',
        fontSize: 12,
        padding: '4px 9px',
        borderRadius: 4,
        background: 'var(--color-fill)',
        border: '1px solid var(--color-border)',
        whiteSpace: 'nowrap',
        justifySelf: 'start',
      }}
    >
      {tokens.map((t, i) => {
        const color = /^saved$/.test(t)
          ? MINT
          : /^[A-Za-z_]+$/.test(t)
          ? 'var(--color-state-probation)'
          : /^\d/.test(t)
          ? AMBER
          : /^[=×−+()/]$/.test(t)
          ? 'var(--color-state-paused)'
          : undefined;
        return (
          <span key={i} style={{ color }}>
            {t}
          </span>
        );
      })}
    </code>
  );
};

interface MethodRowProps {
  title: string;
  formula: string;
  detail: string;
  usd: number;
  share: number;
  color: string;
}

const MethodRow: React.FC<MethodRowProps> = ({ title, formula, detail, usd, share, color }) => {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ borderTop: '1px solid var(--color-border)' }}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        style={{
          width: '100%',
          display: 'grid',
          gridTemplateColumns: '150px minmax(0, 290px) minmax(120px, 1fr) 96px 20px',
          alignItems: 'center',
          gap: 'var(--space-4)',
          padding: '14px 4px',
          textAlign: 'left',
          color: 'inherit',
        }}
      >
        <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 13, color }}>{title}</span>
        <Formula text={formula} />
        <span style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ flex: 1, height: 4, background: 'var(--color-border)', borderRadius: 2 }}>
            <span
              style={{
                display: 'block',
                height: '100%',
                width: `${Math.max(share > 0 ? 1.5 : 0, share * 100)}%`,
                background: color,
                borderRadius: 2,
              }}
            />
          </span>
          <span
            className="tabular-nums"
            style={{ fontFamily: 'var(--font-mono)', fontSize: 12, width: 46, textAlign: 'right' }}
          >
            {(share * 100).toFixed(1)}%
          </span>
        </span>
        <span
          className="tabular-nums"
          style={{ fontFamily: 'var(--font-mono)', fontSize: 12, textAlign: 'right', color: usd > 0 ? INK : MUTED }}
        >
          {usd > 0 ? `+${money(usd, 2)}` : '$0.00'}
        </span>
        <ChevronRight
          size={15}
          color={MUTED}
          style={{ transform: open ? 'rotate(90deg)' : 'none', transition: 'transform 150ms' }}
        />
      </button>
      {open && (
        <p
          style={{
            padding: '0 4px 14px 166px',
            fontSize: 13,
            lineHeight: '20px',
            color: 'var(--color-text-secondary)',
            maxWidth: 760,
          }}
        >
          {detail}
        </p>
      )}
    </div>
  );
};

type CostTab = 'overview' | 'agents' | 'method';

/** CSV of the per-agent task economics (what the "Export CSV" button downloads). */
export function taskCsv(rows: { agent: string; tasks: number; succeeded: number; failed: number; success_rate: number; spend_usd: number; cost_per_success_usd: number; wasted_usd: number }[]): string {
  const head = 'agent,tasks,succeeded,failed,success_rate,spend_usd,cost_per_success_usd,wasted_usd';
  return [head, ...rows.map((r) => [r.agent, r.tasks, r.succeeded, r.failed, r.success_rate, r.spend_usd, r.cost_per_success_usd, r.wasted_usd].join(','))].join('\n');
}

export const CostView: React.FC = () => {
  const [tab, setTab] = useState<CostTab>('overview');
  const { data, isLoading, error, refetch } = useQuery({ queryKey: ['roi'], queryFn: api.getRoi, refetchInterval: livePoll });
  const { data: metricsData } = useQuery({ queryKey: ['metrics', 30], queryFn: () => api.getMetrics(30), refetchInterval: livePoll });
  const { data: actionsData } = useQuery({ queryKey: ['actions'], queryFn: () => api.getActions(50), refetchInterval: livePoll });
  const { data: fleetData } = useQuery({ queryKey: ['fleet'], queryFn: api.getFleet, refetchInterval: livePoll });

  const taskRows = useMemo(() => taskRowsByWasted(data?.tasks_by_agent), [data]);
  const heat = useMemo(() => burnHeatmap(metricsData?.metrics ?? [], 8), [metricsData]);
  const totalSaved = data?.saved_usd ?? 0;
  const totalSpend = data?.total_spend_usd ?? 0;
  const savedShown = useCountUp(totalSaved);
  const roiX = totalSpend > 0 ? totalSaved / totalSpend : 0;
  const tasksSucceeded = data?.tasks_succeeded ?? 0;
  const tasksTotal = data?.tasks_total ?? 0;
  const horizon = data?.horizon_minutes ?? 60;

  const byAction = (names: string[]) =>
    (data?.saved_by_action ?? []).filter((a) => names.includes(a.action)).reduce((acc, a) => acc + a.usd, 0);
  const share = (usd: number) => (totalSaved > 0 ? usd / totalSaved : 0);
  const killPause = byAction(['KILL', 'PAUSE']);
  const deny = byAction(['TOOL_DENY']);
  const rewrite = byAction(['TOOL_REWRITE']);

  const agentRows = useMemo(() => {
    if (!data) return [];
    const fleet = new Map((fleetData?.agents ?? []).map((a) => [a.agent_id, a]));
    return Object.keys(data.spend_by_agent)
      .map((id) => ({
        id,
        tasks: data.tasks_by_agent[id]?.tasks ?? 0,
        ok: data.tasks_by_agent[id]?.succeeded ?? 0,
        cps: data.tasks_by_agent[id]?.cost_per_success_usd ?? 0,
        spend: fleet.get(id)?.spend_usd ?? data.tasks_by_agent[id]?.spend_usd ?? data.spend_by_agent[id] ?? 0,
        budget: fleet.get(id)?.budget_usd ?? 0,
        saved: data.saved_by_action.filter((a) => a.agent_id === id).reduce((acc, a) => acc + a.usd, 0),
      }))
      .sort((a, b) => b.saved - a.saved || b.spend - a.spend);
  }, [data, fleetData]);

  const exportCsv = () => {
    const blob = new Blob([taskCsv(taskRows)], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'cloudsentinel-task-economics.csv';
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 22, width: '100%' }}>
      <PageHeader
        title="Cost Burn-Down & ROI Attribution"
        summary="What the fleet spent, what the circuit breaker saved, and how each saved dollar is priced."
        actions={
          <>
            <button type="button" className="btn" onClick={() => refetch()} aria-label="Refresh financial metrics">
              Refresh
            </button>
            <button type="button" className="btn" onClick={exportCsv} aria-label="Export CSV" disabled={taskRows.length === 0}>
              <Download size={15} /> Export CSV
            </button>
          </>
        }
      >
        <Tabs<CostTab>
          label="Cost views"
          value={tab}
          onChange={setTab}
          tabs={[
            { value: 'overview', label: 'Overview' },
            { value: 'agents', label: 'By agent', count: agentRows.length || undefined },
            { value: 'method', label: 'Attribution' },
          ]}
        />
      </PageHeader>

      {isLoading || error || !data ? (
        <Panel title="Economic Return Summary" icon={<DollarSign size={18} />} loading={isLoading} error={error} onRetry={() => refetch()} />
      ) : tab === 'overview' ? (
        <>
          <section aria-label="Economic Return Summary" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <h2 className="kpi-label">Economic Return Summary</h2>
            <div style={{ display: 'grid', gridTemplateColumns: '1.3fr 1fr 1fr 1fr', gap: 18 }}>
              <HeroCard
                testId="roi-badge"
                label="Total value saved"
                icon={<DollarSign size={15} />}
                value={money(savedShown)}
                foot={`${fmtRoi(roiX)}x ROI on ${money(totalSpend, 2)} of spend · ${data.interventions} interventions`}
                progress={totalSaved + totalSpend > 0 ? totalSaved / (totalSaved + totalSpend) : 0}
              />
              <KpiCard label="Total fleet spend" icon={<Coins size={15} />} value={money(totalSpend)} foot={<span className="muted" style={{ fontSize: 12 }}>{agentRows.length} agents billed</span>} />
              <KpiCard label="Cost per success" icon={<Target size={15} />} value={money(data.cost_per_successful_task_usd)} foot={<span className="muted" style={{ fontSize: 12 }}>{tasksSucceeded} / {tasksTotal} tasks resolved</span>} />
              <KpiCard label="Wasted spend" icon={<AlertTriangle size={15} />} value={money(data.wasted_usd)} foot={<span className="muted" style={{ fontSize: 12 }}>burned in loops</span>} />
            </div>
          </section>

          <section className="card card-pad" aria-label="Cumulative Cost Burn-Down vs Prevented Runaway">
            <CardHeader title="Cumulative cost burn-down vs. prevented runaway" sub={`${horizon} min horizon — amber dots mark circuit-breaker interventions; hover one for details`} />
            <BurnDownChart roi={data} />
          </section>

          <div className="bento" style={{ alignItems: 'start' }}>
            <section className="card card-pad col-span-5" aria-label="When agents burn">
              <CardHeader title="When agents burn" sub="Average tokens per minute, last 30 minutes" />
              {heat.rows.length && heat.cols.length ? (
                <Heatmap testId="burn-heatmap" rows={heat.rows.map((r) => r.toUpperCase())} cols={heat.cols} values={heat.values} format={(v) => `${fmtCompact(v)}/min`} />
              ) : (
                <p className="muted">No metrics yet. The grid fills in once agents report spend.</p>
              )}
            </section>

            <section className="card col-span-7" aria-label="Spend vs Value Saved by Agent" style={{ padding: '20px 0 8px' }}>
              <div style={{ padding: '0 22px' }}>
                <CardHeader title="Spend vs. value saved by agent" sub="Ranked by dollars saved, against each agent's budget" />
              </div>
              <div data-testid="agent-spend-chart" style={{ overflowX: 'auto' }}>
                <table className="ui-table" aria-label="Agent spend and savings">
                  <thead>
                    <tr>
                      <th>Agent</th>
                      <th className="num">Tasks</th>
                      <th className="num">Cost / success</th>
                      <th>Against budget</th>
                      <th className="num">Saved</th>
                    </tr>
                  </thead>
                  <tbody>
                    {agentRows.map((r) => {
                      const pct = r.budget > 0 ? r.spend / r.budget : 0;
                      return (
                        <tr key={r.id}>
                          <td>{r.id}</td>
                          <td className="num">{r.ok}/{r.tasks}</td>
                          <td className="num muted">{money(r.cps)}</td>
                          <td style={{ minWidth: 170 }}>
                            <span style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                              <span style={{ flex: 1, height: 5, borderRadius: 3, background: 'var(--color-fill)' }}>
                                <span className="meter-fill" style={{ display: 'block', height: '100%', borderRadius: 3, width: `${Math.min(100, pct * 100)}%`, background: pct >= 0.8 ? 'var(--chart-red)' : 'var(--chart-violet)' }} />
                              </span>
                              <span style={{ fontSize: 12, width: 38, textAlign: 'right', color: pct >= 0.8 ? 'var(--color-state-killed)' : 'var(--color-state-healthy)' }}>{Math.round(pct * 100)}%</span>
                            </span>
                          </td>
                          <td className="num" style={{ color: r.saved > 0 ? 'var(--color-state-healthy)' : 'var(--color-text-muted)' }}>{r.saved > 0 ? `+${moneyShort(r.saved)}` : '—'}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </section>
          </div>
        </>
      ) : tab === 'agents' ? (
        <>
          <section className="card card-pad" aria-label="Budget Burn-Down by Agent">
            <CardHeader title="Budget burn-down by agent" sub="Budget left over the last 30 min. Dashed lines project when each agent hits $0; paused agents flatten at the PAUSE marker." />
            {(metricsData?.metrics.length ?? 0) === 0 ? (
              <p className="muted" style={{ padding: '24px 0' }}>No metrics yet. Budget lines appear once agents report spend.</p>
            ) : (
              <BudgetBurnDown metrics={metricsData?.metrics ?? []} actions={actionsData?.items ?? []} agents={fleetData?.agents ?? []} />
            )}
          </section>
          <section className="card" aria-label="Task Economics by Agent" style={{ padding: '20px 0 8px' }}>
            <div style={{ padding: '0 22px' }}>
              <CardHeader title="Task economics by agent" sub="Sorted by wasted spend" />
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table className="ui-table" aria-label="Task economics">
                <thead>
                  <tr>
                    {['Agent', 'Tasks', 'Succeeded', 'Failed', 'Success rate', 'Spend', 'Cost / success', 'Wasted'].map((h, i) => (
                      <th key={h} className={i ? 'num' : undefined}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {taskRows.length === 0 && (
                    <tr><td colSpan={8} className="muted">No task data yet.</td></tr>
                  )}
                  {taskRows.map((r) => (
                    <tr key={r.agent}>
                      <td>{r.agent}</td>
                      <td className="num">{r.tasks}</td>
                      <td className="num">{r.succeeded}</td>
                      <td className="num" style={{ color: r.failed > 0 ? 'var(--color-state-killed)' : undefined }}>{r.failed}</td>
                      <td className="num">{(r.success_rate * 100).toFixed(1)}%</td>
                      <td className="num">{money(r.spend_usd)}</td>
                      <td className="num">{money(r.cost_per_success_usd)}</td>
                      <td className="num" style={{ color: r.wasted_usd > 0 ? 'var(--color-state-suspicious)' : 'var(--color-text-muted)' }}>{money(r.wasted_usd)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      ) : (
        <section className="card card-pad" aria-label="Attribution Methodology">
          <CardHeader title="Attribution methodology" sub="How each saved dollar is priced. Select a row for the reasoning." />
          <div>
            <MethodRow
              title="KILL / PAUSE"
              formula={`saved = usd_per_min × ${horizon}`}
              detail="Priced at the agent's $/min at the moment of action, multiplied by the horizon: how long a runaway would have burned before a human noticed."
              usd={killPause}
              share={share(killPause)}
              color={ROSE}
            />
            <MethodRow
              title="TOOL_DENY"
              formula="saved = value_at_stake"
              detail="A denied tool call is credited with the full value that was at stake, such as the amount of a blocked refund or purchase."
              usd={deny}
              share={share(deny)}
              color="var(--color-state-paused)"
            />
            <MethodRow
              title="TOOL_REWRITE"
              formula="saved = value × (1 − new / old)"
              detail="A rewritten call is credited with the reduction only: the value at stake scaled by how much the amount was cut."
              usd={rewrite}
              share={share(rewrite)}
              color={CYAN}
            />
          </div>
        </section>
      )}
    </div>
  );
};
