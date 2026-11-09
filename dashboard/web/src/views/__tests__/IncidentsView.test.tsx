import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { IncidentsView } from '../IncidentsView';
import { api } from '../../api/client';
import type { MetricRow } from '../../api/types';

const iso = (s: number) => new Date(Date.UTC(2026, 10, 8, 3, 0, s)).toISOString();
const t = (s: number) => Date.UTC(2026, 10, 8, 3, 0, s);
const metric = (s: number, state: string, loop: number) =>
  ({ agent_id: 'beta', state, tokens_per_min: 0, usd_per_min: 0.05, calls_per_sec: 0, total_tokens: 0, spend_usd: 0, budget_usd: 1, exact_repeats: 0, loop_score: loop, tool_cycle: false, memory_mb: 0, memory_pct: 0, created_at: iso(s) }) as MetricRow;

const wrap = (url = '/incidents') => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route path="/incidents" element={<IncidentsView />} />
          <Route path="/incidents/:incidentId" element={<IncidentsView />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
};

describe('IncidentsView replay', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, 'getAlerts').mockResolvedValue({ items: [{ id: 1, agent_id: 'beta', severity: 'warning', rule: 'loop', message: 'looping', created_at: iso(0) }] });
    vi.spyOn(api, 'getVerdicts').mockResolvedValue({ items: [{ agent_id: 'beta', source: 'claude', action: 'PAUSE', confidence: 0.9, pattern: 'p', reason: 'Same intent repeated', created_at: iso(20) }] });
    vi.spyOn(api, 'getActions').mockResolvedValue({ items: [{ id: 2, agent_id: 'beta', action: 'PAUSE', actor: 'claude', reason: 'loop', usd_saved_estimate: 2.52, created_at: iso(30) }] });
    vi.spyOn(api, 'getMetrics').mockResolvedValue({ metrics: [metric(0, 'healthy', 0.1), metric(25, 'suspicious', 0.7), metric(35, 'paused', 0.9)] });
    vi.spyOn(api, 'getMemoryHistory').mockResolvedValue({ items: [] });
  });

  it('lists the incident with outcome and $ saved', async () => {
    wrap();
    expect(await screen.findByRole('option', { name: /Incident beta/ })).toBeInTheDocument();
    expect(screen.getByText(/\+\$2\.52 saved/)).toBeInTheDocument();
    expect(screen.getByText('paused')).toBeInTheDocument();
  });

  it('scrubbing changes the state, loop score and verdict shown', async () => {
    wrap();
    const slider = await screen.findByLabelText('Replay scrubber');
    // start of the incident: healthy, no verdict yet
    await waitFor(() => expect(screen.getByTestId('incident-snapshot')).toHaveTextContent('No verdict yet'));
    fireEvent.change(slider, { target: { value: String(t(30)) } });
    await waitFor(() => expect(screen.getByTestId('incident-snapshot')).toHaveTextContent('Same intent repeated'));
    expect(screen.getByTestId('incident-snapshot')).toHaveTextContent('0.70');
    fireEvent.change(slider, { target: { value: String(t(34)) } });
    fireEvent.keyDown(slider, { key: 'ArrowRight' });
    await waitFor(() => expect(screen.getByTestId('incident-snapshot')).toHaveTextContent('0.90'));
  });

  it('opens a shared link at the right incident and moment (D16)', async () => {
    const id = `beta-${t(0)}`;
    wrap(`/incidents/${id}?t=${t(30)}`);
    await waitFor(() => expect(screen.getByTestId('incident-snapshot')).toHaveTextContent('Same intent repeated'));
    expect(screen.getByTestId('incident-snapshot')).toHaveTextContent('0.70');
    expect(screen.getByRole('button', { name: 'Copy share link' })).toBeInTheDocument();
  });

  it('shows the empty state when nothing happened', async () => {
    vi.spyOn(api, 'getAlerts').mockResolvedValue({ items: [] });
    vi.spyOn(api, 'getVerdicts').mockResolvedValue({ items: [] });
    vi.spyOn(api, 'getActions').mockResolvedValue({ items: [] });
    wrap();
    expect(await screen.findByText('Zero Active Incidents')).toBeInTheDocument();
  });
});
