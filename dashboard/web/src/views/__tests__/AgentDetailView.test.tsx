import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { AgentDetailView } from '../AgentDetailView';
import { api, ApiError } from '../../api/client';
import { ToastProvider } from '../../components/Toast';

vi.mock('../../api/client', () => ({
  api: {
    getAgent: vi.fn(),
    getAgentNodes: vi.fn(),
    getMemoryHistory: vi.fn(),
    getToolCalls: vi.fn(),
    postCommand: vi.fn(),
    getMemory: vi.fn(),
    putMemory: vi.fn(),
    decideToolCall: vi.fn(),
  },
  ApiError: class ApiError extends Error {
    status: number;
    detail: string;
    constructor(status: number, detail: string) {
      super(`API Error ${status}: ${detail}`);
      this.name = 'ApiError';
      this.status = status;
      this.detail = detail;
    }
  },
}));

const mockAgentData = {
  agent: {
    agent_id: 'beta',
    display_name: 'Beta Worker',
    runtime: 'langgraph',
    state: 'paused',
    budget_usd: 5.0,
    spend_usd: 4.3,
    total_tokens: 450000,
    tokens_per_min: 75000,
    usd_per_min: 0.15,
    calls_per_sec: 1.2,
    exact_repeats: 14,
    loop_score: 0.88,
    tool_cycle: true,
    memory_pct: 42,
    baseline: {},
    last_verdict: {
      agent_id: 'beta',
      source: 'claude',
      action: 'PAUSE',
      confidence: 0.93,
      pattern: 'semantic_loop',
      reason: 'Repeated order 4471 queries in a tight loop',
      suggested_fix: 'Set memory "order_4471" to "cancelled - skip it and move on" so the agent stops retrying.',
      latency_ms: 812,
    },
    updated_at: '2026-11-08T12:00:00Z',
  },
  spans: [
    {
      span_id: 'span-001',
      trace_id: 'trace-001',
      agent_id: 'beta',
      operation: 'tool_execution',
      name: 'lookup_order',
      duration_ms: 120.5,
      cost_usd: 0.0025,
      status: 'error',
      tool_args: { order_id: 4471 },
    },
  ],
  verdicts: [
    {
      id: 1,
      agent_id: 'beta',
      source: 'claude',
      action: 'PAUSE',
      confidence: 0.93,
      pattern: 'semantic_loop',
      reason: 'Repeated order 4471 queries in a tight loop',
      suggested_fix: 'Set memory "order_4471" to "cancelled - skip it and move on" so the agent stops retrying.',
    },
  ],
  memory: {
    id: 1,
    agent_id: 'beta',
    version: 1,
    content: {
      order_4471: 'orders API returned 500 - retry until success',
    },
    edited_by: 'agent',
    reason: 'Initial retry belief',
    created_at: '2026-11-08T11:50:00Z',
  },
};

const mockNodesData = {
  items: [
    {
      ts: 100,
      node: 'lookup_order',
      step: 1,
      framework: 'langgraph',
      changed: { status: 'error' },
      next: 'retry',
      status: 'error',
      duration_ms: 120,
      trace_id: 'run-1',
    },
  ],
  edges: [{ source: 'lookup_order', target: 'retry', count: 14 }],
  last_node: 'lookup_order',
  next_node: 'retry',
};

const mockHistoryData = {
  items: [
    {
      id: 1,
      agent_id: 'beta',
      version: 1,
      content: { order_4471: 'orders API returned 500 - retry until success' },
      edited_by: 'agent',
      reason: 'Initial state',
      created_at: '2026-11-08T11:50:00Z',
    },
  ],
};

const mockToolCallsData = {
  items: [
    {
      id: 101,
      agent_id: 'beta',
      tool_name: 'issue_refund',
      args: { order_id: 4471, amount: 50000 },
      decision: 'pending',
      final_args: {},
      decided_by: '',
      reason: 'Refund exceeds safety limit',
      value_usd: 450.0,
      created_at: '2026-11-08T11:55:00Z',
    },
  ],
};

function renderComponent() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: 0 } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <MemoryRouter initialEntries={['/agents/beta']}>
          <Routes>
            <Route path="/agents/:id" element={<AgentDetailView />} />
          </Routes>
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}

describe('AgentDetailView C2 Tests', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.getAgent).mockResolvedValue(mockAgentData as any);
    vi.mocked(api.getAgentNodes).mockResolvedValue(mockNodesData as any);
    vi.mocked(api.getMemoryHistory).mockResolvedValue(mockHistoryData as any);
    vi.mocked(api.getToolCalls).mockResolvedValue(mockToolCallsData as any);
    vi.mocked(api.postCommand).mockResolvedValue({ id: 99, status: 'pending' });
    vi.mocked(api.putMemory).mockResolvedValue({
      id: 2,
      agent_id: 'beta',
      version: 2,
      content: { order_4471: 'cancelled - skip it and move on' },
      edited_by: 'human',
      reason: 'Fixed loop',
      created_at: '2026-11-08T12:05:00Z',
    });
    vi.mocked(api.decideToolCall).mockResolvedValue({
      id: 101,
      agent_id: 'beta',
      tool_name: 'issue_refund',
      args: { order_id: 4471, amount: 50000 },
      decision: 'rewrite',
      final_args: { order_id: 4471, amount: 5000 },
      decided_by: 'human',
      reason: 'Capped refund',
      value_usd: 45.0,
      created_at: '2026-11-08T11:55:00Z',
    });
  });

  it('renders agent status, command bar, memory, tools, and spans', async () => {
    renderComponent();

    expect(await screen.findByText(/ACTION: PAUSE/i)).toBeInTheDocument();
    expect(screen.getByTestId('command-bar')).toBeInTheDocument();
    expect(screen.getByTestId('command-pause-btn')).toBeInTheDocument();
    expect(screen.getByTestId('command-resume-btn')).toBeInTheDocument();
    expect(screen.getByTestId('command-kill-btn')).toBeInTheDocument();

    // Check verdict panel
    expect(screen.getByText(/Safety Engine Verdict/i)).toBeInTheDocument();
    expect(screen.getByText(/semantic_loop/i)).toBeInTheDocument();

    // Check tool call table
    expect(screen.getByText(/issue_refund/i)).toBeInTheDocument();
    expect(screen.getByTestId('tool-approve-btn')).toBeInTheDocument();
    expect(screen.getByTestId('tool-deny-btn')).toBeInTheDocument();
    expect(screen.getByTestId('tool-rewrite-btn')).toBeInTheDocument();

    // Check spans table
    const spansTable = screen.getByTestId('spans-table');
    expect(spansTable).toBeInTheDocument();
    expect(within(spansTable).getByText(/lookup_order/i)).toBeInTheDocument();
  });

  it('handles kill confirm dialog and cancels with Esc key without dispatching command', async () => {
    renderComponent();

    await screen.findByText(/ACTION: PAUSE/i);

    const killBtn = screen.getByTestId('command-kill-btn');
    fireEvent.click(killBtn);

    // Dialog opens
    expect(screen.getByTestId('confirm-dialog')).toBeInTheDocument();
    expect(screen.getByText(/Confirm Kill Action/i)).toBeInTheDocument();

    // Press Escape
    fireEvent.keyDown(window, { key: 'Escape' });

    // Dialog closes
    await waitFor(() => {
      expect(screen.queryByTestId('confirm-dialog')).not.toBeInTheDocument();
    });

    expect(api.postCommand).not.toHaveBeenCalled();

    // Open again and confirm with reason
    fireEvent.click(killBtn);
    const reasonInput = screen.getByTestId('confirm-reason-input');
    fireEvent.change(reasonInput, { target: { value: 'Terminating runaway node' } });

    const submitBtn = screen.getByTestId('confirm-submit-btn');
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(api.postCommand).toHaveBeenCalledWith('beta', {
        command: 'KILL',
        requested_by: 'dashboard',
        reason: 'Terminating runaway node',
        params: undefined,
      });
    });
  });

  it('applies suggested fix to memory editor without auto-saving', async () => {
    renderComponent();

    const applyBtn = await screen.findByTestId('apply-suggestion-btn');
    expect(applyBtn).toBeInTheDocument();

    fireEvent.click(applyBtn);

    // Verify textarea was updated with patched key and value
    const textarea = screen.getByTestId('json-editor-textarea') as HTMLTextAreaElement;
    expect(textarea.value).toContain('cancelled - skip it and move on');

    // api.putMemory was NOT automatically called
    expect(api.putMemory).not.toHaveBeenCalled();

    // Reason input was auto-populated
    const reasonInput = screen.getByTestId('memory-reason-input') as HTMLInputElement;
    expect(reasonInput.value).toContain('semantic_loop');
  });

  it('blocks saving memory when JSON is invalid', async () => {
    renderComponent();

    await screen.findByText(/ACTION: PAUSE/i);

    const textarea = screen.getByTestId('json-editor-textarea');
    fireEvent.change(textarea, { target: { value: '{"order_4471": invalid_unquoted_value}' } });

    // Inline error appears
    expect(await screen.findByTestId('json-editor-error')).toBeInTheDocument();

    // Provide reason
    const reasonInput = screen.getByTestId('memory-reason-input');
    fireEvent.change(reasonInput, { target: { value: 'Test invalid save' } });

    // Save button is disabled
    const saveBtn = screen.getByTestId('memory-save-btn');
    expect(saveBtn).toBeDisabled();

    fireEvent.click(saveBtn);
    expect(api.putMemory).not.toHaveBeenCalled();
  });

  it('handles 409 conflict flow with reload and overwrite options', async () => {
    vi.mocked(api.putMemory).mockRejectedValueOnce(
      new ApiError(409, 'memory changed by a human; reload it first')
    );

    renderComponent();

    await screen.findByText(/ACTION: PAUSE/i);

    const reasonInput = screen.getByTestId('memory-reason-input');
    fireEvent.change(reasonInput, { target: { value: 'Operator belief update' } });

    const saveBtn = screen.getByTestId('memory-save-btn');
    fireEvent.click(saveBtn);

    // 409 banner appears
    expect(await screen.findByTestId('memory-conflict-banner')).toBeInTheDocument();
    expect(screen.getByText(/Someone else changed the memory/i)).toBeInTheDocument();

    // Reload button works
    vi.mocked(api.getMemory).mockResolvedValueOnce({
      id: 5,
      agent_id: 'beta',
      version: 2,
      content: { order_4471: 'reloaded_value' },
      edited_by: 'human',
      reason: 'Concurrent human fix',
      created_at: '2026-11-08T12:10:00Z',
    });

    const reloadBtn = screen.getByTestId('conflict-reload-btn');
    fireEvent.click(reloadBtn);

    await waitFor(() => {
      expect(api.getMemory).toHaveBeenCalledWith('beta');
      expect(screen.queryByTestId('memory-conflict-banner')).not.toBeInTheDocument();
    });

    // Test overwrite path: mock another 409 and test overwrite
    vi.mocked(api.putMemory).mockRejectedValueOnce(
      new ApiError(409, 'memory changed by a human; reload it first')
    );
    fireEvent.change(screen.getByTestId('memory-reason-input'), { target: { value: 'Force update' } });
    fireEvent.click(screen.getByTestId('memory-save-btn'));

    expect(await screen.findByTestId('memory-conflict-banner')).toBeInTheDocument();

    const overwriteBtn = screen.getByTestId('conflict-overwrite-btn');
    fireEvent.click(overwriteBtn);

    await waitFor(() => {
      // Overwrite passes base_version: null
      expect(api.putMemory).toHaveBeenCalledWith('beta', expect.objectContaining({
        base_version: null,
      }));
    });
  });

  it('opens rewrite modal for pending tool call and sends final_args', async () => {
    renderComponent();

    const rewriteBtn = await screen.findByTestId('tool-rewrite-btn');
    fireEvent.click(rewriteBtn);

    // Rewrite modal opens
    expect(screen.getByTestId('rewrite-dialog')).toBeInTheDocument();
    expect(screen.getByText(/Rewrite Tool Call: issue_refund/i)).toBeInTheDocument();

    // Change args inside modal textarea
    const argsTextarea = screen.getByTestId('rewrite-json-editor').querySelector('textarea');
    expect(argsTextarea).not.toBeNull();
    fireEvent.change(argsTextarea!, {
      target: { value: JSON.stringify({ order_id: 4471, amount: 5000 }, null, 2) },
    });

    // Change rewrite reason
    const reasonInput = screen.getByTestId('rewrite-reason-input');
    fireEvent.change(reasonInput, { target: { value: 'Reduced refund amount to 5,000 BDT limit' } });

    // Submit rewrite
    const submitRewriteBtn = screen.getByTestId('rewrite-submit-btn');
    fireEvent.click(submitRewriteBtn);

    await waitFor(() => {
      expect(api.decideToolCall).toHaveBeenCalledWith(101, {
        decision: 'rewrite',
        final_args: { order_id: 4471, amount: 5000 },
        decided_by: 'human',
        reason: 'Reduced refund amount to 5,000 BDT limit',
      });
    });

    // Dialog closes
    await waitFor(() => {
      expect(screen.queryByTestId('rewrite-dialog')).not.toBeInTheDocument();
    });
  });
});
