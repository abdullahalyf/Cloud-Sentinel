import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { api, ApiError } from '../client';

describe('API Client (src/api/client.ts)', () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it('handles 200 OK responses with parsed JSON', async () => {
    const mockHealth = {
      ok: true,
      mode: 'mock',
      judge: 'claude',
      contract: 2,
    };

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => mockHealth,
    });

    const res = await api.getHealth();
    expect(res).toEqual(mockHealth);
    expect(global.fetch).toHaveBeenCalledWith('/v1/health', expect.any(Object));
  });

  it('throws ApiError with status 400 and detail on bad request', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 400,
      statusText: 'Bad Request',
      json: async () => ({ detail: 'tool_name is required' }),
    });

    try {
      await api.getToolCalls();
      expect.unreachable('Should have thrown an ApiError');
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      const apiErr = err as ApiError;
      expect(apiErr.status).toBe(400);
      expect(apiErr.detail).toBe('tool_name is required');
    }
  });

  it('throws ApiError with status 409 and detail on conflict', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 409,
      statusText: 'Conflict',
      json: async () => ({ detail: 'memory changed by a human; reload it first' }),
    });

    try {
      await api.putMemory('beta', {
        content: { order_4471: 'retry' },
        edited_by: 'agent',
        reason: 'retry order',
        base_version: 1,
      });
      expect.unreachable('Should have thrown an ApiError');
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      const apiErr = err as ApiError;
      expect(apiErr.status).toBe(409);
      expect(apiErr.detail).toBe('memory changed by a human; reload it first');
    }
  });

  it('throws ApiError with status 0 on network error', async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error('Connection refused at port 8000'));

    try {
      await api.getFleet();
      expect.unreachable('Should have thrown an ApiError');
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      const apiErr = err as ApiError;
      expect(apiErr.status).toBe(0);
      expect(apiErr.detail).toBe('Connection refused at port 8000');
    }
  });

  it('sends correct body and headers on postCommand', async () => {
    const mockCmdRes = { id: 10, status: 'pending' as const };
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => mockCmdRes,
    });

    const res = await api.postCommand('beta', {
      command: 'PAUSE',
      requested_by: 'dashboard',
      reason: 'semantic loop detected',
    });

    expect(res).toEqual(mockCmdRes);
    expect(global.fetch).toHaveBeenCalledWith(
      '/v1/agents/beta/commands',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          command: 'PAUSE',
          requested_by: 'dashboard',
          reason: 'semantic loop detected',
        }),
      })
    );
  });
});
