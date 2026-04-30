alter table listings
  add column if not exists platform_product_id varchar(128);

create index if not exists idx_listings_store_platform_product_id
  on listings (store_id, platform_product_id);

create table if not exists library_products (
  id uuid primary key default gen_random_uuid(),
  platform varchar(32) not null,
  external_product_id varchar(128) not null,
  title varchar(512) not null,
  brand varchar(255),
  category varchar(255),
  fact_status varchar(32) not null default 'pending_enrichment',
  merchant_packaged_weight_raw varchar(128),
  merchant_packaged_dimensions_raw varchar(128),
  cbs_package_weight_raw varchar(128),
  cbs_package_dimensions_raw varchar(128),
  consolidated_packaged_dimensions_raw varchar(128),
  raw_payload jsonb,
  confidence_score numeric(5,2),
  last_refreshed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (platform, external_product_id),
  check (platform = 'takealot'),
  check (fact_status in ('pending_enrichment', 'partial', 'complete', 'stale'))
);

create index if not exists idx_library_products_platform_category
  on library_products (platform, category);

create table if not exists tenant_product_guardrails (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id),
  store_id uuid not null references stores(id),
  product_id uuid not null references library_products(id),
  protected_floor_price numeric(18,4) not null,
  status varchar(32) not null default 'pending_listing_link',
  linked_listing_id uuid references listings(id),
  linked_bidding_rule_id uuid references bidding_rules(id),
  autobid_sync_status varchar(32) not null default 'pending',
  source varchar(32) not null default 'extension',
  last_synced_at timestamptz,
  last_error_code varchar(64),
  last_error_message text,
  created_by uuid references users(id),
  updated_by uuid references users(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (tenant_id, store_id, product_id),
  check (protected_floor_price > 0),
  check (status in ('pending_listing_link', 'synced_autobid', 'sync_failed', 'stale')),
  check (autobid_sync_status in ('pending', 'synced', 'failed'))
);

create index if not exists idx_tenant_product_guardrails_store_status
  on tenant_product_guardrails (store_id, status, updated_at desc);

create table if not exists extension_auth_tokens (
  id uuid primary key default gen_random_uuid(),
  token_hash varchar(128) not null unique,
  tenant_id uuid not null references tenants(id),
  user_id uuid not null references users(id),
  store_id uuid references stores(id),
  expires_at timestamptz not null,
  last_seen_at timestamptz,
  created_at timestamptz not null default now()
);

create index if not exists idx_extension_auth_tokens_user_expires
  on extension_auth_tokens (user_id, expires_at);
