create table if not exists selection_ingest_runs (
  id uuid primary key default gen_random_uuid(),
  platform varchar(32) not null default 'takealot',
  status varchar(32) not null default 'queued',
  source varchar(64) not null default 'takealot_site',
  strategy varchar(64) not null default 'category_price_buckets',
  category_bucket_count integer not null default 0,
  price_bucket_count integer not null default 0,
  discovered_count bigint not null default 0,
  processed_count bigint not null default 0,
  inserted_count bigint not null default 0,
  updated_count bigint not null default 0,
  failed_count bigint not null default 0,
  started_at timestamptz,
  finished_at timestamptz,
  error_message text,
  metadata jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (platform = 'takealot'),
  check (status in ('queued', 'running', 'succeeded', 'failed', 'cancelled'))
);

create index if not exists idx_selection_ingest_runs_status_created
  on selection_ingest_runs (status, created_at desc);

create table if not exists selection_products (
  id uuid primary key default gen_random_uuid(),
  platform varchar(32) not null default 'takealot',
  platform_product_id varchar(128) not null,
  image_url text,
  title varchar(512) not null,
  main_category varchar(255),
  category_level1 varchar(255),
  category_level2 varchar(255),
  category_level3 varchar(255),
  brand varchar(255),
  currency varchar(8) not null default 'ZAR',
  current_price numeric(18,4),
  rating numeric(4,2),
  total_review_count integer,
  rating_5_count integer,
  rating_4_count integer,
  rating_3_count integer,
  rating_2_count integer,
  rating_1_count integer,
  latest_review_at timestamptz,
  stock_status varchar(64),
  offer_count integer,
  current_snapshot_week date,
  status varchar(32) not null default 'active',
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (platform, platform_product_id),
  check (platform = 'takealot'),
  check (current_price is null or current_price >= 0),
  check (rating is null or (rating >= 0 and rating <= 5)),
  check (total_review_count is null or total_review_count >= 0),
  check (rating_5_count is null or rating_5_count >= 0),
  check (rating_4_count is null or rating_4_count >= 0),
  check (rating_3_count is null or rating_3_count >= 0),
  check (rating_2_count is null or rating_2_count >= 0),
  check (rating_1_count is null or rating_1_count >= 0),
  check (offer_count is null or offer_count >= 0),
  check (status in ('active', 'unavailable', 'stale', 'deleted'))
);

create index if not exists idx_selection_products_category_price
  on selection_products (main_category, category_level1, category_level2, category_level3, current_price);

create index if not exists idx_selection_products_brand
  on selection_products (brand);

create index if not exists idx_selection_products_rating_reviews
  on selection_products (rating desc, total_review_count desc);

create index if not exists idx_selection_products_stock_offer
  on selection_products (stock_status, offer_count);

create index if not exists idx_selection_products_updated
  on selection_products (updated_at desc);

create index if not exists idx_selection_products_title_search
  on selection_products using gin (to_tsvector('simple', coalesce(title, '')));

create table if not exists selection_product_snapshots (
  id uuid primary key default gen_random_uuid(),
  product_id uuid not null references selection_products(id) on delete cascade,
  ingest_run_id uuid references selection_ingest_runs(id),
  snapshot_week date not null,
  currency varchar(8) not null default 'ZAR',
  current_price numeric(18,4),
  rating numeric(4,2),
  total_review_count integer,
  rating_5_count integer,
  rating_4_count integer,
  rating_3_count integer,
  rating_2_count integer,
  rating_1_count integer,
  latest_review_at timestamptz,
  stock_status varchar(64),
  offer_count integer,
  raw_payload jsonb,
  captured_at timestamptz not null default now(),
  unique (product_id, snapshot_week),
  check (current_price is null or current_price >= 0),
  check (rating is null or (rating >= 0 and rating <= 5)),
  check (total_review_count is null or total_review_count >= 0),
  check (offer_count is null or offer_count >= 0)
);

create index if not exists idx_selection_snapshots_week_price
  on selection_product_snapshots (snapshot_week desc, current_price);

create index if not exists idx_selection_snapshots_product_captured
  on selection_product_snapshots (product_id, captured_at desc);
