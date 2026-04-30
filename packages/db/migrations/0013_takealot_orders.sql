create table if not exists orders (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id),
  store_id uuid not null references stores(id),
  external_order_id varchar(128) not null,
  order_number varchar(128),
  status varchar(64) not null,
  fulfillment_status varchar(64),
  total_amount numeric(18,4),
  currency varchar(16) not null default 'ZAR',
  placed_at timestamptz,
  last_synced_at timestamptz,
  raw_payload jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (store_id, external_order_id),
  check (total_amount is null or total_amount >= 0)
);

create index if not exists idx_orders_tenant_created
  on orders (tenant_id, created_at desc);

create index if not exists idx_orders_store_status
  on orders (store_id, status);

create index if not exists idx_orders_store_placed
  on orders (store_id, placed_at desc);

create table if not exists order_items (
  id uuid primary key default gen_random_uuid(),
  order_id uuid not null references orders(id) on delete cascade,
  external_order_item_id varchar(128) not null,
  sku varchar(128) not null,
  title varchar(512),
  quantity integer not null default 1,
  unit_price numeric(18,4),
  status varchar(64),
  raw_payload jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (order_id, external_order_item_id),
  check (quantity > 0),
  check (unit_price is null or unit_price >= 0)
);

create index if not exists idx_order_items_order
  on order_items (order_id);

create index if not exists idx_order_items_sku
  on order_items (sku);

create table if not exists order_events (
  id uuid primary key default gen_random_uuid(),
  order_id uuid not null references orders(id) on delete cascade,
  event_type varchar(128) not null,
  status varchar(64),
  message text,
  payload jsonb,
  occurred_at timestamptz not null default now(),
  created_at timestamptz not null default now()
);

create index if not exists idx_order_events_order_created
  on order_events (order_id, created_at desc);

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
values (
  'SYNC_TAKEALOT_ORDERS',
  'orders',
  'Sync Takealot orders',
  'order-sync',
  'medium',
  3,
  900,
  true,
  false,
  'task_type+store',
  30,
  true
)
on conflict (task_type) do update
set display_name = excluded.display_name,
    queue_name = excluded.queue_name,
    enabled = excluded.enabled;
