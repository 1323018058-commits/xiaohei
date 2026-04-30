-- Atomic worker claims live on listing_submissions because the external
-- Takealot calls must be guarded by the same row that stores the eventual
-- submission/offer ids. A stale task can only retry after its claim expires.
alter table listing_submissions
  add column if not exists loadsheet_submit_claim_task_id uuid references task_runs(id),
  add column if not exists loadsheet_submit_claim_token varchar(64),
  add column if not exists loadsheet_submit_claim_expires_at timestamptz,
  add column if not exists offer_finalize_claim_task_id uuid references task_runs(id),
  add column if not exists offer_finalize_claim_token varchar(64),
  add column if not exists offer_finalize_claim_expires_at timestamptz;

comment on column listing_submissions.loadsheet_submit_claim_task_id is
  'Worker task that currently owns the Takealot loadsheet submit side-effect claim.';
comment on column listing_submissions.loadsheet_submit_claim_token is
  'Opaque token required to write loadsheet submit success/failure, preventing late workers from overwriting success.';
comment on column listing_submissions.loadsheet_submit_claim_expires_at is
  'Time after which another worker may reclaim an unfinished loadsheet submit.';
comment on column listing_submissions.offer_finalize_claim_task_id is
  'Worker task that currently owns the Takealot Offer finalize side-effect claim.';
comment on column listing_submissions.offer_finalize_claim_token is
  'Opaque token required to write Offer finalize success/failure, preventing duplicate Offer writes.';
comment on column listing_submissions.offer_finalize_claim_expires_at is
  'Time after which another worker may reclaim an unfinished Offer finalize.';

create index if not exists idx_listing_submissions_loadsheet_submit_claim
  on listing_submissions (loadsheet_submit_claim_expires_at, updated_at)
  where takealot_loadsheet_submission_id = ''
    and status in ('content_queued', 'content_submit_failed', 'queue_failed', 'content_submitting');

create index if not exists idx_listing_submissions_offer_finalize_claim
  on listing_submissions (offer_finalize_claim_expires_at, updated_at)
  where review_status = 'approved'
    and takealot_offer_id = ''
    and finalized_at is null;
