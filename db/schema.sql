-- CloudSentinel database schema (Supabase / PostgreSQL)
-- Owner: Fojle.  Must stay in sync with shared/contracts.py (MetricRow, AlertRow, ActionRow, CommandRow).
-- How to use: Supabase dashboard → SQL Editor → paste this whole file → Run.

create table if not exists agent_metrics (
    id             bigint generated always as identity primary key,
    agent          text        not null,
    container_id   text        not null,
    tokens_per_min integer     not null default 0,
    calls_per_sec  real        not null default 0,
    total_tokens   integer     not null default 0,
    token_budget   integer     not null default 0,
    loop_repeats   integer     not null default 0,
    memory_mb      real        not null default 0,
    memory_pct     real        not null default 0,
    status         text        not null default 'running',
    created_at     timestamptz not null default now()
);
create index if not exists agent_metrics_created_idx on agent_metrics (created_at desc);

create table if not exists alerts (
    id         bigint generated always as identity primary key,
    agent      text        not null,
    severity   text        not null,        -- info | warning | critical
    rule       text        not null,
    message    text        not null,
    created_at timestamptz not null default now()
);
create index if not exists alerts_created_idx on alerts (created_at desc);

create table if not exists actions (
    id                    bigint generated always as identity primary key,
    agent                 text        not null,
    action                text        not null,   -- KILL | WARN
    actor                 text        not null,   -- rules | claude | fallback | human
    reason                text        not null,
    tokens_saved_estimate integer     not null default 0,
    created_at            timestamptz not null default now()
);
create index if not exists actions_created_idx on actions (created_at desc);

create table if not exists commands (
    id           bigint generated always as identity primary key,
    agent        text        not null,
    command      text        not null,            -- KILL | GO_ROGUE
    requested_by text        not null default 'dashboard',
    reason       text        not null default '',
    status       text        not null default 'pending',   -- pending | done | failed
    result       text        not null default '',
    created_at   timestamptz not null default now()
);
create index if not exists commands_status_idx on commands (status, created_at);

-- Hackathon note: we use the service-role key from a trusted laptop only.
-- Never put the service-role key in the dashboard if it is deployed publicly.
