import { livePoll } from '../utils/live';
import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { WifiOff } from 'lucide-react';
import { api, ApiError } from '../api/client';

/** Shown while the API is unreachable. The 1 s poll keeps retrying, so it clears itself. */
export const ConnectionBanner: React.FC = () => {
  const { isError, error } = useQuery({
    queryKey: ['health'],
    queryFn: api.getHealth,
    refetchInterval: livePoll,
  });
  if (!isError) return null;
  // A hosted demo on a free tier sleeps when idle; the proxy then answers 502/503/504 for ~1 min.
  const waking = error instanceof ApiError && [502, 503, 504].includes(error.status);
  return (
    <div
      role="alert"
      data-testid="connection-lost"
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 'var(--space-2)',
        padding: 'var(--space-2) var(--space-4)',
        backgroundColor: 'var(--color-state-killed-bg)',
        borderBottom: '1px solid var(--color-state-killed-border)',
        color: 'var(--color-state-killed)',
        fontFamily: 'var(--font-mono)',
        fontSize: 'var(--type-micro-size)',
        fontWeight: 700,
        position: 'relative',
        zIndex: 150,
      }}
    >
      <WifiOff size={14} />
      {waking
        ? 'The demo API is waking up (a free server sleeps when idle; this can take about a minute). Retrying…'
        : `Connection to the API lost${error instanceof Error ? ` (${error.message})` : ''}. Retrying every second…`}
    </div>
  );
};
