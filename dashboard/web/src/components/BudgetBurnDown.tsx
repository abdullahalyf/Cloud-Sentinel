import React, { useEffect, useMemo, useRef } from 'react';
import * as echarts from 'echarts/core';
import { LineChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, MarkLineComponent, LegendComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import type { ActionRow, AgentView, MetricRow } from '../api/types';
import { actionMarkers, budgetLeftSeries, projectToZero } from '../utils/burndown';

echarts.use([LineChart, GridComponent, TooltipComponent, MarkLineComponent, LegendComponent, CanvasRenderer]);

const PALETTE = ['#22D3EE', '#818CF8', '#34D399', '#FBBF24', '#FB7185'];

interface Props {
  metrics: MetricRow[];
  actions: ActionRow[];
  agents: AgentView[];
}

/** Budget left per agent (solid), projection to $0 (dashed), PAUSE/KILL markers (vertical). */
export const BudgetBurnDown: React.FC<Props> = ({ metrics, actions, agents }) => {
  const el = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);

  const option = useMemo(() => {
    const markers = actionMarkers(actions);
    const series: unknown[] = [];
    agents.forEach((a, i) => {
      const color = PALETTE[i % PALETTE.length];
      const data = budgetLeftSeries(metrics, a.agent_id);
      series.push({
        name: a.agent_id,
        type: 'line',
        showSymbol: false,
        smooth: false,
        lineStyle: { color, width: 2 },
        itemStyle: { color },
        data,
        markLine:
          i === 0 && markers.length
            ? {
                symbol: 'none',
                silent: true,
                lineStyle: { color: '#FBBF24', type: 'dotted' },
                label: { color: '#FBBF24', fontFamily: 'JetBrains Mono', fontSize: 11, formatter: (p: { name: string }) => p.name },
                data: markers.map((m) => ({ xAxis: m.ts, name: m.label })),
              }
            : undefined,
      });
      const proj = projectToZero(data, a.usd_per_min);
      if (proj) {
        series.push({
          name: `${a.agent_id} projection`,
          type: 'line',
          showSymbol: false,
          lineStyle: { color, width: 1.5, type: 'dashed', opacity: 0.8 },
          itemStyle: { color },
          data: proj,
        });
      }
    });
    return {
      animation: false,
      grid: { left: 56, right: 16, top: 16, bottom: 28 },
      tooltip: { trigger: 'axis', backgroundColor: '#080C14', borderColor: 'rgba(255,255,255,0.14)', textStyle: { color: '#E6EDF6', fontFamily: 'JetBrains Mono', fontSize: 11 } },
      xAxis: {
        type: 'time',
        axisLine: { lineStyle: { color: 'rgba(255,255,255,0.15)' } },
        axisLabel: { color: '#8A97AB', fontFamily: 'JetBrains Mono', fontSize: 10.5 },
        splitLine: { show: false },
      },
      yAxis: {
        type: 'value',
        min: 0,
        axisLabel: { color: '#8A97AB', fontFamily: 'JetBrains Mono', fontSize: 10.5, formatter: (v: number) => `$${v.toFixed(2)}` },
        splitLine: { lineStyle: { color: 'rgba(255,255,255,0.07)' } },
      },
      series,
    };
  }, [metrics, actions, agents]);

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

  return <div ref={el} data-testid="budget-burndown" role="img" aria-label="Budget left per agent over time with projection to zero and pause or kill markers" style={{ width: '100%', height: 300 }} />;
};
