create extension if not exists pg_trgm;

create index if not exists idx_listings_store_active_updated
  on listings (store_id, updated_at desc, sku)
  where sync_status <> 'stale';

create index if not exists idx_listings_active_sku_trgm
  on listings using gin (sku gin_trgm_ops)
  where sync_status <> 'stale';

create index if not exists idx_listings_active_title_trgm
  on listings using gin (title gin_trgm_ops)
  where sync_status <> 'stale';

create index if not exists idx_order_items_order_sku
  on order_items (order_id, sku);
