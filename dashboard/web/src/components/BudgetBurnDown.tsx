import React, { useEffect, useMemo, useRef } from 'react';
import * as echarts from 'echarts/core';
import { LineChart, ScatterChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import type { ActionRow, AgentView, MetricRow } from '../api/types';
import { budgetLeftSeries, clipProjection, projectToZero, viewWindow } from '../utils/burndown';
import { buildEventDots, dotCard, legendFor, type EventDot } from '../utils/eventDots';

echarts.use([LineChart, ScatterChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer]);

// ECharts cannot read CSS variables, so these mirror the --chart-* tokens
const PALETTE = ['#3b1fe8', '#12c8e8', '#b944db', '#f5b83d', '#f0402f'];
const TEXT = '#6a6578';
const INK = '#191222';

interface Props {
  metrics: MetricRow[];
  actions: ActionRow[];
  agents: AgentView[];
}

/** Budget left; an agent that overshot its budget shows how far over instead of a negative amount. */
export const budgetText = (v: number): string => (v < 0 ? `over by $${Math.abs(v).toFixed(2)}` : `$${v.toFixed(2)}`);

/** Agent text goes into tooltip HTML, so it must be escaped. */
export const esc = (s: string): string =>
  s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');

export function dotCardHtml(d: EventDot): string {
  const c = dotCard(d);
  const rows = c.lines.map((l) => `<div style="margin-top:3px;color:${INK}">${esc(l)}</div>`).join('');
  return (
    `<div style="min-width:210px;max-width:320px;white-space:normal;line-height:1.35">` +
    `<div style="display:flex;align-items:center;gap:8px;font-weight:700"><span style="width:10px;height:10px;border-radius:50%;background:${d.color};display:inline-block"></span>${esc(c.title)}</div>` +
    `<div style="color:${TEXT};margin:4px 0 6px">${esc(c.meaning)}</div>${rows}</div>`
  );
}

/** Budget left per agent (solid), projection to $0 (dashed), and one coloured dot per circuit-breaker event on the agent's line. */
export const BudgetBurnDown: React.FC<Props> = ({ metrics, actions, agents }) => {
  const el = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);

  const model = useMemo(() => {
    const per = agents.map((a) => ({ agent: a, data: budgetLeftSeries(metrics, a.agent_id) }));
    const win = viewWindow(per.map((p) => p.data));
    const byAgent = Object.fromEntries(per.map((p) => [p.agent.agent_id, p.data]));
    const dots = win ? buildEventDots(actions, byAgent, win.from, win.to) : [];
    return { per, win, dots };
  }, [metrics, actions, agents]);

  const option = useMemo(() => {
    const { per, win, dots } = model;
    const series: unknown[] = [];
    per.forEach(({ agent: a, data }, i) => {
      const color = PALETTE[i % PALETTE.length];
      series.push({
        name: a.agent_id,
        type: 'line',
        showSymbol: false,
        smooth: false,
        lineStyle: { color, width: 2 },
        itemStyle: { color },
        data,
      });
      const proj = win ? clipProjection(projectToZero(data, a.usd_per_min), win.max) : null;
      if (proj) {
        series.push({
          name: `${a.agent_id} projection`,
          type: 'line',
          showSymbol: false,
          lineStyle: { color, width: 1.5, type: 'dashed', opacity: 0.8 },
          itemStyle: { color },
          data: proj,
          tooltip: { show: false },
        });
      }
    });
    if (dots.length) {
      series.push({
        name: 'Circuit-breaker events',
        type: 'scatter',
        z: 10,
        data: dots.map((d) => ({
          value: [d.ts, d.value],
          dot: d,
          symbolSize: d.count > 1 ? 20 : 14,
          itemStyle: { color: d.color, borderColor: '#ffffff', borderWidth: 2.5, shadowBlur: 8, shadowColor: 'rgba(34,28,80,0.35)' },
          label: { show: d.count > 1, formatter: String(d.count), color: '#ffffff', fontSize: 10, fontWeight: 700, fontFamily: 'Urbanist' },
        })),
        emphasis: { scale: 1.3 },
        tooltip: {
          trigger: 'item',
          formatter: (p: { data?: { dot?: EventDot } }) => (p.data?.dot ? dotCardHtml(p.data.dot) : ''),
        },
      });
    }
    return {
      animation: false,
      grid: { left: 56, right: 24, top: 16, bottom: 30 },
      tooltip: {
        trigger: 'axis',
        backgroundColor: '#fafaff',
        borderColor: 'rgba(25,18,34,0.09)',
        extraCssText: 'box-shadow:0 18px 44px -12px rgba(34,28,80,.35);border-radius:14px;',
        textStyle: { color: INK, fontFamily: 'Urbanist', fontSize: 12 },
        // the line tooltip lists budget left per agent; dots have their own card
        formatter: (params: unknown) => {
          const arr = (Array.isArray(params) ? params : [params]) as { seriesType: string; seriesName: string; marker: string; value: [number, number]; axisValue: number }[];
          const lines = arr.filter((p) => p.seriesType === 'line');
          if (!lines.length) return '';
          const head = `<div style="color:${TEXT};margin-bottom:4px">${new Date(lines[0].axisValue).toLocaleTimeString()}</div>`;
          return head + lines.map((p) => `<div style="display:flex;justify-content:space-between;gap:18px">${p.marker}<span style="flex:1">${esc(p.seriesName)}</span><b>${budgetText(Number(p.value[1]))}</b></div>`).join('');
        },
      },
      xAxis: {
        type: 'time',
        min: win ? win.from : undefined,
        max: win ? win.max : undefined,
        axisLine: { lineStyle: { color: 'rgba(25,18,34,0.25)' } },
        axisLabel: { color: TEXT, fontFamily: 'Urbanist', fontSize: 10.5 },
        splitLine: { show: false },
      },
      yAxis: {
        type: 'value',
        min: 0,
        axisLabel: { color: TEXT, fontFamily: 'Urbanist', fontSize: 10.5, formatter: (v: number) => `$${v.toFixed(2)}` },
        splitLine: { lineStyle: { color: 'rgba(25,18,34,0.07)' } },
      },
      series,
    };
  }, [model]);

  useEffect(() => {
    if (!el.current) return;
    try {
      chart.current = echarts.init(el.current, undefined, { renderer: 'canvas' });
    } catch {
      return; // no canvas (tests): the table below still shows the data
    }
    const ro = new ResizeObserver(() => chart.current?.resize());
    ro.observe(el.current);
    return () => {
      ro.disconnect();
      chart.current?.dispose();
      chart.current = null;
    };
  }, []);

  useEffect(() => {
    chart.current?.setOption(option as echarts.EChartsCoreOption, true);
  }, [option]);

  const legend = legendFor(model.dots);

  return (
    <div>
      <div ref={el} data-testid="budget-burndown" role="img" aria-label="Budget left per agent over time, with a dot for each circuit-breaker event" style={{ width: '100%', height: 300 }} />
      <div data-testid="burndown-legend" style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '8px 16px', marginTop: 8, fontSize: 12.5, color: 'var(--color-text-secondary)' }}>
        {legend.length > 0 ? (
          <>
            <span style={{ color: 'var(--color-text-muted)' }}>Each dot is something the circuit breaker did to that agent. Hover one to see what:</span>
            {legend.map((l) => (
              <span key={l.name} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                <span style={{ width: 11, height: 11, borderRadius: '50%', background: l.color, boxShadow: '0 0 0 2px #fff, 0 0 0 3px rgba(25,18,34,0.12)' }} />
                {l.name}
              </span>
            ))}
          </>
        ) : (
          <span style={{ color: 'var(--color-text-muted)' }}>No circuit-breaker events in this window.</span>
        )}
      </div>
    </div>
  );
};
