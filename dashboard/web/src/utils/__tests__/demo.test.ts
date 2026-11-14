import { describe, it, expect, vi } from 'vitest';
import { runDemo, resetDemo, DEMO_STEPS, budgetWithHeadroom, type StepStatus } from '../demo';
import type { AgentView } from '../../api/types';

type Fake = { agent_id: string; state: AgentView['state']; spend_usd: number; budget_usd: number };

/** A tiny fake brain: commands change agent state the way the real one does. */
function fakeBrain(agents: Fake[], opts: { probationPolls?: number; rogueBetaResult?: AgentView['state']; memory?: Record<string, Record<string, unknown>>; killOnProbation?: number } = {}) {
  let killsLeft = opts.killOnProbation ?? 0;
  const fleet = new Map(agents.map((a) => [a.agent_id, { ...a }]));
  const memory = new Map(Object.entries(opts.memory ?? {}));
  let probationLeft = 0;
  let version = 1;
  const postCommand = vi.fn(async (id: string, body: { command: string; params?: Record<string, unknown> }) => {
    const a = fleet.get(id)!;
    if (body.command === 'SET_BUDGET') a.budget_usd = Number(body.params?.budget_usd);
    if (body.command === 'RESTART' || body.command === 'RESUME') {
      a.state = 'probation';
      probationLeft = opts.probationPolls ?? 0;
    }
    if (body.command === 'GO_ROGUE' && id === 'beta') a.state = opts.rogueBetaResult ?? 'paused';
    return { id: 1, status: 'pending' };
  });
  const getFleet = vi.fn(async () => {
    fleet.forEach((a) => {
      if (a.state === 'probation') {
        if (a.agent_id === 'beta' && killsLeft > 0) {
          killsLeft--;
          a.state = 'killed';
        } else if (probationLeft <= 0) a.state = 'healthy';
        else probationLeft--;
      }
    });
    return { agents: [...fleet.values()].map((a) => ({ ...a }) as unknown as AgentView) };
  });
  return {
    api: {
      postCommand,
      getFleet,
      getMemory: vi.fn(async (id: string) => ({ version: version++, content: memory.get(id) ?? {} })),
      getRoi: vi.fn(async () => ({ saved_usd: 132.12 })),
      putMemory: vi.fn(async (id: string, body: { content: Record<string, unknown> }) => {
        memory.set(id, body.content);
        return {};
      }),
    },
    fleet,
  };
}

const run = (api: unknown, log: Record<number, { s: StepStatus; d?: string }>, navigate = vi.fn()) =>
  runDemo({ api: api as never, onStatus: (i, s, d) => (log[i] = { s, d }), navigate, signal: new AbortController().signal, pollMs: 1, waitMs: 300, humanWaitMs: 300, probationWaitMs: 300, startWaitMs: 20 });

describe('demo runner', () => {
  it('starts with a step that gets beta ready, then the 7 scripted steps', () => {
    expect(DEMO_STEPS).toHaveLength(8);
    expect(DEMO_STEPS[0].id).toBe('prepare');
  });

  it('only raises a budget that is nearly spent, to spend + $1', () => {
    expect(budgetWithHeadroom(0.5, 0.5)).toBe(1.5);
    expect(budgetWithHeadroom(0.1, 0.5)).toBeNull();
  });

  it('gives an exhausted beta budget headroom so the hard limit cannot kill it, then runs everything', async () => {
    const { api } = fakeBrain([
      { agent_id: 'beta', state: 'healthy', spend_usd: 0.5, budget_usd: 0.5 },
      { agent_id: 'gamma', state: 'killed', spend_usd: 1.0, budget_usd: 1.0 },
      { agent_id: 'delta', state: 'healthy', spend_usd: 0.1, budget_usd: 0.5 },
    ]);
    const log: Record<number, { s: StepStatus; d?: string }> = {};
    const navigate = vi.fn();
    expect(await run(api, log, navigate)).toBe(true);
    expect(Object.values(log).every((x) => x.s === 'done')).toBe(true);
    const cmds = api.postCommand.mock.calls.map((c) => `${c[0]}:${c[1].command}${c[1].params?.budget_usd ? `=${c[1].params.budget_usd}` : ''}`);
    expect(cmds).toEqual([
      'beta:SET_BUDGET=1.5',
      'beta:GO_ROGUE',
      'gamma:SET_BUDGET=2',
      'gamma:RESTART',
      'gamma:GO_ROGUE',
      'delta:GO_ROGUE',
    ]);
    expect(log[0].d).toMatch(/budget raised to \$1\.50/);
    expect(navigate).toHaveBeenCalledWith('/approvals');
  });

  it('restarts a killed beta and waits for probation to end before sending it rogue', async () => {
    const { api } = fakeBrain(
      [
        { agent_id: 'beta', state: 'killed', spend_usd: 0.1, budget_usd: 0.5 },
        { agent_id: 'gamma', state: 'healthy', spend_usd: 0, budget_usd: 1 },
        { agent_id: 'delta', state: 'healthy', spend_usd: 0, budget_usd: 1 },
      ],
      { probationPolls: 3 }
    );
    const log: Record<number, { s: StepStatus; d?: string }> = {};
    expect(await run(api, log)).toBe(true);
    const calls = api.postCommand.mock.calls.map((c) => `${c[0]}:${c[1].command}`);
    expect(calls.slice(0, 2)).toEqual(['beta:RESTART', 'beta:GO_ROGUE']);
    expect(log[0].d).toMatch(/restarted; beta is healthy/);
  });

  it('clears a loop belief left in memory by the last run, so a restarted beta does not loop on probation', async () => {
    const { api } = fakeBrain(
      [
        { agent_id: 'beta', state: 'killed', spend_usd: 0.5, budget_usd: 0.5 },
        { agent_id: 'gamma', state: 'healthy', spend_usd: 0, budget_usd: 1 },
        { agent_id: 'delta', state: 'healthy', spend_usd: 0, budget_usd: 1 },
      ],
      { memory: { beta: { order_4471: 'orders API returned 500 - retry until success', note: 'keep me' } } }
    );
    const log: Record<number, { s: StepStatus; d?: string }> = {};
    expect(await run(api, log)).toBe(true);
    const first = api.putMemory.mock.calls[0];
    expect(first[0]).toBe('beta');
    expect(first[1].content).toEqual({ note: 'keep me' });
    expect(log[0].d).toMatch(/cleared the loop belief.*budget raised.*restarted/);
  });

  it('explains it and stops if beta is still killed instead of paused', async () => {
    const { api } = fakeBrain(
      [
        { agent_id: 'beta', state: 'healthy', spend_usd: 0, budget_usd: 1 },
        { agent_id: 'gamma', state: 'healthy', spend_usd: 0, budget_usd: 1 },
        { agent_id: 'delta', state: 'healthy', spend_usd: 0, budget_usd: 1 },
      ],
      { rogueBetaResult: 'killed' }
    );
    const log: Record<number, { s: StepStatus; d?: string }> = {};
    expect(await run(api, log)).toBe(false);
    expect(log[2].s).toBe('failed');
    expect(log[2].d).toMatch(/killed instead of paused/);
    expect(log[3]).toBeUndefined();
  });

  it('retries when beta is killed on probation, and explains it plainly if it keeps happening', async () => {
    const agents = (): Fake[] => [
      { agent_id: 'beta', state: 'killed', spend_usd: 0, budget_usd: 1 },
      { agent_id: 'gamma', state: 'healthy', spend_usd: 0, budget_usd: 1 },
      { agent_id: 'delta', state: 'healthy', spend_usd: 0, budget_usd: 1 },
    ];
    const once = fakeBrain(agents(), { killOnProbation: 1 });
    const log1: Record<number, { s: StepStatus; d?: string }> = {};
    expect(await run(once.api, log1)).toBe(true);
    expect(log1[0].d).toMatch(/attempt 2/);

    const always = fakeBrain(agents(), { killOnProbation: 99 });
    const log2: Record<number, { s: StepStatus; d?: string }> = {};
    expect(await run(always.api, log2)).toBe(false);
    expect(log2[0].s).toBe('failed');
    expect(log2[0].d).toMatch(/killed on probation 3 times.*halves its soft limits.*Press Start/);
  });

  it('marks a step failed when the API never reaches the state', async () => {
    const { api } = fakeBrain([{ agent_id: 'beta', state: 'killed', spend_usd: 0, budget_usd: 1 }], { probationPolls: 10_000 });
    const log: Record<number, { s: StepStatus; d?: string }> = {};
    expect(await run(api, log)).toBe(false);
    expect(log[0].s).toBe('failed');
    expect(log[0].d).toMatch(/Timed out waiting for beta to be healthy/);
  });

  it('reset restores budget headroom, restarts killed, resumes paused, and clears memory', async () => {
    const { api } = fakeBrain([
      { agent_id: 'beta', state: 'paused', spend_usd: 0.1, budget_usd: 0.5 },
      { agent_id: 'gamma', state: 'killed', spend_usd: 1.0, budget_usd: 1.0 },
      { agent_id: 'alpha', state: 'healthy', spend_usd: 0, budget_usd: 1 },
    ]);
    await resetDemo(api as never);
    expect(api.postCommand.mock.calls.map((c) => `${c[0]}:${c[1].command}`)).toEqual(['beta:RESUME', 'gamma:SET_BUDGET', 'gamma:RESTART']);
    expect(api.putMemory).toHaveBeenCalledTimes(3);
  });
});
