import { describe, it, expect, vi, afterEach } from 'vitest';
import { QueryClient } from '@tanstack/react-query';
import { startLiveStream, livePoll, keysFor, isStreamLive, streamUrl } from '../live';

class FakeSocket {
  static instances: FakeSocket[] = [];
  readyState = 0;
  closed = false;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onmessage: ((m: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(public url: string) {
    FakeSocket.instances.push(this);
  }
  close() {
    this.closed = true;
    this.onclose?.();
  }
}

afterEach(() => {
  FakeSocket.instances = [];
  vi.useRealTimers();
});

describe('live stream', () => {
  it('maps event types to the queries they make stale', () => {
    expect(keysFor('action')).toContainEqual(['roi']);
    expect(keysFor('tool_call')).toContainEqual(['tool-calls']);
    expect(keysFor('nope')).toEqual([]);
  });

  it('slows polling while connected, restores 1 s when the socket drops, and reconnects', () => {
    vi.useFakeTimers();
    const qc = new QueryClient();
    const stop = startLiveStream(qc, { url: 'ws://x/v1/stream', WebSocketImpl: FakeSocket as never, minRetryMs: 100 });
    expect(livePoll()).toBe(1000); // not connected yet

    FakeSocket.instances[0].onopen?.();
    expect(isStreamLive()).toBe(true);
    expect(livePoll()).toBe(5000);

    FakeSocket.instances[0].onclose?.(); // network drop
    expect(isStreamLive()).toBe(false);
    expect(livePoll()).toBe(1000); // polling fallback

    vi.advanceTimersByTime(150);
    expect(FakeSocket.instances).toHaveLength(2); // reconnect attempt
    stop();
  });

  it('writes a metric event into the fleet cache and invalidates on others', () => {
    const qc = new QueryClient();
    const spy = vi.spyOn(qc, 'invalidateQueries');
    const stop = startLiveStream(qc, { url: 'ws://x', WebSocketImpl: FakeSocket as never });
    const s = FakeSocket.instances[0];
    s.onmessage?.({ data: JSON.stringify({ type: 'metric', data: [{ agent_id: 'beta' }] }) });
    expect(qc.getQueryData(['fleet'])).toEqual({ agents: [{ agent_id: 'beta' }] });
    s.onmessage?.({ data: JSON.stringify({ type: 'alert', data: { id: 1 } }) });
    expect(spy).toHaveBeenCalledWith({ queryKey: ['alerts'] });
    s.onmessage?.({ data: 'not json' }); // must not throw
    stop();
  });

  it('does not close a socket that is still connecting (avoids the browser error); closes it once open', () => {
    const qc = new QueryClient();
    const stop = startLiveStream(qc, { url: 'ws://x', WebSocketImpl: FakeSocket as never });
    const s = FakeSocket.instances[0];
    s.readyState = 0; // CONNECTING
    stop();
    expect(s.closed).toBe(false);
    s.onopen?.(); // connection completes -> now it is closed
    expect(s.closed).toBe(true);
  });

  it('gives up quietly when the socket never opens (static host), so the UI just polls', () => {
    vi.useFakeTimers();
    const qc = new QueryClient();
    const stop = startLiveStream(qc, { url: 'ws://x', WebSocketImpl: FakeSocket as never, minRetryMs: 10, maxRetryMs: 10, maxFailedOpens: 3 });
    for (let i = 0; i < 10; i++) {
      FakeSocket.instances[FakeSocket.instances.length - 1].onclose?.();
      vi.advanceTimersByTime(20);
    }
    expect(FakeSocket.instances).toHaveLength(3); // 3 tries, then no more
    expect(livePoll()).toBe(1000);
    stop();
  });

  it('builds the socket URL from VITE_WS_URL, then VITE_API_URL, then the page host', () => {
    expect(streamUrl({ VITE_WS_URL: 'wss://api.example/v1/stream' })).toBe('wss://api.example/v1/stream');
    expect(streamUrl({ VITE_API_URL: 'https://api.example/' })).toBe('wss://api.example/v1/stream');
    expect(streamUrl({})).toMatch(/^wss?:\/\/.+\/v1\/stream$/);
  });
});
