alter table selection_products
  add column if not exists merchant_package_weight_kg numeric(12,4),
  add column if not exists merchant_package_length_cm numeric(12,2),
  add column if not exists merchant_package_width_cm numeric(12,2),
  add column if not exists merchant_package_height_cm numeric(12,2),
  add column if not exists merchant_package_volume_cm3 numeric(18,2),
  add column if not exists merchant_package_variant_count integer,
  add column if not exists merchant_package_updated_at timestamptz,
  add column if not exists merchant_package_source varchar(64);

do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'chk_selection_products_merchant_package_weight'
  ) then
    alter table selection_products
      add constraint chk_selection_products_merchant_package_weight
      check (merchant_package_weight_kg is null or merchant_package_weight_kg >= 0) not valid;
  end if;

  if not exists (
    select 1 from pg_constraint where conname = 'chk_selection_products_merchant_package_length'
  ) then
    alter table selection_products
      add constraint chk_selection_products_merchant_package_length
      check (merchant_package_length_cm is null or merchant_package_length_cm >= 0) not valid;
  end if;

  if not exists (
    select 1 from pg_constraint where conname = 'chk_selection_products_merchant_package_width'
  ) then
    alter table selection_products
      add constraint chk_selection_products_merchant_package_width
      check (merchant_package_width_cm is null or merchant_package_width_cm >= 0) not valid;
  end if;

  if not exists (
    select 1 from pg_constraint where conname = 'chk_selection_products_merchant_package_height'
  ) then
    alter table selection_products
      add constraint chk_selection_products_merchant_package_height
      check (merchant_package_height_cm is null or merchant_package_height_cm >= 0) not valid;
  end if;

  if not exists (
    select 1 from pg_constraint where conname = 'chk_selection_products_merchant_package_volume'
  ) then
    alter table selection_products
      add constraint chk_selection_products_merchant_package_volume
      check (merchant_package_volume_cm3 is null or merchant_package_volume_cm3 >= 0) not valid;
  end if;

  if not exists (
    select 1 from pg_constraint where conname = 'chk_selection_products_merchant_package_variant_count'
  ) then
    alter table selection_products
      add constraint chk_selection_products_merchant_package_variant_count
      check (merchant_package_variant_count is null or merchant_package_variant_count >= 0) not valid;
  end if;
end $$;

create index if not exists idx_selection_products_merchant_package_updated
  on selection_products (merchant_package_updated_at desc);

create index if not exists idx_selection_products_merchant_package_weight
  on selection_products (merchant_package_weight_kg);

create index if not exists idx_selection_products_merchant_package_volume
  on selection_products (merchant_package_volume_cm3);

create table if not exists selection_product_variants (
  id uuid primary key default gen_random_uuid(),
  product_id uuid not null references selection_products(id) on delete cascade,
  platform varchar(32) not null default 'takealot',
  platform_product_id varchar(128) not null,
  tsin_id bigint not null,
  gtin varchar(255),
  title varchar(512),
  size varchar(128),
  basic_colors varchar(255),
  color_name varchar(255),
  merchant_package_weight_kg numeric(12,4),
  merchant_package_length_cm numeric(12,2),
  merchant_package_width_cm numeric(12,2),
  merchant_package_height_cm numeric(12,2),
  merchant_package_volume_cm3 numeric(18,2),
  merchant_package_weight_raw text,
  merchant_package_dimensions_raw text,
  raw_payload jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (platform, tsin_id),
  check (platform = 'takealot'),
  check (merchant_package_weight_kg is null or merchant_package_weight_kg >= 0),
  check (merchant_package_length_cm is null or merchant_package_length_cm >= 0),
  check (merchant_package_width_cm is null or merchant_package_width_cm >= 0),
  check (merchant_package_height_cm is null or merchant_package_height_cm >= 0),
  check (merchant_package_volume_cm3 is null or merchant_package_volume_cm3 >= 0)
);

create index if not exists idx_selection_product_variants_product
  on selection_product_variants (product_id);

create index if not exists idx_selection_product_variants_plid
  on selection_product_variants (platform_product_id);

create index if not exists idx_selection_product_variants_updated
  on selection_product_variants (updated_at desc);
