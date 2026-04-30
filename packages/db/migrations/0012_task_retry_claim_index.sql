drop index if exists idx_task_runs_claim_ready;

create index if not exists idx_task_runs_claim_ready
  on task_runs (task_type, status, created_at asc)
  where status in ('queued', 'leased', 'waiting_retry');
