import type { NodeFeedItem, SpanRow } from '../api/types';
import type { GanttBar, GanttKind } from '../components/viz';

/** Turns recorded spans and graph-node transitions into bars for the session replay chart. */

// epoch seconds (1.7e9) or milliseconds (1.7e12) -> milliseconds
export const toMs = (t: number): number => (t > 1e11 ? t : t * 1000);

export function spanKind(s: SpanRow): GanttKind {
  if (s.status === 'error') return 'error';
  if (s.operation === 'tool' || s.tool_name) return 'tool';
  if (s.operation === 'graph_node') return 'action';
  return 'llm';
}

export function spansToBars(spans: SpanRow[]): GanttBar[] {
  return spans
    .filter((s) => typeof s.start_ts === 'number')
    .map((s, i) => {
      const start = toMs(s.start_ts as number);
      const dur = s.duration_ms ?? (s.end_ts && s.start_ts ? (toMs(s.end_ts) - start) : 0);
      return {
        id: s.span_id || `span-${i}`,
        start,
        end: start + Math.max(dur, 50),
        kind: spanKind(s),
        label: s.name || s.operation,
        detail: s.error_type || (s.model ? `${s.provider ?? ''} ${s.model}`.trim() : undefined),
        who: s.agent_id,
      };
    });
}

export function nodesToBars(items: NodeFeedItem[]): GanttBar[] {
  return items.map((n, i) => {
    const start = toMs(n.ts);
    return {
      id: `node-${n.trace_id}-${n.step}-${i}`,
      start,
      end: start + Math.max(n.duration_ms, 50),
      kind: n.status === 'error' ? 'error' : 'action',
      label: n.node,
      detail: `next: ${n.next}`,
    } as GanttBar;
  });
}
