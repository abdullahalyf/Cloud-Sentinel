/**
 * TypeScript types mirroring CONTRACTS §6 and shared.contracts dataclasses.
 */

export type AgentState = 'healthy' | 'suspicious' | 'paused' | 'probation' | 'killed';
export type ActionType =
  | 'KILL'
  | 'PAUSE'
  | 'RESUME'
  | 'RESTART'
  | 'WARN'
  | 'SET_BUDGET'
  | 'MEMORY_EDIT'
  | 'TOOL_ALLOW'
  | 'TOOL_DENY'
  | 'TOOL_REWRITE'
  | 'AUTO_HEAL';

export interface WorkerInfo {
  worker_id: string;
  started_at: number;
  last_seen: number;
  agents_owned: number;
  pid: number;
}

export interface HealthResponse {
  ok: boolean;
  mode: 'fake' | 'docker' | 'k8s' | 'mock';
  judge: 'claude' | 'gemini' | 'fallback';
  contract: number;
  workers?: WorkerInfo[];
  agents_total?: number;
}

export interface BaselineMetric {
  median: number;
  limit: number;
  samples: number;
}

export interface AgentBaseline {
  tokens_per_min?: BaselineMetric;
  usd_per_min?: BaselineMetric;
  calls_per_sec?: BaselineMetric;
}

export interface VerdictRow {
  id?: number;
  agent_id: string;
  source: 'claude' | 'gemini' | 'fallback' | 'rules';
  action: 'KILL' | 'PAUSE' | 'WARN' | 'IGNORE';
  confidence: number;
  pattern: string;
  reason: string;
  suggested_fix?: string;
  latency_ms?: number;
  created_at?: string;
}

export interface AgentView {
  agent_id: string;
  display_name: string;
  runtime: string;
  state: AgentState;
  budget_usd: number;
  spend_usd: number;
  total_tokens: number;
  tokens_per_min: number;
  usd_per_min: number;
  calls_per_sec: number;
  exact_repeats: number;
  loop_score: number;
  tool_cycle: boolean;
  memory_pct: number;
  baseline: AgentBaseline;
  last_verdict: VerdictRow | null;
  updated_at: string;
}

export interface FleetResponse {
  agents: AgentView[];
}

export interface SpanRow {
  id?: number;
  trace_id: string;
  span_id: string;
  parent_span_id?: string;
  agent_id: string;
  operation: string;
  name: string;
  provider?: string;
  model?: string;
  input_tokens?: number;
  output_tokens?: number;
  cost_usd?: number;
  tool_name?: string;
  tool_args?: string | Record<string, unknown>;
  prompt_preview?: string;
  prompt_hash?: string;
  task_id?: string;
  task_status?: string;
  status?: 'ok' | 'error';
  error_type?: string;
  start_ts?: number;
  end_ts?: number;
  duration_ms?: number;
  detail?: string | Record<string, unknown>;
  created_at?: string;
}

export interface MemoryRow {
  id?: number;
  agent_id: string;
  version: number;
  content: Record<string, unknown>;
  edited_by: 'agent' | 'human' | 'mcp';
  reason: string;
  created_at: string;
}

export interface MemoryHistoryResponse {
  items: MemoryRow[];
}

export interface AgentDetailResponse {
  agent: AgentView;
  spans: SpanRow[];
  verdicts: VerdictRow[];
  memory: MemoryRow | null;
}

export interface NodeFeedItem {
  ts: number;
  node: string;
  step: number;
  framework: string;
  changed: Record<string, unknown>;
  next: string;
  status: 'ok' | 'error';
  duration_ms: number;
  trace_id: string;
}

export interface NodeFeedEdge {
  source: string;
  target: string;
  count: number;
}

export interface NodeFeed {
  items: NodeFeedItem[];
  edges: NodeFeedEdge[];
  last_node: string | null;
  next_node: string | null;
}

export interface MetricRow {
  id?: number;
  agent_id: string;
  state: string;
  tokens_per_min: number;
  usd_per_min: number;
  calls_per_sec: number;
  total_tokens: number;
  spend_usd: number;
  budget_usd: number;
  exact_repeats: number;
  loop_score: number;
  tool_cycle: number | boolean;
  memory_mb: number;
  memory_pct: number;
  created_at: string;
}

export interface MetricsResponse {
  metrics: MetricRow[];
}

export interface GraphNode {
  id: string;
  kind: 'agent' | 'tool' | 'model';
  label: string;
}

export interface GraphEdge {
  source: string;
  target: string;
  count: number;
  in_cycle: boolean;
}

export interface GraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface VerdictsResponse {
  items: VerdictRow[];
}

export interface ActionRow {
  id: number;
  agent_id: string;
  action: string;
  actor: string;
  reason: string;
  usd_saved_estimate: number;
  tokens_saved_estimate?: number;
  created_at: string;
}

export interface ActionsResponse {
  items: ActionRow[];
}

export interface AlertRow {
  id: number;
  agent_id: string;
  severity: 'info' | 'warning' | 'critical';
  rule: string;
  message: string;
  created_at: string;
}

export interface AlertsResponse {
  items: AlertRow[];
}

export interface ToolCallRow {
  id: number;
  agent_id: string;
  tool_name: string;
  args: Record<string, unknown>;
  decision: 'pending' | 'allow' | 'deny' | 'rewrite' | 'timeout';
  final_args: Record<string, unknown>;
  decided_by: string;
  reason: string;
  value_usd: number;
  created_at: string;
  decided_at?: string;
}

export interface ToolCallsResponse {
  items: ToolCallRow[];
}

export interface HealProposalRow {
  id: number;
  agent_id: string;
  kind: 'memory_patch' | 'tool_policy';
  patch: Record<string, unknown>;
  confidence: number;
  status: 'pending' | 'applied' | 'rejected' | 'expired';
  verdict_id: number;
  base_version: number;
  reason: string;
  decided_by: string;
  decided_at: string;
  created_at: string;
}

export interface HealProposalsResponse {
  items: HealProposalRow[];
}

export interface TaskStats {
  tasks: number;
  succeeded: number;
  failed: number;
  abandoned: number;
  success_rate: number;
  spend_usd: number;
  wasted_usd: number;
  unattributed_usd: number;
  cost_per_success_usd: number;
}

export interface SavedByAction {
  action_id: number;
  agent_id: string;
  action: string;
  actor: string;
  usd: number;
}

export interface RoiReport {
  total_spend_usd: number;
  spend_by_agent: Record<string, number>;
  saved_usd: number;
  saved_by_action: SavedByAction[];
  interventions: number;
  tool_calls_held: number;
  tasks_total: number;
  tasks_succeeded: number;
  cost_per_successful_task_usd: number;
  wasted_usd: number;
  tasks_by_agent: Record<string, TaskStats>;
  horizon_minutes: number;
  formula: string;
}

export interface ExplainEvent {
  kind: 'alert' | 'verdict' | 'action' | 'heal';
  ts: number;
  title: string;
  detail: string;
}

export interface ExplainReport {
  agent_id: string;
  state: string;
  minutes: number;
  summary: string;
  polished_summary: string | null;
  events: ExplainEvent[];
  counts: {
    alerts: number;
    verdicts: number;
    actions: number;
    heals: number;
  };
  outcome: 'PAUSE' | 'KILL' | 'WARN' | 'IGNORE' | null;
  cost: {
    spend_usd: number;
    budget_usd: number;
    saved_usd: number;
  };
}

export interface CommandRequest {
  command: 'KILL' | 'PAUSE' | 'RESUME' | 'RESTART' | 'GO_ROGUE' | 'SET_BUDGET';
  params?: Record<string, unknown>;
  requested_by: string;
  reason: string;
}

export interface CommandResponse {
  id: number;
  status: 'pending' | 'done' | 'failed';
}

export interface PutMemoryRequest {
  content: Record<string, unknown>;
  edited_by: 'agent' | 'human' | 'mcp';
  reason: string;
  base_version?: number | null;
}

export interface ToolCallDecisionRequest {
  decision: 'allow' | 'deny' | 'rewrite';
  final_args?: Record<string, unknown> | null;
  decided_by: 'human' | 'mcp';
  reason: string;
}

export interface HealDecisionRequest {
  decision: 'apply' | 'reject';
  reason: string;
  requested_by: 'human' | 'mcp';
}

export interface PolicyView {
  version: string;
  loaded_at: string;
  source: string;
  defaults: Record<string, unknown>;
  agents: Record<string, unknown>;
  tools: Array<Record<string, unknown>>;
  last_error: string;
}
