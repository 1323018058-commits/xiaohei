create table if not exists listings (
  id uuid primary key default gen_random_uuid(),
  store_id uuid not null references stores(id),
  external_listing_id varchar(128) not null,
  sku varchar(128) not null,
  title varchar(512) not null,
  platform_price numeric(18,4),
  stock_quantity integer,
  currency varchar(16) not null default 'USD',
  sync_status varchar(32) not null default 'synced',
  raw_payload jsonb,
  last_synced_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (store_id, external_listing_id),
  check (sync_status in ('synced', 'stale', 'error')),
  check (platform_price is null or platform_price >= 0),
  check (stock_quantity is null or stock_quantity >= 0)
);

create index if not exists idx_listings_store_sku
  on listings (store_id, sku);

create index if not exists idx_listings_store_sync_status
  on listings (store_id, sync_status);

do $$
begin
  if exists (
    select 1
    from pg_constraint
    where conname = 'task_runs_status_check'
  ) then
    alter table task_runs drop constraint task_runs_status_check;
  end if;

  alter table task_runs
    add constraint task_runs_status_check
    check (status in (
      'created',
      'queued',
      'leased',
      'running',
      'waiting_dependency',
      'waiting_retry',
      'cancel_requested',
      'cancelled',
      'succeeded',
      'failed',
      'partial',
      'failed_retryable',
      'failed_final',
      'dead_letter',
      'manual_intervention',
      'timed_out',
      'quarantined'
    ));
end $$;
