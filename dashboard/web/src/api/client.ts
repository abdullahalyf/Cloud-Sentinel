import type {
  ActionsResponse,
  AgentDetailResponse,
  AlertsResponse,
  CommandRequest,
  CommandResponse,
  ExplainReport,
  FleetResponse,
  GraphResponse,
  HealthResponse,
  HealDecisionRequest,
  HealProposalRow,
  HealProposalsResponse,
  MemoryHistoryResponse,
  MemoryRow,
  MetricsResponse,
  NodeFeed,
  PolicyView,
  PutMemoryRequest,
  RoiReport,
  ToolCallDecisionRequest,
  ToolCallRow,
  ToolCallsResponse,
  VerdictsResponse,
} from './types';

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(`API Error ${status}: ${detail}`);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

const BASE_URL = '';

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const url = `${BASE_URL}${path}`;
  const headers = new Headers(options.headers || {});

  if (!headers.has('Content-Type') && options.body && typeof options.body === 'string') {
    headers.set('Content-Type', 'application/json');
  }

  let res: Response;
  try {
    res = await fetch(url, { ...options, headers });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Network request failed';
    throw new ApiError(0, message);
  }

  if (!res.ok) {
    let detail = res.statusText || `Request failed with status ${res.status}`;
    try {
      const data = await res.json();
      if (data && typeof data.detail === 'string') {
        detail = data.detail;
      }
    } catch {
      // Body is not JSON, keep fallback detail
    }
    throw new ApiError(res.status, detail);
  }

  return res.json() as Promise<T>;
}

export const api = {
  getHealth: () => request<HealthResponse>('/v1/health'),

  getFleet: () => request<FleetResponse>('/v1/fleet'),

  getAgent: (id: string) => request<AgentDetailResponse>(`/v1/agents/${encodeURIComponent(id)}`),

  getAgentNodes: (id: string, minutes = 10, limit = 100) =>
    request<NodeFeed>(`/v1/agents/${encodeURIComponent(id)}/nodes?minutes=${minutes}&limit=${limit}`),

  getAgentExplain: (id: string, minutes = 10) =>
    request<ExplainReport>(`/v1/agents/${encodeURIComponent(id)}/explain?minutes=${minutes}`),

  getMetrics: (minutes = 5, agentId?: string) => {
    const params = new URLSearchParams({ minutes: minutes.toString() });
    if (agentId) params.append('agent_id', agentId);
    return request<MetricsResponse>(`/v1/metrics?${params.toString()}`);
  },

  getGraph: (minutes = 2) => request<GraphResponse>(`/v1/graph?minutes=${minutes}`),

  getVerdicts: (limit = 20) => request<VerdictsResponse>(`/v1/verdicts?limit=${limit}`),

  getActions: (limit = 50) => request<ActionsResponse>(`/v1/actions?limit=${limit}`),

  getAlerts: (limit = 50) => request<AlertsResponse>(`/v1/alerts?limit=${limit}`),

  postCommand: (agentId: string, body: CommandRequest) =>
    request<CommandResponse>(`/v1/agents/${encodeURIComponent(agentId)}/commands`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  getMemory: (agentId: string) =>
    request<MemoryRow>(`/v1/agents/${encodeURIComponent(agentId)}/memory`),

  putMemory: (agentId: string, body: PutMemoryRequest) =>
    request<MemoryRow>(`/v1/agents/${encodeURIComponent(agentId)}/memory`, {
      method: 'PUT',
      body: JSON.stringify(body),
    }),

  getMemoryHistory: (agentId: string, limit = 10) =>
    request<MemoryHistoryResponse>(`/v1/agents/${encodeURIComponent(agentId)}/memory/history?limit=${limit}`),

  getToolCalls: (status?: string, limit = 50) => {
    const params = new URLSearchParams({ limit: limit.toString() });
    if (status) params.append('status', status);
    return request<ToolCallsResponse>(`/v1/tool-calls?${params.toString()}`);
  },

  getToolCall: (id: number) => request<ToolCallRow>(`/v1/tool-calls/${id}`),

  decideToolCall: (id: number, body: ToolCallDecisionRequest) =>
    request<ToolCallRow>(`/v1/tool-calls/${id}/decision`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  getHealProposals: (status?: string, agentId?: string, limit = 50) => {
    const params = new URLSearchParams({ limit: limit.toString() });
    if (status) params.append('status', status);
    if (agentId) params.append('agent_id', agentId);
    return request<HealProposalsResponse>(`/v1/heal-proposals?${params.toString()}`);
  },

  getHealProposal: (id: number) => request<HealProposalRow>(`/v1/heal-proposals/${id}`),

  decideHealProposal: (id: number, body: HealDecisionRequest) =>
    request<HealProposalRow>(`/v1/heal-proposals/${id}/decision`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  getRoi: () => request<RoiReport>('/v1/roi'),

  getPolicy: () => request<PolicyView>('/v1/policy'),

  resetMock: () => request<{ ok: boolean }>('/v1/mock/reset', { method: 'POST' }),
};
