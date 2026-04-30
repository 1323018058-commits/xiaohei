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
  'EXTENSION_LIST_NOW',
  'extension',
  'Create listing from extension',
  'extension-listing',
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
