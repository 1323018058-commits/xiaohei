do $$
declare
  constraint_name text;
begin
  alter table listing_submissions
    add column if not exists stage varchar(32) not null default 'draft';

  select conname
    into constraint_name
  from pg_constraint
  where conrelid = 'listing_assets'::regclass
    and contype = 'c'
    and pg_get_constraintdef(oid) ilike '%asset_type%'
  limit 1;
  if constraint_name is not null then
    execute format('alter table listing_assets drop constraint %I', constraint_name);
  end if;

  alter table listing_assets
    add constraint listing_assets_asset_type_check
    check (asset_type in ('image', 'loadsheet'));

  constraint_name := null;
  select conname
    into constraint_name
  from pg_constraint
  where conrelid = 'listing_assets'::regclass
    and contype = 'c'
    and pg_get_constraintdef(oid) ilike '%source%'
  limit 1;
  if constraint_name is not null then
    execute format('alter table listing_assets drop constraint %I', constraint_name);
  end if;

  alter table listing_assets
    add constraint listing_assets_source_check
    check (source in ('url', 'upload', 'generated'));

  constraint_name := null;
  select conname
    into constraint_name
  from pg_constraint
  where conrelid = 'listing_submissions'::regclass
    and contype = 'c'
    and pg_get_constraintdef(oid) ilike '%status%'
    and pg_get_constraintdef(oid) not ilike '%review_status%'
  limit 1;
  if constraint_name is not null then
    execute format('alter table listing_submissions drop constraint %I', constraint_name);
  end if;

  alter table listing_submissions
    add constraint listing_submissions_status_check
    check (status in (
      'draft',
      'queued',
      'validating',
      'pending_assets',
      'generating_loadsheet',
      'submitting',
      'submitted',
      'under_review',
      'approved',
      'rejected',
      'failed',
      'cancelled',
      'manual_intervention',
      'content_queued',
      'content_submitting',
      'content_submitted',
      'content_submit_failed',
      'queue_failed'
    ));

  constraint_name := null;
  select conname
    into constraint_name
  from pg_constraint
  where conrelid = 'listing_submissions'::regclass
    and contype = 'c'
    and pg_get_constraintdef(oid) ilike '%stage%'
    and pg_get_constraintdef(oid) not ilike '%review_status%'
  limit 1;
  if constraint_name is not null then
    execute format('alter table listing_submissions drop constraint %I', constraint_name);
  end if;

  alter table listing_submissions
    add constraint listing_submissions_stage_check
    check (stage in (
      'draft',
      'queued',
      'validating',
      'generating_loadsheet',
      'submitting',
      'submitted',
      'failed',
      'cancelled',
      'manual_intervention'
    ));
end $$;

create index if not exists idx_listing_assets_submission_type
  on listing_assets (submission_id, asset_type, created_at desc);

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
  'SUBMIT_LISTING_LOADSHEET',
  'listing',
  'Submit listing loadsheet',
  'listing-submissions',
  'medium',
  3,
  1200,
  true,
  true,
  'task_type+target',
  45,
  true
)
on conflict (task_type) do update
set display_name = excluded.display_name,
    queue_name = excluded.queue_name,
    max_retries = greatest(task_definitions.max_retries, excluded.max_retries),
    lease_timeout_seconds = excluded.lease_timeout_seconds,
    enabled = true,
    updated_at = now();
