import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { Panel } from '../Panel';
import { ApiError } from '../../api/client';

describe('Panel Component (src/components/Panel.tsx)', () => {
  it('renders title and normal children when not loading, error, or empty', () => {
    render(
      <Panel title="Agent Metrics">
        <div data-testid="panel-content">Content is active</div>
      </Panel>
    );

    expect(screen.getByText('Agent Metrics')).toBeInTheDocument();
    expect(screen.getByTestId('panel-content')).toHaveTextContent('Content is active');
  });

  it('renders Loading skeleton state when loading is true', () => {
    render(
      <Panel title="Fleet Telemetry" loading={true}>
        <div>Hidden Children</div>
      </Panel>
    );

    expect(screen.getByText('Fleet Telemetry')).toBeInTheDocument();
    expect(screen.getByRole('status', { name: /loading/i })).toBeInTheDocument();
    expect(screen.queryByText('Hidden Children')).not.toBeInTheDocument();
  });

  it('renders Empty state when empty is true', () => {
    render(
      <Panel
        title="Approvals Queue"
        empty={true}
        emptyTitle="No Pending Actions"
        emptyMessage="Nothing waiting for human review."
      >
        <div>Hidden Children</div>
      </Panel>
    );

    expect(screen.getByText('Approvals Queue')).toBeInTheDocument();
    expect(screen.getByText('No Pending Actions')).toBeInTheDocument();
    expect(screen.getByText('Nothing waiting for human review.')).toBeInTheDocument();
    expect(screen.queryByText('Hidden Children')).not.toBeInTheDocument();
  });

  it('renders Error state with detail and calls onRetry when clicked', () => {
    const onRetryMock = vi.fn();
    const testError = new ApiError(404, 'Agent gamma not found on port 8000');

    render(
      <Panel title="Incident Stream" error={testError} onRetry={onRetryMock}>
        <div>Hidden Children</div>
      </Panel>
    );

    expect(screen.getByText('Incident Stream')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByText(/Agent gamma not found on port 8000/)).toBeInTheDocument();

    const retryBtn = screen.getByRole('button', { name: /retry/i });
    expect(retryBtn).toBeInTheDocument();

    fireEvent.click(retryBtn);
    expect(onRetryMock).toHaveBeenCalledTimes(1);
    expect(screen.queryByText('Hidden Children')).not.toBeInTheDocument();
  });
});
