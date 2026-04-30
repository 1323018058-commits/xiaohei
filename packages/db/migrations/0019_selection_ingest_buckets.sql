create table if not exists selection_ingest_buckets (
  id uuid primary key default gen_random_uuid(),
  ingest_run_id uuid not null references selection_ingest_runs(id) on delete cascade,
  bucket_key text not null,
  seed_name text not null,
  department_slug text,
  category_ref text not null,
  main_category varchar(255),
  category_level1 varchar(255),
  category_level2 varchar(255),
  category_level3 varchar(255),
  url text,
  min_price numeric(18,4) not null,
  max_price numeric(18,4) not null,
  depth integer not null default 0,
  status varchar(32) not null default 'queued',
  page_count integer not null default 0,
  total_count integer,
  discovered_count integer not null default 0,
  persisted_count integer not null default 0,
  failed_count integer not null default 0,
  split_from_id uuid references selection_ingest_buckets(id) on delete set null,
  error_message text,
  metadata jsonb,
  started_at timestamptz,
  finished_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (ingest_run_id, bucket_key),
  check (status in ('queued', 'running', 'succeeded', 'failed', 'skipped', 'split')),
  check (min_price >= 0),
  check (max_price >= min_price),
  check (depth >= 0)
);

create index if not exists idx_selection_ingest_buckets_run_status
  on selection_ingest_buckets (ingest_run_id, status, updated_at);

create index if not exists idx_selection_ingest_buckets_category_price
  on selection_ingest_buckets (
    main_category,
    category_level1,
    category_level2,
    category_level3,
    min_price,
    max_price
  );
