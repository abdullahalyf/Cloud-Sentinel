import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ApprovalsView, formatWaiting, orderCards } from '../ApprovalsView';
import { ToastProvider } from '../../components/Toast';
import { api } from '../../api/client';
import type { HealProposalRow, ToolCallRow } from '../../api/types';

const call = (id: number, created: string, agent = 'delta'): ToolCallRow => ({
  id,
  agent_id: agent,
  tool_name: 'issue_refund',
  args: { amount: 50000, order: 'o1' },
  decision: 'pending',
  final_args: {},
  decided_by: '',
  reason: 'amount over limit',
  value_usd: 50000,
  created_at: created,
});

const heal: HealProposalRow = {
  id: 7,
  agent_id: 'beta',
  kind: 'memory_patch',
  patch: { memory: [{ op: 'set', key: 'order_4471', value: 'cancelled' }] },
  confidence: 0.71,
  status: 'pending',
  verdict_id: 1,
  base_version: 1,
  reason: 'looping on a failing order',
  decided_by: '',
  decided_at: '',
  created_at: '2026-11-08T03:00:00Z',
};

const wrap = (ui: React.ReactElement) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>{ui}</ToastProvider>
    </QueryClientProvider>
  );
};

describe('ApprovalsView helpers', () => {
  it('orders cards oldest first, tool calls before heals', () => {
    const order = orderCards([call(2, '2026-11-08T02:00:02Z'), call(1, '2026-11-08T02:00:01Z')], [heal]);
    expect(order).toEqual(['tool-1', 'tool-2', 'heal-7']);
  });
  it('formats waiting time', () => {
    const t = new Date('2026-11-08T02:00:00Z').getTime();
    expect(formatWaiting('2026-11-08T02:00:00Z', t + 12_000)).toBe('12s');
    expect(formatWaiting('2026-11-08T02:00:00Z', t + 185_000)).toBe('3m 05s');
    expect(formatWaiting('2026-11-08T02:00:00Z', t + 65_000_000)).toBe('18h 03m');
    expect(formatWaiting('2026-11-08T02:00:00Z', t + 65_000_000)).toBe('18h 03m');
  });
});

describe('ApprovalsView', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, 'getToolCalls').mockResolvedValue({ items: [call(1, '2026-11-08T02:00:01Z'), call(2, '2026-11-08T02:00:02Z')] });
    vi.spyOn(api, 'getHealProposals').mockResolvedValue({ items: [heal] });
    vi.spyOn(api, 'getMemory').mockResolvedValue({ agent_id: 'beta', version: 1, content: { order_4471: 'retry until success' }, edited_by: 'agent', reason: '', created_at: '' });
  });

  it('approves with the button', async () => {
    const decide = vi.spyOn(api, 'decideToolCall').mockResolvedValue(call(1, ''));
    wrap(<ApprovalsView />);
    fireEvent.click(await screen.findByRole('button', { name: 'Approve tool call 1' }));
    await waitFor(() => expect(decide).toHaveBeenCalled());
    expect(decide.mock.calls[0][0]).toBe(1);
    expect(decide.mock.calls[0][1]).toMatchObject({ decision: 'allow', decided_by: 'human' });
  });

  it('J moves to the next card and D denies it from the keyboard', async () => {
    const decide = vi.spyOn(api, 'decideToolCall').mockResolvedValue(call(2, ''));
    wrap(<ApprovalsView />);
    await screen.findByTestId('tool-card-2');
    await waitFor(() => expect(screen.getByTestId('tool-card-1')).toHaveAttribute('data-selected', 'true'));
    fireEvent.keyDown(window, { key: 'j' });
    await waitFor(() => expect(screen.getByTestId('tool-card-2')).toHaveAttribute('data-selected', 'true'));
    fireEvent.keyDown(window, { key: 'd' });
    await waitFor(() => expect(decide).toHaveBeenCalled());
    expect(decide.mock.calls[0][0]).toBe(2);
    expect(decide.mock.calls[0][1]).toMatchObject({ decision: 'deny' });
  });

  it('A applies a heal proposal and shows old → new', async () => {
    vi.spyOn(api, 'getToolCalls').mockResolvedValue({ items: [] });
    const decide = vi.spyOn(api, 'decideHealProposal').mockResolvedValue(heal);
    wrap(<ApprovalsView />);
    expect(await screen.findByText(/order_4471: retry until success → cancelled/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId('heal-card-7')).toHaveAttribute('data-selected', 'true'));
    fireEvent.keyDown(window, { key: 'a' });
    await waitFor(() => expect(decide).toHaveBeenCalled());
    expect(decide.mock.calls[0][1]).toMatchObject({ decision: 'apply', requested_by: 'human' });
  });

  it('R opens the rewrite editor and sends final_args', async () => {
    const decide = vi.spyOn(api, 'decideToolCall').mockResolvedValue(call(1, ''));
    wrap(<ApprovalsView />);
    await waitFor(() => expect(screen.getByTestId('tool-card-1')).toHaveAttribute('data-selected', 'true'));
    fireEvent.keyDown(window, { key: 'r' });
    fireEvent.click(await screen.findByRole('button', { name: 'Send rewrite' }));
    await waitFor(() => expect(decide).toHaveBeenCalled());
    expect(decide.mock.calls[0][1]).toMatchObject({ decision: 'rewrite', final_args: { amount: 50000, order: 'o1' } });
  });

  it('shows the empty state', async () => {
    vi.spyOn(api, 'getToolCalls').mockResolvedValue({ items: [] });
    vi.spyOn(api, 'getHealProposals').mockResolvedValue({ items: [] });
    wrap(<ApprovalsView />);
    expect(await screen.findByText('Nothing waiting for a human')).toBeInTheDocument();
  });
});
