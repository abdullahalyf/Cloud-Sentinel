import type { QueryClient } from '@tanstack/react-query';

/**
 * Live push (D12). `WS /v1/stream` pushes {"type","data"} events; each one refreshes the matching
 * queries immediately. While the socket is up, polling slows to 5 s as a safety net; when the socket
 * drops, polling goes back to 1 s and the socket reconnects with backoff.
 */

let connected = false;
const listeners = new Set<(c: boolean) => void>();

export const isStreamLive = (): boolean => connected;

/** Use as `refetchInterval: livePoll` on every polling query. */
export const livePoll = (): number => (connected ? 5000 : 1000);

export function onStreamState(fn: (c: boolean) => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function setConnected(v: boolean) {
  if (connected === v) return;
  connected = v;
  listeners.forEach((l) => l(v));
}

type StreamEvent = { type: string; data: unknown };

/** Which queries an event makes stale. */
export function keysFor(type: string): string[][] {
  switch (type) {
    case 'metric':
      return [['metrics'], ['agent']];
    case 'action':
      return [['actions'], ['fleet'], ['roi'], ['agent'], ['memory-history']];
    case 'verdict':
      return [['verdicts'], ['agent'], ['fleet']];
    case 'alert':
      return [['alerts'], ['agent']];
    case 'tool_call':
      return [['tool-calls'], ['roi']];
    default:
      return [];
  }
}

export function handleEvent(qc: QueryClient, ev: StreamEvent): void {
  // a metric event carries the whole fleet, so write it straight into the cache
  if (ev.type === 'metric' && Array.isArray(ev.data)) {
    qc.setQueryData(['fleet'], { agents: ev.data });
  }
  keysFor(ev.type).forEach((queryKey) => qc.invalidateQueries({ queryKey }));
}

interface Options {
  url?: string;
  WebSocketImpl?: typeof WebSocket;
  minRetryMs?: number;
  maxRetryMs?: number;
}

export function streamUrl(): string {
  const { protocol, host } = window.location;
  return `${protocol === 'https:' ? 'wss' : 'ws'}://${host}/v1/stream`;
}

/** Opens the socket and keeps it open. Returns a stop function. */
export function startLiveStream(qc: QueryClient, opts: Options = {}): () => void {
  const WS = opts.WebSocketImpl ?? (typeof WebSocket !== 'undefined' ? WebSocket : undefined);
  if (!WS) return () => {};
  const minRetry = opts.minRetryMs ?? 1000;
  const maxRetry = opts.maxRetryMs ?? 5000;
  let socket: WebSocket | null = null;
  let retry = minRetry;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let stopped = false;

  const open = () => {
    if (stopped) return;
    try {
      socket = new WS(opts.url ?? streamUrl());
    } catch {
      schedule();
      return;
    }
    socket.onopen = () => {
      retry = minRetry;
      setConnected(true);
    };
    socket.onmessage = (m) => {
      try {
        handleEvent(qc, JSON.parse(String(m.data)) as StreamEvent);
      } catch {
        /* ignore a malformed frame */
      }
    };
    socket.onclose = () => {
      setConnected(false);
      schedule();
    };
    socket.onerror = () => socket?.close();
  };

  const schedule = () => {
    if (stopped) return;
    timer = setTimeout(open, retry);
    retry = Math.min(maxRetry, retry * 2);
  };

  open();
  return () => {
    stopped = true;
    if (timer) clearTimeout(timer);
    if (socket) {
      socket.onclose = null;
      socket.close();
    }
    setConnected(false);
  };
}
