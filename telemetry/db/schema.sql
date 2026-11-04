-- CloudSentinel database schema v2 (Supabase / PostgreSQL).   Owner: Fojle.
-- Must stay in sync with shared/contracts.py rows and LocalStore._SCHEMA in shared/store.py.
-- How to use: Supabase → SQL Editor → paste this whole file → Run. Safe to run twice.
-- JSON columns are TEXT holding JSON (same as SQLite) so both stores behave identically.

create table if not exists agents (
    agent_id      text primary key,
    display_name  text        not null default '',
    runtime       text        not null default 'fake',
    runtime_id    text        not null default '',
    state         text        not null default 'healthy',  -- healthy|suspicious|paused|probation|killed
    budget_usd    real        not null default 0.5,
    spend_usd     real        not null default 0,
    total_tokens  integer     not null default 0,
    last_seen_ts  double precision not null default 0,
    updated_at    timestamptz not null default now()
);

create table if not exists spans (
    id             bigint generated always as identity primary key,
    trace_id       text not null default '',
    span_id        text not null default '',
    parent_span_id text not null default '',
    agent_id       text not null,
    operation      text not null,                 -- invoke_agent | chat | execute_tool | graph_node
    name           text not null default '',
    provider       text not null default '',
    model          text not null default '',
    input_tokens   integer not null default 0,
    output_tokens  integer not null default 0,
    cost_usd       double precision not null default 0,
    tool_name      text not null default '',
    tool_args      text not null default '{}',    -- JSON
    prompt_preview text not null default '',
    prompt_hash    text not null default '',
    task_id        text not null default '',
    task_status    text not null default '',
    status         text not null default 'ok',    -- ok | error
    error_type     text not null default '',
    start_ts       double precision not null default 0,
    end_ts         double precision not null default 0,
    duration_ms    double precision not null default 0,
    detail         text not null default '{}',    -- JSON; graph_node: {node, step, framework, changed}
    created_at     timestamptz not null default now()
);
create index if not exists spans_agent_ts on spans (agent_id, start_ts);
alter table spans add column if not exists detail text not null default '{}';  -- for databases made before 4 Nov

create table if not exists agent_metrics (
    id             bigint generated always as identity primary key,
    agent_id       text not null,
    state          text not null,
    tokens_per_min integer not null default 0,
    usd_per_min    double precision not null default 0,
    calls_per_sec  real not null default 0,
    total_tokens   integer not null default 0,
    spend_usd      double precision not null default 0,
    budget_usd     double precision not null default 0,
    exact_repeats  integer not null default 0,
    loop_score     real not null default 0,
    tool_cycle     integer not null default 0,
    memory_mb      real not null default 0,
    memory_pct     real not null default 0,
    created_at     timestamptz not null default now()
);
create index if not exists metrics_created on agent_metrics (created_at desc);

create table if not exists alerts (
    id         bigint generated always as identity primary key,
    agent_id   text not null,
    severity   text not null,          -- info | warning | critical
    rule       text not null,
    message    text not null,
    created_at timestamptz not null default now()
);

create table if not exists verdicts (
    id            bigint generated always as identity primary key,
    agent_id      text not null,
    source        text not null,       -- claude | gemini | fallback
    action        text not null,       -- KILL | PAUSE | WARN | IGNORE
    confidence    real not null,
    pattern       text not null,
    reason        text not null,
    suggested_fix text not null default '',
    latency_ms    real not null default 0,
    created_at    timestamptz not null default now()
);

create table if not exists actions (
    id                    bigint generated always as identity primary key,
    agent_id              text not null,
    action                text not null,   -- KILL|PAUSE|RESUME|RESTART|WARN|SET_BUDGET|MEMORY_EDIT|TOOL_*
    actor                 text not null,   -- rules|claude|gemini|fallback|human|policy|mcp
    reason                text not null,
    usd_saved_estimate    double precision not null default 0,
    tokens_saved_estimate integer not null default 0,
    created_at            timestamptz not null default now()
);

create table if not exists commands (
    id           bigint generated always as identity primary key,
    agent_id     text not null,
    command      text not null,            -- KILL|PAUSE|RESUME|RESTART|GO_ROGUE|SET_BUDGET
    params       text not null default '{}',
    requested_by text not null default 'dashboard',
    reason       text not null default '',
    status       text not null default 'pending',   -- pending | done | failed
    result       text not null default '',
    created_at   timestamptz not null default now()
);
create index if not exists commands_status_idx on commands (status, id);

create table if not exists agent_memory (
    id         bigint generated always as identity primary key,
    agent_id   text not null,
    version    integer not null,
    content    text not null default '{}',   -- JSON object
    edited_by  text not null default 'agent', -- agent | human | mcp
    reason     text not null default '',
    created_at timestamptz not null default now()
);
create index if not exists memory_agent_version on agent_memory (agent_id, version desc);

create table if not exists tool_calls (
    id         bigint generated always as identity primary key,
    agent_id   text not null,
    tool_name  text not null,
    args       text not null default '{}',
    decision   text not null default 'pending',  -- pending|allow|deny|rewrite|timeout
    final_args text not null default '{}',
    decided_by text not null default '',
    reason     text not null default '',
    value_usd  double precision not null default 0,
    created_at timestamptz not null default now(),
    decided_at text not null default ''
);
create index if not exists tool_calls_decision on tool_calls (decision, id);

-- Hackathon note: the service-role key is used from trusted laptops only.
-- Never put it in a publicly deployed dashboard (the dashboard talks to the API, not the DB).
