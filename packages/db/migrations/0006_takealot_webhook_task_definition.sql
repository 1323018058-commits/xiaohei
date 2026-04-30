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
  'TAKEALOT_WEBHOOK_PROCESS',
  'webhook',
  'Process Takealot webhook',
  'takealot-webhooks',
  'high',
  3,
  300,
  true,
  false,
  'delivery_id',
  30,
  true
)
on conflict (task_type) do update
set display_name = excluded.display_name,
    queue_name = excluded.queue_name,
    enabled = excluded.enabled;
