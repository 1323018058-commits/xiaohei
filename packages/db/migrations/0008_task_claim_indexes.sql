create index if not exists idx_task_runs_claim_ready
  on task_runs (task_type, status, created_at asc)
  where status in ('queued', 'leased');

create index if not exists idx_task_runs_lease_expiry
  on task_runs (status, lease_expires_at)
  where status = 'leased';

create index if not exists idx_task_runs_retry_schedule
  on task_runs (status, next_retry_at)
  where status in ('queued', 'leased', 'waiting_retry');
