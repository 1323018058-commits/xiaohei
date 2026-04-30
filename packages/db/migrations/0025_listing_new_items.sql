create table if not exists takealot_categories (
  id uuid primary key default gen_random_uuid(),
  category_id integer not null,
  division varchar(128) not null default '',
  department varchar(128) not null default '',
  main_category_id integer not null default 0,
  main_category_name varchar(255) not null default '',
  lowest_category_name varchar(255) not null default '',
  lowest_category_raw varchar(500) not null default '',
  path_en varchar(1024) not null default '',
  path_zh varchar(1024) not null default '',
  search_text text not null default '',
  min_required_images integer not null default 1,
  compliance_certificates jsonb not null default '[]'::jsonb,
  image_requirement_texts jsonb not null default '[]'::jsonb,
  required_attributes jsonb not null default '[]'::jsonb,
  optional_attributes jsonb not null default '[]'::jsonb,
  loadsheet_template_id varchar(128),
  loadsheet_template_name varchar(255),
  raw_payload jsonb,
  import_source varchar(128) not null default 'manual',
  imported_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint uq_takealot_categories_catalog_key unique (
    division,
    department,
    main_category_id,
    category_id
  ),
  check (category_id > 0),
  check (main_category_id >= 0),
  check (min_required_images >= 0),
  check (jsonb_typeof(compliance_certificates) = 'array'),
  check (jsonb_typeof(image_requirement_texts) = 'array'),
  check (jsonb_typeof(required_attributes) = 'array'),
  check (jsonb_typeof(optional_attributes) = 'array')
);

create index if not exists idx_takealot_categories_category_id
  on takealot_categories (category_id);

create index if not exists idx_takealot_categories_department
  on takealot_categories (department);

create index if not exists idx_takealot_categories_main_category
  on takealot_categories (main_category_id, main_category_name);

create index if not exists idx_takealot_categories_lowest_name
  on takealot_categories (lowest_category_name);

create extension if not exists pg_trgm;

create index if not exists idx_takealot_categories_search_trgm
  on takealot_categories using gin (search_text gin_trgm_ops);

create table if not exists takealot_brands (
  id uuid primary key default gen_random_uuid(),
  brand_id varchar(64) not null,
  brand_name varchar(255) not null,
  search_text text not null default '',
  raw_payload jsonb,
  import_source varchar(128) not null default 'manual',
  imported_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint uq_takealot_brands_brand_id unique (brand_id)
);

create index if not exists idx_takealot_brands_name
  on takealot_brands (brand_name);

create index if not exists idx_takealot_brands_search_trgm
  on takealot_brands using gin (search_text gin_trgm_ops);

create table if not exists listing_submissions (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id),
  store_id uuid not null references stores(id),
  listing_id uuid references listings(id),
  source_job_id uuid references listing_jobs(id),
  processing_task_id uuid references task_runs(id),
  idempotency_key varchar(128),
  platform varchar(32) not null default 'takealot',
  sku varchar(128) not null,
  barcode varchar(128) not null,
  title varchar(512) not null,
  subtitle varchar(512) not null default '',
  description text not null default '',
  whats_in_the_box text not null default '',
  category_id integer not null,
  takealot_category_row_id uuid references takealot_categories(id),
  category_path varchar(1024) not null default '',
  brand_id varchar(64) not null default '',
  brand_name varchar(255) not null default '',
  selling_price numeric(18,4),
  rrp numeric(18,4),
  stock_quantity integer not null default 0,
  minimum_leadtime_days integer not null default 0,
  seller_warehouse_id varchar(128),
  length_cm numeric(12,2),
  width_cm numeric(12,2),
  height_cm numeric(12,2),
  weight_kg numeric(12,4),
  image_urls jsonb not null default '[]'::jsonb,
  dynamic_attributes jsonb not null default '{}'::jsonb,
  content_payload jsonb,
  loadsheet_payload jsonb,
  official_response jsonb,
  official_status varchar(64) not null default '',
  takealot_offer_id varchar(128) not null default '',
  takealot_loadsheet_submission_id varchar(128) not null default '',
  status varchar(32) not null default 'draft',
  review_status varchar(32) not null default 'not_submitted',
  error_code varchar(128),
  error_message text,
  submitted_at timestamptz,
  last_checked_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (platform = 'takealot'),
  check (category_id > 0),
  check (selling_price is null or selling_price >= 0),
  check (rrp is null or rrp >= 0),
  check (stock_quantity >= 0),
  check (minimum_leadtime_days >= 0),
  check (length_cm is null or length_cm >= 0),
  check (width_cm is null or width_cm >= 0),
  check (height_cm is null or height_cm >= 0),
  check (weight_kg is null or weight_kg >= 0),
  check (jsonb_typeof(image_urls) = 'array'),
  check (jsonb_typeof(dynamic_attributes) = 'object'),
  check (status in (
    'draft',
    'queued',
    'validating',
    'pending_assets',
    'generating_loadsheet',
    'submitting',
    'submitted',
    'under_review',
    'approved',
    'rejected',
    'failed',
    'cancelled',
    'manual_intervention'
  )),
  check (review_status in (
    'not_submitted',
    'queued',
    'submitted',
    'under_review',
    'approved',
    'rejected',
    'needs_changes',
    'unknown'
  ))
);

create unique index if not exists uq_listing_submissions_store_idempotency
  on listing_submissions (store_id, idempotency_key)
  where idempotency_key is not null;

create index if not exists idx_listing_submissions_store_created
  on listing_submissions (store_id, created_at desc);

create index if not exists idx_listing_submissions_tenant_status
  on listing_submissions (tenant_id, status, created_at desc);

create index if not exists idx_listing_submissions_category
  on listing_submissions (category_id);

create index if not exists idx_listing_submissions_review_status
  on listing_submissions (review_status, last_checked_at desc);

create table if not exists listing_assets (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id),
  store_id uuid not null references stores(id),
  submission_id uuid references listing_submissions(id) on delete cascade,
  asset_type varchar(32) not null default 'image',
  source varchar(32) not null default 'url',
  original_file_name varchar(255),
  file_name varchar(255),
  storage_path text,
  public_url text,
  external_url text,
  content_type varchar(128),
  size_bytes bigint,
  checksum_sha256 varchar(64),
  width integer,
  height integer,
  sort_order integer not null default 0,
  validation_status varchar(32) not null default 'pending',
  validation_errors jsonb not null default '[]'::jsonb,
  raw_payload jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (asset_type in ('image')),
  check (source in ('url', 'upload')),
  check (size_bytes is null or size_bytes >= 0),
  check (width is null or width >= 0),
  check (height is null or height >= 0),
  check (sort_order >= 0),
  check (validation_status in ('pending', 'valid', 'invalid', 'warning')),
  check (jsonb_typeof(validation_errors) = 'array')
);

create index if not exists idx_listing_assets_submission_order
  on listing_assets (submission_id, sort_order, created_at);

create index if not exists idx_listing_assets_store_created
  on listing_assets (store_id, created_at desc);

create table if not exists takealot_loadsheet_template_cache (
  id uuid primary key default gen_random_uuid(),
  category_id integer not null,
  template_key varchar(128) not null default 'default',
  template_id varchar(128),
  template_name varchar(255),
  template_version varchar(64),
  status varchar(32) not null default 'cached',
  required_attributes jsonb not null default '[]'::jsonb,
  optional_attributes jsonb not null default '[]'::jsonb,
  field_definitions jsonb not null default '[]'::jsonb,
  raw_payload jsonb,
  fetched_at timestamptz,
  expires_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint uq_takealot_loadsheet_template_cache_key unique (category_id, template_key),
  check (category_id > 0),
  check (status in ('cached', 'stale', 'failed')),
  check (jsonb_typeof(required_attributes) = 'array'),
  check (jsonb_typeof(optional_attributes) = 'array'),
  check (jsonb_typeof(field_definitions) = 'array')
);

create index if not exists idx_takealot_loadsheet_template_cache_category
  on takealot_loadsheet_template_cache (category_id, updated_at desc);

insert into task_definitions (
  task_type,
  domain,
  display_name,
  queue_name,
  priority,
  max_retries,
  lease_timeout_seconds,
  is_cancellable,
  is_high_risk,
  idempotency_scope,
  retention_days,
  enabled
)
values
  (
    'SUBMIT_LISTING_LOADSHEET',
    'listing',
    'Submit listing loadsheet',
    'listing-submissions',
    'medium',
    3,
    1200,
    true,
    true,
    'task_type+target',
    45,
    false
  ),
  (
    'SYNC_LISTING_SUBMISSION_STATUS',
    'listing',
    'Sync listing submission status',
    'listing-submissions',
    'medium',
    5,
    900,
    true,
    false,
    'task_type+target',
    45,
    false
  ),
  (
    'FINALIZE_LISTING_OFFER',
    'listing',
    'Finalize listing offer',
    'listing-submissions',
    'medium',
    3,
    900,
    true,
    true,
    'task_type+target',
    45,
    false
  )
on conflict (task_type) do update
set display_name = excluded.display_name,
    queue_name = excluded.queue_name,
    max_retries = excluded.max_retries,
    lease_timeout_seconds = excluded.lease_timeout_seconds,
    enabled = excluded.enabled,
    updated_at = now();
