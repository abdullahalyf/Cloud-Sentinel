import { livePoll } from '../utils/live';
import React, { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { DollarSign, RotateCcw, ChevronRight } from 'lucide-react';
import { api } from '../api/client';
import type { RoiReport } from '../api/types';
import { Panel } from '../components/Panel';
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

const Stat: React.FC<{ label: string; value: string; note?: string; color?: string }> = ({
  label,
  value,
  note,
  color,
}) => (
  <div style={{ padding: '0 var(--space-5)', minWidth: 0 }}>
    <div className="kpi-label">{label}</div>
    <div className="kpi-value" style={{ fontSize: 26, marginTop: 4, color: color ?? INK }}>
      {value}
    </div>
    {note && <div style={{ fontSize: 12, color: MUTED, marginTop: 2 }}>{note}</div>}
  </div>
);

export const CostView: React.FC = () => {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['roi'],
    queryFn: api.getRoi,
    refetchInterval: livePoll,
  });

  const { data: metricsData } = useQuery({
    queryKey: ['metrics', 30],
    queryFn: () => api.getMetrics(30),
    refetchInterval: livePoll,
  });
  const { data: actionsData } = useQuery({
    queryKey: ['actions'],
    queryFn: () => api.getActions(50),
    refetchInterval: livePoll,
  });
  const { data: fleetData } = useQuery({
    queryKey: ['fleet'],
    queryFn: api.getFleet,
    refetchInterval: livePoll,
  });
  const taskRows = useMemo(() => taskRowsByWasted(data?.tasks_by_agent), [data]);

  const totalSaved = data?.saved_usd ?? 0;
  const totalSpend = data?.total_spend_usd ?? 0;
  const savedShown = useCountUp(totalSaved);
  const roiX = totalSpend > 0 ? totalSaved / totalSpend : 0;
  const tasksSucceeded = data?.tasks_succeeded ?? 0;
  const tasksTotal = data?.tasks_total ?? 0;
  const successPct = tasksTotal > 0 ? (tasksSucceeded / tasksTotal) * 100 : 0;

  const byAction = (names: string[]) =>
    (data?.saved_by_action ?? []).filter((a) => names.includes(a.action)).reduce((s, a) => s + a.usd, 0);
  const share = (usd: number) => (totalSaved > 0 ? usd / totalSaved : 0);
  const killPause = byAction(['KILL', 'PAUSE']);
  const deny = byAction(['TOOL_DENY']);
  const rewrite = byAction(['TOOL_REWRITE']);
  const horizon = data?.horizon_minutes ?? 60;

  const agentRows = useMemo(() => {
    if (!data) return [];
    return Object.keys(data.spend_by_agent)
      .map((id) => ({
        id,
        spend: data.tasks_by_agent[id]?.spend_usd ?? data.spend_by_agent[id] ?? 0,
        wasted: data.tasks_by_agent[id]?.wasted_usd ?? 0,
        saved: data.saved_by_action.filter((a) => a.agent_id === id).reduce((s, a) => s + a.usd, 0),
        ok: data.tasks_by_agent[id]?.succeeded ?? 0,
        tasks: data.tasks_by_agent[id]?.tasks ?? 0,
      }))
      .sort((a, b) => b.saved - a.saved || b.spend - a.spend);
  }, [data]);
  const maxSaved = Math.max(1e-9, ...agentRows.map((r) => r.saved));

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 'var(--space-8)',
        width: '100%',
        paddingBottom: 'var(--space-8)',
      }}
    >
      <header
        style={{
          display: 'flex',
          alignItems: 'flex-end',
          justifyContent: 'space-between',
          gap: 'var(--space-4)',
          flexWrap: 'wrap',
        }}
      >
        <div>
          <h1
            style={{
              fontSize: 'var(--type-title-md-size)',
              lineHeight: 'var(--type-title-md-lh)',
              fontWeight: 600,
              letterSpacing: '-0.02em',
            }}
          >
            Cost Burn-Down &amp; ROI Attribution
          </h1>
          <p style={{ color: 'var(--color-text-secondary)', marginTop: 2 }}>
            Real-time financial return on investment, task-attributed spend, and autonomous runaway
            prevention.
          </p>
        </div>
        <button
          type="button"
          onClick={() => refetch()}
          aria-label="Refresh financial metrics"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 'var(--space-2)',
            border: 'none',
            borderRadius: 10,
            color: '#fff',
            background: 'var(--color-navy)',
            padding: '8px 14px',
            fontWeight: 600,
          }}
        >
          <RotateCcw size={13} /> Refresh
        </button>
      </header>

      {isLoading || error || !data ? (
        <Panel
          title="Economic Return Summary"
          icon={<DollarSign size={18} />}
          loading={isLoading}
          error={error}
          onRetry={() => refetch()}
        />
      ) : (
        <>
          {/* Hero figure + hairline ledger, no card chrome */}
          <section
            aria-label="Economic Return Summary"
            style={{
              display: 'grid',
              gridTemplateColumns: 'minmax(0, 5fr) minmax(0, 7fr)',
              gap: 'var(--space-8)',
              alignItems: 'end',
            }}
          >
            <div>
              <div className="kpi-label" style={{ marginBottom: 6 }}>
                Economic Return Summary · TOTAL VALUE SAVED
              </div>
              <div
                className="kpi-value"
                style={{
                  fontSize: 'clamp(44px, 5.2vw, 72px)',
                  lineHeight: 1,
                  letterSpacing: '-0.03em',
                  color: MINT,
                }}
              >
                {money(savedShown)}
              </div>
              <div style={{ marginTop: 'var(--space-3)', fontSize: 14, color: 'var(--color-text-secondary)' }}>
                <strong
                  data-testid="roi-badge"
                  className="tabular-nums"
                  style={{ color: INK, fontFamily: 'var(--font-mono)' }}
                >
                  {fmtRoi(roiX)}x ROI
                </strong>{' '}
                on {money(totalSpend)} of fleet spend, across {data.interventions} interventions.
              </div>
            </div>

            <div>
              <div
                className="card"
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
                  padding: 'var(--space-4) 0',
                }}
              >
                <Stat label="TOTAL FLEET SPEND" value={money(totalSpend)} note={`${agentRows.length} agents billed`} />
                <div style={{ borderLeft: '1px solid var(--color-border)' }}>
                  <Stat
                    label="COST PER SUCCESS"
                    value={money(data.cost_per_successful_task_usd)}
                    note="per resolved task"
                  />
                </div>
                <div style={{ borderLeft: '1px solid var(--color-border)' }}>
                  <Stat label="WASTED SPEND" value={money(data.wasted_usd)} note="burned in loops" color={AMBER} />
                </div>
              </div>
              <div style={{ marginTop: 'var(--space-3)' }}>
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    fontFamily: 'var(--font-mono)',
                    fontSize: 12,
                    marginBottom: 5,
                  }}
                >
                  <span className="tabular-nums">
                    {tasksSucceeded} / {tasksTotal} tasks resolved
                  </span>
                  <span style={{ color: MUTED }}>{successPct.toFixed(0)}% success</span>
                </div>
                <div
                  style={{
                    display: 'flex',
                    height: 6,
                    borderRadius: 3,
                    overflow: 'hidden',
                    background: 'var(--color-state-killed-bg)',
                  }}
                >
                  <div className="meter-fill" style={{ width: `${successPct}%`, background: MINT }} />
                </div>
              </div>
            </div>
          </section>

          {/* Burn-down + per-agent ledger */}
          <div className="bento" style={{ alignItems: 'start' }}>
            <section
              className="col-span-8 card"
              aria-label="Cumulative Cost Burn-Down vs Prevented Runaway"
              style={{ padding: 'var(--space-4) var(--space-5)', minWidth: 0 }}
            >
              <h2 style={{ fontSize: 15, fontWeight: 600 }}>Cumulative Cost Burn-Down vs. Prevented Runaway</h2>
              <p style={{ fontSize: 12.5, color: MUTED, margin: '2px 0 var(--space-3)' }}>
                {horizon} min horizon. Dashed amber lines mark circuit-breaker interventions.
              </p>
              <BurnDownChart roi={data} />
            </section>

            <section className="col-span-4" aria-label="Spend vs Value Saved by Agent" style={{ minWidth: 0 }}>
              <h2 style={{ fontSize: 15, fontWeight: 600 }}>Spend vs. Value Saved by Agent</h2>
              <p style={{ fontSize: 12.5, color: MUTED, margin: '2px 0 var(--space-2)' }}>Ranked by dollars saved</p>
              <div data-testid="agent-spend-chart">
                {agentRows.map((r, i) => (
                  <div
                    key={r.id}
                    style={{
                      padding: '12px 0',
                      borderTop: '1px solid var(--color-border)',
                      display: 'grid',
                      gridTemplateColumns: '1fr auto',
                      rowGap: 6,
                    }}
                  >
                    <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700 }}>
                      <span style={{ color: MUTED, marginRight: 8 }}>{i + 1}</span>
                      {r.id}
                    </span>
                    <span
                      className="tabular-nums"
                      style={{
                        fontFamily: 'var(--font-mono)',
                        fontSize: 13,
                        color: r.saved > 0 ? MINT : MUTED,
                        textAlign: 'right',
                      }}
                    >
                      {r.saved > 0 ? `+${moneyShort(r.saved)} saved` : 'no saves'}
                    </span>
                    <span style={{ gridColumn: '1 / -1', height: 3, background: 'var(--color-border)', borderRadius: 2 }}>
                      <span
                        style={{
                          display: 'block',
                          height: '100%',
                          width: `${r.saved > 0 ? Math.max(2, (r.saved / maxSaved) * 100) : 0}%`,
                          background: MINT,
                          borderRadius: 2,
                        }}
                      />
                    </span>
                    <span
                      className="tabular-nums"
                      style={{ gridColumn: '1 / -1', fontFamily: 'var(--font-mono)', fontSize: 11.5, color: MUTED }}
                    >
                      spend {money(r.spend)} · wasted{' '}
                      <span style={{ color: r.wasted > 0 ? AMBER : MUTED }}>{money(r.wasted)}</span> · {r.ok}/
                      {r.tasks} tasks
                    </span>
                  </div>
                ))}
              </div>
            </section>
          </div>

          {/* D7: budget burn-down per agent (ECharts) with projection and PAUSE/KILL markers */}
          <section
            className="card"
            aria-label="Budget Burn-Down by Agent"
            style={{ padding: 'var(--space-4) var(--space-5)' }}
          >
            <h2 style={{ fontSize: 15, fontWeight: 600 }}>Budget Burn-Down by Agent</h2>
            <p style={{ fontSize: 12.5, color: MUTED, margin: '2px 0 var(--space-3)' }}>
              Budget left over the last 30 min. Dashed lines project the time each agent hits $0 at its current $/min;
              paused agents flatten at the <span style={{ color: AMBER }}>PAUSE</span> marker.
            </p>
            {(metricsData?.metrics.length ?? 0) === 0 ? (
              <p style={{ color: MUTED, padding: 'var(--space-6) 0' }}>
                No metrics yet. Budget lines appear once agents report spend.
              </p>
            ) : (
              <BudgetBurnDown
                metrics={metricsData?.metrics ?? []}
                actions={actionsData?.items ?? []}
                agents={fleetData?.agents ?? []}
              />
            )}
          </section>

          {/* D7: task economics by agent, worst waste first */}
          <section aria-label="Task Economics by Agent">
            <h2 style={{ fontSize: 15, fontWeight: 600 }}>Task Economics by Agent</h2>
            <p style={{ fontSize: 12.5, color: MUTED, margin: '2px 0 var(--space-2)' }}>Sorted by wasted spend</p>
            <div className="card" style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                <thead>
                  <tr style={{ color: MUTED, textAlign: 'right' }}>
                    {['agent', 'tasks', 'succeeded', 'failed', 'success rate', 'spend', 'cost / success', 'wasted'].map((h, i) => (
                      <th key={h} style={{ padding: '10px 14px', fontWeight: 600, textAlign: i === 0 ? 'left' : 'right' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {taskRows.length === 0 && (
                    <tr><td colSpan={8} style={{ padding: 14, color: MUTED }}>No task data yet.</td></tr>
                  )}
                  {taskRows.map((r) => (
                    <tr key={r.agent} style={{ borderTop: '1px solid var(--color-border)' }}>
                      <td style={{ padding: '10px 14px', fontWeight: 700 }}>{r.agent}</td>
                      <td className="tabular-nums" style={{ padding: '10px 14px', textAlign: 'right' }}>{r.tasks}</td>
                      <td className="tabular-nums" style={{ padding: '10px 14px', textAlign: 'right' }}>{r.succeeded}</td>
                      <td className="tabular-nums" style={{ padding: '10px 14px', textAlign: 'right', color: r.failed > 0 ? ROSE : undefined }}>{r.failed}</td>
                      <td className="tabular-nums" style={{ padding: '10px 14px', textAlign: 'right' }}>{(r.success_rate * 100).toFixed(1)}%</td>
                      <td className="tabular-nums" style={{ padding: '10px 14px', textAlign: 'right' }}>{money(r.spend_usd)}</td>
                      <td className="tabular-nums" style={{ padding: '10px 14px', textAlign: 'right' }}>{money(r.cost_per_success_usd)}</td>
                      <td className="tabular-nums" style={{ padding: '10px 14px', textAlign: 'right', color: r.wasted_usd > 0 ? AMBER : MUTED }}>{money(r.wasted_usd)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {/* Attribution ledger */}
          <section aria-label="Attribution Methodology">
            <h2 style={{ fontSize: 15, fontWeight: 600 }}>Attribution Methodology</h2>
            <p style={{ fontSize: 12.5, color: MUTED, margin: '2px 0 var(--space-3)' }}>
              How each saved dollar is priced. Select a row for the reasoning.
            </p>
            <div className="card" style={{ padding: '0 var(--space-4)' }}>
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
        </>
      )}
    </div>
  );
};
