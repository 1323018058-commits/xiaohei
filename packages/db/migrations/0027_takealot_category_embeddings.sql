do $$
begin
  if exists (select 1 from pg_available_extensions where name = 'vector') then
    execute 'create extension if not exists vector';
  end if;
exception when others then
  null;
end $$;

create table if not exists takealot_category_embeddings (
  id uuid primary key default gen_random_uuid(),
  category_id integer not null,
  embedding_model varchar(128) not null,
  embedding_dimensions integer not null,
  embedding_text text not null,
  embedding_vector jsonb not null default '[]'::jsonb,
  embedding_hash varchar(64) not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint uq_takealot_category_embeddings_key unique (
    category_id,
    embedding_model,
    embedding_dimensions
  ),
  check (category_id > 0),
  check (embedding_dimensions > 0),
  check (jsonb_typeof(embedding_vector) = 'array')
);

create index if not exists idx_takealot_category_embeddings_category
  on takealot_category_embeddings (category_id);

create index if not exists idx_takealot_category_embeddings_model
  on takealot_category_embeddings (embedding_model, embedding_dimensions, updated_at desc);

create index if not exists idx_takealot_category_embeddings_hash
  on takealot_category_embeddings (embedding_hash);

do $$
begin
  if exists (select 1 from pg_extension where extname = 'vector')
     and not exists (
       select 1
       from information_schema.columns
       where table_name = 'takealot_category_embeddings'
         and column_name = 'embedding_vector_pg'
     ) then
    execute 'alter table takealot_category_embeddings add column embedding_vector_pg vector(1024)';
  end if;
exception when others then
  null;
end $$;

do $$
begin
  if exists (
       select 1
       from information_schema.columns
       where table_name = 'takealot_category_embeddings'
         and column_name = 'embedding_vector_pg'
     ) then
    begin
      execute 'create index if not exists idx_takealot_category_embeddings_vector_hnsw on takealot_category_embeddings using hnsw (embedding_vector_pg vector_cosine_ops)';
    exception when others then
      begin
        execute 'create index if not exists idx_takealot_category_embeddings_vector_ivfflat on takealot_category_embeddings using ivfflat (embedding_vector_pg vector_cosine_ops)';
      exception when others then
        null;
      end;
    end;
  end if;
end $$;
