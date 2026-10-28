-- CloudSentinel: Row Level Security (RLS).   Owner: Fojle.
--
-- Two keys, two jobs:
--   secret / service_role key  -> sentinel + agents. Does everything. RLS does NOT apply to it.
--   publishable / anon key     -> the DASHBOARD. After this file it can only:
--                                   * READ  agent_metrics, alerts, actions, commands
--                                   * INSERT into commands (the Emergency Kill / Simulate rogue
--                                     buttons), and only a new "pending" KILL or GO_ROGUE
--                                 It can NOT update, delete or truncate anything, and it can not
--                                 write fake metrics, alerts or actions.
--
-- How to use: Supabase dashboard -> SQL Editor -> paste this whole file -> Run.
-- Safe to run again. How to run the dashboard with the safe key: see db/README.md.
--
-- If a part of the demo suddenly stops saving data, the sentinel is probably using the PUBLISHABLE
-- key by mistake. It must use the secret / service_role key.

-- 1. Turn RLS on. A table with RLS on and no policy is closed to everybody except service_role.
alter table agent_metrics enable row level security;
alter table alerts        enable row level security;
alter table actions       enable row level security;
alter table commands      enable row level security;

-- 2. Start from nothing for the two public roles. This also removes TRUNCATE, which RLS cannot stop.
--    ("authenticated" = logged-in users. We have none, so it gets nothing.)
revoke all on table agent_metrics, alerts, actions, commands from anon, authenticated;

-- 3. Give back only what the dashboard needs.
grant select on agent_metrics, alerts, actions, commands to anon;
grant insert on commands to anon;

drop policy if exists "dashboard can read agent_metrics" on agent_metrics;
create policy "dashboard can read agent_metrics" on agent_metrics for select to anon using (true);

drop policy if exists "dashboard can read alerts" on alerts;
create policy "dashboard can read alerts" on alerts for select to anon using (true);

drop policy if exists "dashboard can read actions" on actions;
create policy "dashboard can read actions" on actions for select to anon using (true);

drop policy if exists "dashboard can read commands" on commands;
create policy "dashboard can read commands" on commands for select to anon using (true);

-- The only thing the dashboard may write: a NEW command, still waiting for the sentinel.
-- It can not insert a command that is already "done" or invent any other command type.
drop policy if exists "dashboard can send commands" on commands;
create policy "dashboard can send commands" on commands for insert to anon
    with check (command in ('KILL', 'GO_ROGUE') and status = 'pending');