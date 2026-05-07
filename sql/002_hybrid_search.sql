-- Reciprocal Rank Fusion over BM25-ish full-text search and HNSW cosine vector search.
-- Pattern adapted from the Supabase hybrid-search guide:
--   https://supabase.com/docs/guides/ai/hybrid-search
--
-- Returns the top `match_count` chunks by fused score, with both component ranks
-- exposed so the caller (or a Loom debug view) shows where a hit came from.

create or replace function hybrid_search(
    query_text         text,
    query_embedding    vector(1024),
    match_count        int default 20,
    full_text_weight   float default 1.0,
    semantic_weight    float default 1.0,
    rrf_k              int default 60
)
returns table (
    id              bigint,
    source_id       bigint,
    chunk_index     int,
    heading         text,
    content         text,
    metadata        jsonb,
    source_url      text,
    source_title    text,
    fts_rank        int,
    semantic_rank   int,
    combined_score  float
)
language sql stable
as $$
with
fts as (
    select
        c.id,
        row_number() over (
            order by ts_rank_cd(c.fts, websearch_to_tsquery('english', query_text)) desc
        )::int as rank
    from chunks c
    where c.fts @@ websearch_to_tsquery('english', query_text)
    limit match_count * 2
),
semantic as (
    select
        c.id,
        row_number() over (
            order by c.embedding <=> query_embedding
        )::int as rank
    from chunks c
    order by c.embedding <=> query_embedding
    limit match_count * 2
),
fused as (
    select
        coalesce(f.id, s.id) as id,
        f.rank as fts_rank,
        s.rank as semantic_rank,
        coalesce(1.0 / (rrf_k + f.rank), 0.0) * full_text_weight
            + coalesce(1.0 / (rrf_k + s.rank), 0.0) * semantic_weight as combined_score
    from fts f
    full outer join semantic s on f.id = s.id
)
select
    c.id,
    c.source_id,
    c.chunk_index,
    c.heading,
    c.content,
    c.metadata,
    src.source_url,
    src.title as source_title,
    fused.fts_rank,
    fused.semantic_rank,
    fused.combined_score
from fused
join chunks  c   on c.id = fused.id
join sources src on src.id = c.source_id
order by fused.combined_score desc
limit match_count;
$$;

-- Vector-only search, useful for ablations and the eval harness.
create or replace function vector_search(
    query_embedding vector(1024),
    match_count     int default 20
)
returns table (
    id              bigint,
    source_id       bigint,
    chunk_index     int,
    heading         text,
    content         text,
    metadata        jsonb,
    source_url      text,
    source_title    text,
    distance        float
)
language sql stable
as $$
select
    c.id, c.source_id, c.chunk_index, c.heading, c.content, c.metadata,
    s.source_url, s.title as source_title,
    (c.embedding <=> query_embedding)::float as distance
from chunks c
join sources s on s.id = c.source_id
order by c.embedding <=> query_embedding
limit match_count;
$$;
