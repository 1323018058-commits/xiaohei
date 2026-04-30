create table if not exists listing_jobs (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id),
  store_id uuid not null references stores(id),
  product_id uuid references library_products(id),
  guardrail_id uuid references tenant_product_guardrails(id),
  entry_task_id uuid references task_runs(id),
  processing_task_id uuid references task_runs(id),
  platform varchar(32) not null default 'takealot',
  source varchar(32) not null default 'extension',
  source_ref varchar(128),
  title varchar(512) not null,
  status varchar(32) not null default 'queued',
  stage varchar(64) not null default 'queued',
  note text,
  raw_payload jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (platform = 'takealot'),
  check (source in ('extension', 'manual')),
  check (status in ('queued', 'processing', 'ready_to_submit', 'manual_intervention', 'failed')),
  check (stage in ('created', 'queued', 'processing', 'prepared', 'waiting_manual', 'failed'))
);

create index if not exists idx_listing_jobs_store_created
  on listing_jobs (store_id, created_at desc);

create index if not exists idx_listing_jobs_status_created
  on listing_jobs (status, created_at desc);

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
  'PROCESS_LISTING_JOB',
  'listing',
  'Process listing job',
  'listing-jobs',
  'medium',
  3,
  900,
  true,
  true,
  'task_type+target',
  30,
  true
)
on conflict (task_type) do update
set display_name = excluded.display_name,
    queue_name = excluded.queue_name,
    enabled = excluded.enabled;
