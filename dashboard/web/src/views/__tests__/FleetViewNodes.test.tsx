import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter } from 'react-router-dom';
import { FleetView } from '../FleetView';
import { api } from '../../api/client';
import type { AgentView, RoiReport } from '../../api/types';

const agent = (id: string, runtime: string): AgentView => ({
  agent_id: id, display_name: id, runtime, state: 'healthy', budget_usd: 1, spend_usd: 0.1, total_tokens: 1,
  tokens_per_min: 100, usd_per_min: 0.01, calls_per_sec: 0, exact_repeats: 0, loop_score: 0, tool_cycle: false,
  memory_pct: 1, baseline: {}, last_verdict: null, updated_at: '2026-11-08T17:00:00Z',
});
const roi = { total_spend_usd: 1, spend_by_agent: {}, saved_usd: 0, saved_by_action: [], interventions: 0, tool_calls_held: 0, tasks_total: 0, tasks_succeeded: 0, cost_per_successful_task_usd: 0, wasted_usd: 0, tasks_by_agent: {}, horizon_minutes: 60, formula: '' } as RoiReport;

const wrap = () =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <BrowserRouter><FleetView /></BrowserRouter>
    </QueryClientProvider>
  );

describe('FleetView multi-node grouping (D15)', () => {
  it('shows a BY NODE toggle only when runtimes carry a node, and groups cards under node headers', async () => {
    vi.spyOn(api, 'getFleet').mockResolvedValue({ agents: [agent('alpha', 'docker@n1'), agent('beta', 'docker@n2')] });
    vi.spyOn(api, 'getRoi').mockResolvedValue(roi);
    wrap();
    const toggle = await screen.findByRole('button', { name: 'Group agents by node' });
    fireEvent.click(toggle);
    await waitFor(() => expect(screen.getByText(/node: n1 · 1 agent$/)).toBeInTheDocument());
    expect(screen.getByText(/node: n2 · 1 agent$/)).toBeInTheDocument();
  });

  it('hides the toggle on a single-node fleet', async () => {
    vi.spyOn(api, 'getFleet').mockResolvedValue({ agents: [agent('alpha', 'docker')] });
    vi.spyOn(api, 'getRoi').mockResolvedValue(roi);
    wrap();
    await screen.findByText('alpha');
    expect(screen.queryByRole('button', { name: 'Group agents by node' })).not.toBeInTheDocument();
  });
});
