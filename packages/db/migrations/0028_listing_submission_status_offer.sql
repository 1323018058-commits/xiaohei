-- Phase 8 keeps the existing loadsheet submission flow intact and adds the
-- review/offer lifecycle that happens after Takealot accepts the loadsheet.
-- The extra timestamps and error field are intentionally on listing_submissions
-- so retries can make idempotent decisions without reading task history.
alter table listing_submissions
  add column if not exists finalized_at timestamptz,
  add column if not exists offer_error_message text,
  add column if not exists last_status_sync_at timestamptz,
  add column if not exists platform_product_id varchar(128);

do $$
begin
  -- These checks are rewritten instead of loosened so every status transition
  -- remains explicit. Phase 8 adds content review states and the approved-only
  -- offer finalization states used by the worker.
  alter table listing_submissions
    drop constraint if exists listing_submissions_status_check;

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
      'content_reviewed',
      'content_review_failed',
      'content_rejected',
      'offer_submitting',
      'offer_submitted',
      'offer_failed',
      'queue_failed'
    ));

  alter table listing_submissions
    drop constraint if exists listing_submissions_stage_check;

  alter table listing_submissions
    add constraint listing_submissions_stage_check
    check (stage in (
      'draft',
      'queued',
      'validating',
      'generating_loadsheet',
      'submitting',
      'submitted',
      'under_review',
      'reviewed',
      'approved',
      'rejected',
      'offer_submitting',
      'offer_submitted',
      'offer_failed',
      'failed',
      'cancelled',
      'manual_intervention'
    ));

  alter table listing_submissions
    drop constraint if exists listing_submissions_review_status_check;

  alter table listing_submissions
    add constraint listing_submissions_review_status_check
    check (review_status in (
      'not_submitted',
      'queued',
      'submitted',
      'under_review',
      'approved',
      'partial',
      'rejected',
      'needs_changes',
      'failed',
      'unknown'
    ));
end $$;

comment on column listing_submissions.last_status_sync_at is
  'Last time the worker asked Takealot for the loadsheet review status; sync failures must not erase an approved state.';
comment on column listing_submissions.finalized_at is
  'Set only after an approved loadsheet has been finalized into a Takealot offer.';
comment on column listing_submissions.offer_error_message is
  'Non-sensitive error text from the offer finalization step; API keys must never be stored here.';
comment on column listing_submissions.platform_product_id is
  'Best-effort Takealot product identifier from the created/associated offer, used to link the local listings row.';

create index if not exists idx_listing_submissions_status_sync_due
  on listing_submissions (store_id, review_status, last_status_sync_at)
  where takealot_loadsheet_submission_id <> ''
    and review_status in ('submitted', 'under_review', 'unknown', 'partial');

create index if not exists idx_listing_submissions_offer_finalize_due
  on listing_submissions (store_id, finalized_at, updated_at)
  where review_status = 'approved'
    and takealot_offer_id = '';

-- Enable the two post-submit worker tasks. They use task_type+target
-- idempotency as documentation even though this app_state implementation does
-- not currently enforce it on insert; the worker still guards every external
-- side effect by reading listing_submissions first.
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
values
  (
    'SYNC_LISTING_SUBMISSION_STATUS',
    'listing',
    'Sync listing submission status',
    'listing-submissions',
    'medium',
    5,
    900,
    true,
    false,
    'task_type+target',
    45,
    true
  ),
  (
    'FINALIZE_LISTING_OFFER',
    'listing',
    'Finalize listing offer',
    'listing-submissions',
    'medium',
    3,
    900,
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
