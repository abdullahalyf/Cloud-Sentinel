/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Optional API base URL (default '' = same origin, via proxy or rewrite). */
  readonly VITE_API_URL?: string;
  /** Optional full WebSocket URL for /v1/stream (static hosts cannot proxy sockets). */
  readonly VITE_WS_URL?: string;
  /** '1' always shows the demo panel (it also shows when the API runs in fake/mock mode). */
  readonly VITE_DEMO?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
