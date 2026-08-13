-- Optional Supabase-only grants / RLS (skip on local pg0).
-- Apply after 20260813_knowledge_chunks.sql when targeting a real Supabase project.

revoke all on function public.match_knowledge_chunks(vector, int, text) from public;
grant execute on function public.match_knowledge_chunks(vector, int, text) to service_role;

alter table public.knowledge_chunks enable row level security;
