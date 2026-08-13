-- Anima-RAG-Lab knowledge_chunks (WBS 2.1–2.3)
-- Works on local Postgres+pgvector (pg0) and Supabase.
-- Embedding: paraphrase-multilingual-MiniLM-L12-v2 (384-d, cosine).

create extension if not exists vector;

create table if not exists public.knowledge_chunks (
  id text primary key,
  content text not null,
  metadata jsonb not null default '{}'::jsonb,
  embedding vector(384) not null,
  module text not null check (module in ('A', 'B', 'C')),
  source text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists knowledge_chunks_module_idx
  on public.knowledge_chunks (module);

create index if not exists knowledge_chunks_source_idx
  on public.knowledge_chunks (source);

create index if not exists knowledge_chunks_embedding_hnsw
  on public.knowledge_chunks
  using hnsw (embedding vector_cosine_ops);

comment on table public.knowledge_chunks is
  'ANIMA-RAG-Lab merged store (Merck A + behavior B + husbandry C)';

create or replace function public.match_knowledge_chunks(
  query_embedding vector(384),
  match_count int default 5,
  filter_module text default null
)
returns table (
  id text,
  content text,
  metadata jsonb,
  module text,
  source text,
  similarity float
)
language sql
stable
parallel safe
as $$
  select
    kc.id,
    kc.content,
    kc.metadata,
    kc.module,
    kc.source,
    (1 - (kc.embedding <=> query_embedding))::float as similarity
  from public.knowledge_chunks as kc
  where filter_module is null
     or kc.module = filter_module
  order by kc.embedding <=> query_embedding
  limit greatest(coalesce(match_count, 5), 1);
$$;
