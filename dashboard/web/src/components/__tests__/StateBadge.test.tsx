import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { StateBadge } from '../StateBadge';

describe('StateBadge Component (src/components/StateBadge.tsx)', () => {
  it('renders healthy badge with uppercase label', () => {
    render(<StateBadge state="healthy" />);
    const badge = screen.getByRole('status', { name: /agent state: healthy/i });
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent('HEALTHY');
  });

  it('renders paused badge with appropriate semantic role', () => {
    render(<StateBadge state="paused" />);
    const badge = screen.getByRole('status', { name: /agent state: paused/i });
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent('PAUSED');
  });

  it('renders killed badge with critical label', () => {
    render(<StateBadge state="killed" />);
    const badge = screen.getByRole('status', { name: /agent state: killed/i });
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent('KILLED');
  });

  it('renders suspicious and probation states correctly', () => {
    const { rerender } = render(<StateBadge state="suspicious" />);
    expect(screen.getByText('SUSPICIOUS')).toBeInTheDocument();

    rerender(<StateBadge state="probation" />);
    expect(screen.getByText('PROBATION')).toBeInTheDocument();
  });
});
