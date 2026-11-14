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
  { id: 'prepare', label: 'Get beta ready: budget headroom, running, out of probation' },
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
  probationWaitMs?: number;
  prepareAttempts?: number;
  startWaitMs?: number;
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

/** Minimum budget left before an agent is sent rogue, so the hard limit does not kill it on the spot. */
export const HEADROOM_USD = 0.3;

/** New budget that leaves room for the demo: current spend + $1.00 (rounded to cents). */
export function budgetWithHeadroom(spend: number, budget: number): number | null {
  return budget - spend >= HEADROOM_USD ? null : Math.round((spend + 1) * 100) / 100;
}

const command = (deps: { api: DemoApi }, agent: string, cmd: 'RESTART' | 'RESUME' | 'SET_BUDGET', reason: string, params?: Record<string, unknown>) =>
  deps.api.postCommand(agent, { command: cmd, params, requested_by: 'dashboard', reason });

/**
 * Makes an agent able to misbehave in a way the circuit breaker can PAUSE:
 * give it budget headroom (an exhausted budget means an instant hard-limit KILL),
 * restart it if killed, resume it if paused. Returns what it changed.
 */
async function makeRunnable(deps: { api: DemoApi }, agentId: string): Promise<string[]> {
  const did: string[] = [];
  const a = (await deps.api.getFleet()).agents.find((x) => x.agent_id === agentId);
  if (!a) throw new Error(`${agentId} is not in the fleet`);
  // A loop is driven by a bad belief in memory ("retry until success"). A restart does not clear
  // memory, so an agent left looping by the last run would come back looping and be killed on
  // probation. Drop that leftover belief first (the same fix a human applies in the demo).
  const mem = await deps.api.getMemory(agentId).catch(() => null);
  const content = (mem?.content ?? {}) as Record<string, unknown>;
  const stale = Object.keys(content).filter((k) => /retry/i.test(String(content[k])));
  if (stale.length) {
    const clean = Object.fromEntries(Object.entries(content).filter(([k]) => !stale.includes(k)));
    await deps.api.putMemory(agentId, { content: clean, edited_by: 'human', reason: 'demo: clear the leftover loop belief' });
    did.push('cleared the loop belief left by the last run');
  }
  const nb = budgetWithHeadroom(a.spend_usd, a.budget_usd);
  if (nb !== null) {
    await command(deps, agentId, 'SET_BUDGET', 'demo: budget headroom', { budget_usd: nb });
    did.push(`budget raised to $${nb.toFixed(2)}`);
  }
  if (a.state === 'killed') {
    await command(deps, agentId, 'RESTART', 'demo: get ready');
    did.push('restarted');
  } else if (a.state === 'paused') {
    await command(deps, agentId, 'RESUME', 'demo: get ready');
    did.push('resumed');
  }
  return did;
}

const rogue = (deps: RunDeps, agent: string, kind: string) =>
  deps.api.postCommand(agent, {
    command: 'GO_ROGUE',
    params: { kind },
    requested_by: 'dashboard',
    reason: `demo: ${kind}`,
  });

/** Runs the steps in order; stops at the first failure and marks it. */
export async function runDemo(deps: RunDeps): Promise<boolean> {
  const wait = deps.waitMs ?? 60_000;
  const humanWait = deps.humanWaitMs ?? 300_000;
  let baselineVersion = 0;

  const steps: (() => Promise<string | void>)[] = [
    async () => {
      // A restarted or resumed agent is on probation, and misbehaving on probation is an instant KILL.
      // The brain halves the soft limits during probation, which can sit below beta's own normal
      // burst rate, so a restart can be killed again. Try a few times and say plainly why if it fails.
      const tries = deps.prepareAttempts ?? 3;
      let notes: string[] = [];
      for (let attempt = 1; attempt <= tries; attempt++) {
        notes = await makeRunnable(deps, 'beta');
        // a command takes about a second to run: wait until beta has actually left killed/paused
        if (notes.some((n) => n === 'restarted' || n === 'resumed')) {
          const started = Date.now() + (deps.startWaitMs ?? 15_000);
          while (Date.now() < started) {
            if (deps.signal.aborted) throw new Error('Stopped');
            const st = (await deps.api.getFleet()).agents.find((a) => a.agent_id === 'beta')?.state;
            if (st && st !== 'killed' && st !== 'paused') break;
            await sleep(deps.pollMs ?? 1000);
          }
        }
        const end = Date.now() + (deps.probationWaitMs ?? 90_000);
        let state = '';
        while (Date.now() < end) {
          if (deps.signal.aborted) throw new Error('Stopped');
          state = (await deps.api.getFleet()).agents.find((a) => a.agent_id === 'beta')?.state ?? '';
          if (state === 'healthy' || state === 'killed') break;
          await sleep(deps.pollMs ?? 1000);
        }
        if (state === 'healthy') {
          const what = notes.length ? `${notes.join(', ')}; ` : '';
          return `${what}beta is healthy${attempt > 1 ? ` (attempt ${attempt})` : ''}`;
        }
        if (state !== 'killed') throw new Error('Timed out waiting for beta to be healthy (probation ends after about 30 s)');
        deps.onStatus(0, 'running', `beta was killed on probation, trying again (${attempt}/${tries})`);
      }
      throw new Error(
        `beta was killed on probation ${tries} times: the brain halves its soft limits during probation, ` +
          "which sits below beta's normal burst rate. Press Start to try again; this is a brain rule, not the dashboard."

      );
    },
    async () => {
      await rogue(deps, 'beta', 'paraphrase_loop');
    },
    async () => {
      await waitUntil(
        async () => {
          const beta = (await deps.api.getFleet()).agents.find((a) => a.agent_id === 'beta');
          if (beta?.state === 'killed') {
            // e.g. beta misbehaved again while still on probation after a recent reset
            throw new Error('beta was killed instead of paused (budget or probation). Press Start again: the first step now prepares beta.');
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
      await makeRunnable(deps, 'gamma');
      await rogue(deps, 'gamma', 'token_bomb');
    },
    async () => {
      await makeRunnable(deps, 'delta');
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
    const nb = budgetWithHeadroom(a.spend_usd, a.budget_usd);
    if (nb !== null) {
      await api.postCommand(a.agent_id, { command: 'SET_BUDGET', params: { budget_usd: nb }, requested_by: 'dashboard', reason: 'demo reset: budget headroom' });
    }
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
