import { describe, it, expect } from 'vitest';
import { toMs, spanKind, spansToBars, nodesToBars } from '../replay';
import type { NodeFeedItem, SpanRow } from '../../api/types';

const span = (p: Partial<SpanRow>): SpanRow => ({ trace_id: 't', span_id: 's', agent_id: 'a', operation: 'llm_call', name: 'n', start_ts: 1_700_000_000, duration_ms: 500, ...p });

describe('replay bars', () => {
  it('normalises seconds and milliseconds', () => {
    expect(toMs(1_700_000_000)).toBe(1_700_000_000_000);
    expect(toMs(1_700_000_000_000)).toBe(1_700_000_000_000);
  });
  it('maps span types to chart kinds', () => {
    expect(spanKind(span({ status: 'error' }))).toBe('error');
    expect(spanKind(span({ operation: 'tool', tool_name: 'x' }))).toBe('tool');
    expect(spanKind(span({ operation: 'graph_node' }))).toBe('action');
    expect(spanKind(span({}))).toBe('llm');
  });
  it('builds bars with a minimum width and skips spans without a start', () => {
    const bars = spansToBars([span({ duration_ms: 10 }), span({ start_ts: undefined })]);
    expect(bars).toHaveLength(1);
    expect(bars[0].end - bars[0].start).toBe(50);
  });
  it('turns node transitions into action/error bars', () => {
    const n = { ts: 1_700_000_000, node: 'lookup', next: 'retry', step: 1, framework: 'lg', changed: {}, status: 'error', duration_ms: 900, trace_id: 't' } as NodeFeedItem;
    expect(nodesToBars([n])[0]).toMatchObject({ kind: 'error', label: 'lookup', detail: 'next: retry' });
  });
});
