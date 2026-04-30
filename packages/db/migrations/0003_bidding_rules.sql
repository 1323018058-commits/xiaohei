create table if not exists bidding_rules (
  id uuid primary key default gen_random_uuid(),
  store_id uuid not null references stores(id),
  sku varchar(128) not null,
  listing_id varchar(128),
  floor_price numeric(18,4) not null,
  ceiling_price numeric(18,4),
  strategy_type varchar(32) not null default 'manual',
  is_active boolean not null default true,
  version bigint not null default 1,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (store_id, sku),
  check (floor_price > 0),
  check (ceiling_price is null or ceiling_price >= floor_price)
);

create index if not exists idx_bidding_rules_store_active
  on bidding_rules (store_id, is_active);

create index if not exists idx_bidding_rules_store_sku
  on bidding_rules (store_id, sku);
