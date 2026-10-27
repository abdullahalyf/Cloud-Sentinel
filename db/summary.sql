-- CloudSentinel: token totals per agent in ONE request, for Store.summary().   Owner: Fojle.
--
-- agent_metrics is the biggest table. Asking for each agent's highest total_tokens one agent at
-- a time (one request per agent) gets slower with every agent we add. This function does it in
-- a single request:   store.summary()  ->  db.rpc("agent_token_totals")
--
-- How to use: Supabase dashboard -> SQL Editor -> paste this whole file -> Run.
-- Safe to run again. Check it:   select * from agent_token_totals();
--
-- It runs with the caller's rights, so Row Level Security (db/security.sql) still applies:
-- the sentinel key and the dashboard key can use it, nobody else can.

create or replace function agent_token_totals()
returns table (agent text, tokens integer)
language sql
stable
set search_path = public
as $$
    select m.agent, max(m.total_tokens)::integer
    from agent_metrics m
    group by m.agent
    order by 2 desc;
$$;