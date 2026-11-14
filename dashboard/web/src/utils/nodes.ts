import type { AgentView } from '../api/types';

/** D15: `RuntimeInfo.runtime` reads `docker@<node>` on a multi-node fleet. */

export function nodeOf(runtime: string): string | null {
  const i = runtime.indexOf('@');
  return i > 0 && i < runtime.length - 1 ? runtime.slice(i + 1) : null;
}

export interface NodeGroup {
  node: string;
  agents: AgentView[];
}

/** Groups agents by node (alphabetical). Agents without a node go last under "unassigned". */
export function groupByNode(agents: AgentView[]): NodeGroup[] {
  const map = new Map<string, AgentView[]>();
  agents.forEach((a) => {
    const n = nodeOf(a.runtime) ?? 'unassigned';
    map.set(n, [...(map.get(n) ?? []), a]);
  });
  return [...map.entries()]
    .sort(([a], [b]) => (a === 'unassigned' ? 1 : b === 'unassigned' ? -1 : a.localeCompare(b)))
    .map(([node, list]) => ({ node, agents: list }));
}

export const hasNodes = (agents: AgentView[]): boolean => agents.some((a) => nodeOf(a.runtime) !== null);
