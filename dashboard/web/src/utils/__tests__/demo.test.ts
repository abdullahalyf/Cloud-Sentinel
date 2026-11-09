import { describe, it, expect, vi } from 'vitest';
import { runDemo, resetDemo, DEMO_STEPS, type StepStatus } from '../demo';
import type { AgentView } from '../../api/types';

const agent = (id: string, state: AgentView['state']) => ({ agent_id: id, state }) as AgentView;

function makeApi(states: AgentView['state'][]) {
  let i = 0;
  let version = 1;
  return {
    postCommand: vi.fn().mockResolvedValue({ id: 1, status: 'pending' }),
    getFleet: vi.fn().mockImplementation(async () => ({
      agents: [agent('beta', states[Math.min(i++, states.length - 1)]), agent('gamma', 'killed')],
    })),
    getMemory: vi.fn().mockImplementation(async () => ({ version: version++ })),
    getRoi: vi.fn().mockResolvedValue({ saved_usd: 132.12 }),
    putMemory: vi.fn().mockResolvedValue({}),
  };
}

describe('demo runner', () => {
  it('has the 7 scripted steps', () => {
    expect(DEMO_STEPS).toHaveLength(7);
  });

  it('runs every step against the real API state and never skips a wait', async () => {
    const api = makeApi(['healthy', 'paused', 'paused']);
    const log: Record<number, StepStatus> = {};
    const navigate = vi.fn();
    const ok = await runDemo({
      api: api as never,
      onStatus: (i, s) => (log[i] = s),
      navigate,
      signal: new AbortController().signal,
      pollMs: 1,
      waitMs: 500,
      humanWaitMs: 500,
    });
    expect(ok).toBe(true);
    expect(Object.values(log).every((s) => s === 'done')).toBe(true);
    const cmds = api.postCommand.mock.calls.map((c) => [c[0], c[1].command, c[1].params.kind]);
    expect(cmds).toEqual([
      ['beta', 'GO_ROGUE', 'paraphrase_loop'],
      ['gamma', 'GO_ROGUE', 'token_bomb'],
      ['delta', 'GO_ROGUE', 'bad_tool_call'],
    ]);
    expect(navigate).toHaveBeenCalledWith('/approvals');
  });

  it('marks a step failed (and stops) when the API never reaches the state', async () => {
    const api = makeApi(['healthy']);
    const log: Record<number, StepStatus> = {};
    const ok = await runDemo({
      api: api as never,
      onStatus: (i, s) => (log[i] = s),
      navigate: vi.fn(),
      signal: new AbortController().signal,
      pollMs: 1,
      waitMs: 20,
    });
    expect(ok).toBe(false);
    expect(log[1]).toBe('failed');
    expect(log[2]).toBeUndefined();
  });

  it('explains it when beta is killed instead of paused', async () => {
    const api = makeApi(['killed']);
    const log: Record<number, { s: StepStatus; d?: string }> = {};
    const ok = await runDemo({
      api: api as never,
      onStatus: (i, s, d) => (log[i] = { s, d }),
      navigate: vi.fn(),
      signal: new AbortController().signal,
      pollMs: 1,
      waitMs: 50,
    });
    expect(ok).toBe(false);
    expect(log[1].s).toBe('failed');
    expect(log[1].d).toMatch(/killed instead of paused/);
  });

  it('reset restarts killed, resumes paused, and clears memory like demo.py', async () => {
    const api = {
      getFleet: vi.fn().mockResolvedValue({ agents: [agent('beta', 'paused'), agent('gamma', 'killed'), agent('alpha', 'healthy')] }),
      postCommand: vi.fn().mockResolvedValue({}),
      putMemory: vi.fn().mockResolvedValue({}),
    };
    await resetDemo(api as never);
    expect(api.postCommand.mock.calls.map((c) => [c[0], c[1].command])).toEqual([
      ['beta', 'RESUME'],
      ['gamma', 'RESTART'],
    ]);
    expect(api.putMemory).toHaveBeenCalledTimes(3);
  });
});
