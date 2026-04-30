create table if not exists bidding_store_runtime_state (
  store_id uuid primary key references stores(id) on delete cascade,
  is_running boolean not null default false,
  last_started_at timestamptz,
  last_stopped_at timestamptz,
  last_manual_cycle_at timestamptz,
  last_worker_cycle_at timestamptz,
  last_cycle_summary jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_bidding_store_runtime_running
  on bidding_store_runtime_state (is_running, updated_at desc);
