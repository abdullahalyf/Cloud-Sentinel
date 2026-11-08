import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter } from 'react-router-dom';
import { FleetView, sortFleetAgents } from '../FleetView';
import { api, ApiError } from '../../api/client';
import type { AgentView, FleetResponse, RoiReport } from '../../api/types';

const mockAgents: AgentView[] = [
  {
    agent_id: 'alpha',
    display_name: 'alpha',
    runtime: 'docker',
    state: 'healthy',
    budget_usd: 0.5,
    spend_usd: 0.05,
    total_tokens: 5000,
    tokens_per_min: 4000,
    usd_per_min: 0.016,
    calls_per_sec: 0.2,
    exact_repeats: 0,
    loop_score: 0.05,
    tool_cycle: false,
    memory_pct: 10.0,
    baseline: {},
    last_verdict: null,
    updated_at: '2026-11-08T17:00:00Z',
  },
  {
    agent_id: 'beta',
    display_name: 'beta',
    runtime: 'docker',
    state: 'paused',
    budget_usd: 0.5,
    spend_usd: 0.2,
    total_tokens: 15000,
    tokens_per_min: 12000,
    usd_per_min: 0.048,
    calls_per_sec: 1.0,
    exact_repeats: 3,
    loop_score: 0.88,
    tool_cycle: true,
    memory_pct: 35.0,
    baseline: {},
    last_verdict: {
      agent_id: 'beta',
      source: 'claude',
      action: 'PAUSE',
      confidence: 0.95,
      pattern: 'semantic_loop',
      reason: 'Repeated order queries',
    },
    updated_at: '2026-11-08T17:00:00Z',
  },
  {
    agent_id: 'gamma',
    display_name: 'gamma',
    runtime: 'docker',
    state: 'killed',
    budget_usd: 1.0,
    spend_usd: 0.9,
    total_tokens: 80000,
    tokens_per_min: 80000,
    usd_per_min: 0.32,
    calls_per_sec: 5.0,
    exact_repeats: 1,
    loop_score: 0.1,
    tool_cycle: false,
    memory_pct: 95.0,
    baseline: {},
    last_verdict: null,
    updated_at: '2026-11-08T17:00:00Z',
  },
  {
    agent_id: 'delta',
    display_name: 'delta',
    runtime: 'docker',
    state: 'healthy',
    budget_usd: 0.2,
    spend_usd: 0.02,
    total_tokens: 3000,
    tokens_per_min: 2500,
    usd_per_min: 0.01,
    calls_per_sec: 0.1,
    exact_repeats: 0,
    loop_score: 0.02,
    tool_cycle: false,
    memory_pct: 8.0,
    baseline: {},
    last_verdict: null,
    updated_at: '2026-11-08T17:00:00Z',
  },
];

const mockRoi: RoiReport = {
  total_spend_usd: 1.17,
  spend_by_agent: { alpha: 0.05, beta: 0.2, gamma: 0.9, delta: 0.02 },
  saved_usd: 142.5,
  saved_by_action: [],
  interventions: 2,
  tool_calls_held: 1,
  tasks_total: 50,
  tasks_succeeded: 45,
  cost_per_successful_task_usd: 0.026,
  wasted_usd: 0.12,
  tasks_by_agent: {},
  horizon_minutes: 60.0,
  formula: 'Mock formula',
};

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>{children}</BrowserRouter>
    </QueryClientProvider>
  );
};

describe('FleetView (src/views/FleetView.tsx)', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  describe('sortFleetAgents unit logic', () => {
    it('sorts killed and paused agents first, then by usd_per_min descending', () => {
      const sorted = sortFleetAgents(mockAgents);
      const ids = sorted.map((a) => a.agent_id);
      // gamma (killed, $0.32) and beta (paused, $0.048) must come before alpha and delta.
      // Between gamma and beta, gamma has higher $/min.
      // Between alpha ($0.016) and delta ($0.01), alpha has higher $/min.
      expect(ids).toEqual(['gamma', 'beta', 'alpha', 'delta']);
    });
  });

  describe('Component rendering & interactions', () => {
    it('renders Bento KPI strip and sorted agent cards', async () => {
      vi.spyOn(api, 'getFleet').mockResolvedValue({ agents: mockAgents } as FleetResponse);
      vi.spyOn(api, 'getRoi').mockResolvedValue(mockRoi);

      render(<FleetView />, { wrapper: createWrapper() });

      // Check header
      expect(screen.getByText('Fleet Telemetry Control')).toBeInTheDocument();

      // Check Bento KPI metrics
      await waitFor(() => {
        expect(screen.getByText('$142.5000')).toBeInTheDocument();
      });
      expect(screen.getByText('$1.1700')).toBeInTheDocument();

      // Check agent cards
      expect(screen.getByText('alpha')).toBeInTheDocument();
      expect(screen.getByText('beta')).toBeInTheDocument();
      expect(screen.getByText('gamma')).toBeInTheDocument();
      expect(screen.getByText('delta')).toBeInTheDocument();
    });

    it('filters agent cards by state when filter button is clicked', async () => {
      vi.spyOn(api, 'getFleet').mockResolvedValue({ agents: mockAgents } as FleetResponse);
      vi.spyOn(api, 'getRoi').mockResolvedValue(mockRoi);

      render(<FleetView />, { wrapper: createWrapper() });

      await waitFor(() => {
        expect(screen.getByText('beta')).toBeInTheDocument();
      });

      // Click "PAUSED (1)" filter button
      const pausedFilterBtn = screen.getByRole('button', { name: /filter by paused/i });
      fireEvent.click(pausedFilterBtn);

      // Now only beta should be in the grid
      expect(screen.getByText('beta')).toBeInTheDocument();
      expect(screen.queryByText('alpha')).not.toBeInTheDocument();
      expect(screen.queryByText('gamma')).not.toBeInTheDocument();
      expect(screen.queryByText('delta')).not.toBeInTheDocument();
    });

    it('renders empty state when fleet has no agents', async () => {
      vi.spyOn(api, 'getFleet').mockResolvedValue({ agents: [] } as FleetResponse);
      vi.spyOn(api, 'getRoi').mockResolvedValue({ ...mockRoi, saved_usd: 0, total_spend_usd: 0 });

      render(<FleetView />, { wrapper: createWrapper() });

      await waitFor(() => {
        expect(screen.getByText('No Agents Running')).toBeInTheDocument();
      });
      expect(
        screen.getByText('No agents yet: start one with python -m brain --fake')
      ).toBeInTheDocument();
    });

    it('renders error state with retry button when query fails', async () => {
      vi.spyOn(api, 'getFleet').mockRejectedValue(
        new ApiError(500, 'Database connection timeout on :8000')
      );
      vi.spyOn(api, 'getRoi').mockResolvedValue(mockRoi);

      render(<FleetView />, { wrapper: createWrapper() });

      await waitFor(() => {
        expect(screen.getByRole('alert')).toBeInTheDocument();
      });
      expect(screen.getByText(/Database connection timeout on :8000/)).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
    });
  });
});
