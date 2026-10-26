-- CloudSentinel: keep the free Supabase database small.   Owner: Fojle.
--
-- agent_metrics gets ~3 rows per second (about 260,000 a day), so the free plan would fill up
-- quickly. This file deletes metrics older than 1 day, every hour, using pg_cron.
--
-- How to use: Supabase dashboard -> SQL Editor -> paste this whole file -> Run.
-- Safe to run again: it replaces the function and the schedule, it never duplicates them.
--
-- Check it:       select * from cron.job;                          -- the schedule is listed
--                 select * from cron.job_run_details order by start_time desc limit 5;  -- last runs
-- Run it by hand: select cleanup_old_metrics();                    -- returns how many rows it deleted
--                 select cleanup_old_metrics(interval '1 hour');   -- keep only the last hour
-- Turn it off:    select cron.unschedule('cleanup-old-metrics');
--
-- Only agent_metrics is cleaned. alerts / actions / commands are tiny and are the demo history.
-- (pg_cron runs on UTC time. created_at is timestamptz, so the comparison is always correct.)

create extension if not exists pg_cron;

create or replace function cleanup_old_metrics(keep interval default interval '1 day')
returns bigint
language plpgsql
set search_path = public
as $$
declare
    deleted bigint;
begin
    -- uses the index agent_metrics_created_idx from db/schema.sql, so it is fast
    delete from agent_metrics where created_at < now() - keep;
    get diagnostics deleted = row_count;
    return deleted;
end;
$$;

-- Supabase exposes public functions over its API. Without this, anyone holding the public key
-- could call cleanup_old_metrics(interval '0') and wipe the table. pg_cron runs as the owner,
-- so it still works.
revoke execute on function cleanup_old_metrics(interval) from public, anon, authenticated;

-- every hour, at minute 0. Same job name again = the old schedule is replaced.
select cron.schedule('cleanup-old-metrics', '0 * * * *', 'select cleanup_old_metrics()');