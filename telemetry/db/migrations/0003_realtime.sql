-- 0003: send inserts of these tables over Supabase Realtime. Safe to run twice
-- (alter publication ... add table fails if the table is already in the publication, so check first).
do $$
declare t text;
begin
  foreach t in array array['actions', 'alerts', 'tool_calls', 'agent_memory'] loop
    if not exists (select 1 from pg_publication_tables
                   where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = t) then
      execute format('alter publication supabase_realtime add table public.%I', t);
    end if;
  end loop;
end $$;