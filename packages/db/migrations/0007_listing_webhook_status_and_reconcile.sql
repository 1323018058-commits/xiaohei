do $$
begin
  if exists (
    select 1
    from pg_constraint
    where conname = 'listings_sync_status_check'
  ) then
    alter table listings drop constraint listings_sync_status_check;
  end if;

  alter table listings
    add constraint listings_sync_status_check
    check (sync_status in ('synced', 'stale', 'error', 'webhook_synced'));
end $$;

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
  'SYNC_STORE_LISTINGS',
  'store',
  'Reconcile Takealot listings',
  'store-sync',
  'medium',
  3,
  900,
  true,
  false,
  'task_type+target',
  30,
  true
)
on conflict (task_type) do update
set display_name = excluded.display_name,
    queue_name = excluded.queue_name,
    enabled = excluded.enabled;
