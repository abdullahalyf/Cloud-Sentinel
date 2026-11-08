import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { AgentCard } from '../AgentCard';
import type { AgentView } from '../../api/types';

const mockAgent: AgentView = {
  agent_id: 'beta',
  display_name: 'beta',
  runtime: 'docker',
  state: 'paused',
  budget_usd: 0.5,
  spend_usd: 0.25,
  total_tokens: 12500,
  tokens_per_min: 16100,
  usd_per_min: 0.0624,
  calls_per_sec: 1.2,
  exact_repeats: 2,
  loop_score: 0.85,
  tool_cycle: true,
  memory_pct: 45.0,
  baseline: {
    tokens_per_min: { median: 5366.0, limit: 16100.0, samples: 30 },
  },
  last_verdict: {
    agent_id: 'beta',
    source: 'claude',
    action: 'PAUSE',
    confidence: 0.93,
    pattern: 'semantic_loop',
    reason: 'Repeated order 4471 requests',
  },
  updated_at: '2026-11-08T17:00:00Z',
};

describe('AgentCard Component (src/components/AgentCard.tsx)', () => {
  it('renders agent ID, state badge, and burn metrics', () => {
    const handleClick = vi.fn();
    render(<AgentCard agent={mockAgent} onClick={handleClick} />);

    expect(screen.getByText('beta')).toBeInTheDocument();
    expect(screen.getByText('PAUSED')).toBeInTheDocument();
    expect(screen.getByText(/\$0.0624/)).toBeInTheDocument();
    expect(screen.getByText(/3.0× normal/)).toBeInTheDocument();
  });

  it('renders budget progress and loop score anomaly warning', () => {
    render(<AgentCard agent={mockAgent} onClick={() => {}} />);

    expect(screen.getByText(/\$0.25 \/ \$0.50 \(50%\)/)).toBeInTheDocument();
    expect(screen.getByText(/0.85/)).toBeInTheDocument();
    expect(screen.getByText(/ANOMALY/)).toBeInTheDocument();
  });

  it('triggers onClick when clicked', () => {
    const handleClick = vi.fn();
    render(<AgentCard agent={mockAgent} onClick={handleClick} />);

    const card = screen.getByTestId('agent-card-beta');
    fireEvent.click(card);
    expect(handleClick).toHaveBeenCalledTimes(1);
  });

  it('triggers onClick when Enter key is pressed on focused card', () => {
    const handleClick = vi.fn();
    render(<AgentCard agent={mockAgent} onClick={handleClick} />);

    const card = screen.getByTestId('agent-card-beta');
    card.focus();
    fireEvent.keyDown(card, { key: 'Enter', code: 'Enter' });
    expect(handleClick).toHaveBeenCalledTimes(1);
  });
});
