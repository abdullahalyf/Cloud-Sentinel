import type { api as Api } from '../api/client';

/**
 * The scripted "3 AM incident" (docs/DECISION.md §5). Each step calls the C2 API exactly like
 * scripts/demo.py does, and waits for the REAL API state: nothing is faked.
 */

export type StepStatus = 'waiting' | 'running' | 'done' | 'failed';

export interface DemoStep {
  id: string;
  label: string;
  /** a step that needs a person */
  human?: boolean;
}

export const DEMO_STEPS: DemoStep[] = [
  { id: 'rogue-beta', label: 'beta goes rogue (paraphrase loop)' },
  { id: 'beta-paused', label: 'Wait until beta is paused' },
  { id: 'apply-fix', label: 'Open beta and press "Apply suggestion", then Save', human: true },
  { id: 'rogue-gamma', label: 'gamma goes rogue (token bomb)' },
  { id: 'rogue-delta', label: 'delta makes a bad tool call' },
  { id: 'approvals', label: 'Jump to the Approvals inbox' },
  { id: 'saved', label: 'Show $ saved' },
];

type DemoApi = Pick<typeof Api, 'postCommand' | 'getFleet' | 'getMemory' | 'getRoi' | 'putMemory'>;

export interface RunDeps {
  api: DemoApi;
  onStatus: (index: number, status: StepStatus, detail?: string) => void;
  navigate: (path: string) => void;
  signal: AbortSignal;
  pollMs?: number;
  waitMs?: number;
  humanWaitMs?: number;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function waitUntil(check: () => Promise<boolean>, deps: RunDeps, timeoutMs: number, what: string) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    if (deps.signal.aborted) throw new Error('Stopped');
    if (await check()) return;
    await sleep(deps.pollMs ?? 1000);
  }
  throw new Error(`Timed out waiting for ${what}`);
}

const rogue = (deps: RunDeps, agent: string, kind: string) =>
  deps.api.postCommand(agent, {
    command: 'GO_ROGUE',
    params: { kind },
    requested_by: 'dashboard',
    reason: `demo: ${kind}`,
  });

/** Runs the 7 steps in order; stops at the first failure and marks it. */
export async function runDemo(deps: RunDeps): Promise<boolean> {
  const wait = deps.waitMs ?? 60_000;
  const humanWait = deps.humanWaitMs ?? 300_000;
  let baselineVersion = 0;

  const steps: (() => Promise<string | void>)[] = [
    async () => {
      await rogue(deps, 'beta', 'paraphrase_loop');
    },
    async () => {
      await waitUntil(
        async () => {
          const beta = (await deps.api.getFleet()).agents.find((a) => a.agent_id === 'beta');
          if (beta?.state === 'killed') {
            // e.g. beta misbehaved again while still on probation after a recent reset
            throw new Error('beta was killed instead of paused. Press "Reset demo", wait for beta to be healthy, and run again.');
          }
          return beta?.state === 'paused';
        },
        deps,
        wait,
        'beta to be paused'
      );
    },
    async () => {
      baselineVersion = (await deps.api.getMemory('beta')).version;
      await waitUntil(
        async () => {
          const [mem, fleet] = await Promise.all([deps.api.getMemory('beta'), deps.api.getFleet()]);
          const beta = fleet.agents.find((a) => a.agent_id === 'beta');
          return mem.version > baselineVersion || (!!beta && beta.state !== 'paused');
        },
        deps,
        humanWait,
        'a person to apply the fix'
      );
    },
    async () => {
      await rogue(deps, 'gamma', 'token_bomb');
    },
    async () => {
      await rogue(deps, 'delta', 'bad_tool_call');
    },
    async () => {
      deps.navigate('/approvals');
    },
    async () => {
      const roi = await deps.api.getRoi();
      return `$${roi.saved_usd.toFixed(4)} saved`;
    },
  ];

  for (let i = 0; i < steps.length; i++) {
    if (deps.signal.aborted) return false;
    deps.onStatus(i, 'running');
    try {
      const detail = await steps[i]();
      deps.onStatus(i, 'done', detail || undefined);
    } catch (e) {
      deps.onStatus(i, 'failed', e instanceof Error ? e.message : String(e));
      return false;
    }
  }
  return true;
}

/** Same as `python scripts/demo.py reset`: restart killed, resume paused, clear memory. */
export async function resetDemo(api: DemoApi): Promise<void> {
  const { agents } = await api.getFleet();
  for (const a of agents) {
    if (a.state === 'killed' || a.state === 'paused') {
      await api.postCommand(a.agent_id, {
        command: a.state === 'killed' ? 'RESTART' : 'RESUME',
        requested_by: 'dashboard',
        reason: 'demo reset',
      });
    }
    await api.putMemory(a.agent_id, { content: {}, edited_by: 'human', reason: 'demo reset' });
  }
}
