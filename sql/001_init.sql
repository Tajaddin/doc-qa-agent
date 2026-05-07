-- Schema for the doc-qa agent.
-- One row per crawled page in `sources`, one row per retrieval-sized chunk in `chunks`.
-- Eval harness questions live in `eval_cases` so the dataset travels with the repo.

create extension if not exists vector;

-- ---------- sources ----------
create table if not exists sources (
    id          bigserial primary key,
    source_url  text unique not null,
    title       text,
    checksum    text,
    fetched_at  timestamptz not null default now(),
    metadata    jsonb       not null default '{}'::jsonb
);

create index if not exists sources_url_idx on sources (source_url);

-- ---------- chunks ----------
create table if not exists chunks (
    id           bigserial primary key,
    source_id    bigint  not null references sources(id) on delete cascade,
    chunk_index  int     not null,
    heading      text,
    content      text    not null,
    token_count  int,
    embedding    vector(1024),
    fts          tsvector,
    metadata     jsonb   not null default '{}'::jsonb,
    unique (source_id, chunk_index)
);

create index if not exists chunks_source_idx on chunks (source_id);

-- HNSW for approximate nearest neighbour search on cosine distance.
create index if not exists chunks_embedding_hnsw
    on chunks using hnsw (embedding vector_cosine_ops);

-- GIN over the tsvector for lexical full-text search.
create index if not exists chunks_fts_gin
    on chunks using gin (fts);

-- Trigger keeps fts in sync with content + heading on insert/update.
create or replace function chunks_update_fts() returns trigger as $$
begin
    new.fts := setweight(to_tsvector('english', coalesce(new.heading, '')), 'A')
            || setweight(to_tsvector('english', coalesce(new.content, '')), 'B');
    return new;
end;
$$ language plpgsql;

drop trigger if exists chunks_fts_trigger on chunks;
create trigger chunks_fts_trigger
    before insert or update of content, heading on chunks
    for each row execute function chunks_update_fts();

-- ---------- eval cases ----------
create table if not exists eval_cases (
    id                bigserial primary key,
    question          text not null,
    gold_answer       text,
    gold_source_urls  text[],
    split             text default 'dev',
    metadata          jsonb not null default '{}'::jsonb
);

-- ---------- helper view ----------
create or replace view chunk_with_source as
select
    c.id, c.source_id, c.chunk_index, c.heading, c.content,
    c.token_count, c.embedding, c.fts, c.metadata,
    s.source_url, s.title as source_title
from chunks c
join sources s on s.id = c.source_id;
