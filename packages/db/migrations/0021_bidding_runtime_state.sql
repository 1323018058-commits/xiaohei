alter table bidding_rules
  add column if not exists next_check_at timestamptz,
  add column if not exists buybox_fetch_fail_count integer not null default 0,
  add column if not exists buybox_last_error text not null default '',
  add column if not exists buybox_last_success_at timestamptz,
  add column if not exists buybox_next_retry_at timestamptz,
  add column if not exists buybox_status varchar(30) not null default 'idle',
  add column if not exists repricing_blocked_reason text not null default '',
  add column if not exists last_action varchar(40) not null default '',
  add column if not exists last_reprice_at timestamptz,
  add column if not exists last_suggested_price numeric(18,4),
  add column if not exists last_applied_price numeric(18,4),
  add column if not exists last_buybox_price numeric(18,4),
  add column if not exists last_next_offer_price numeric(18,4),
  add column if not exists last_cycle_dry_run boolean not null default true,
  add column if not exists last_cycle_error text not null default '',
  add column if not exists last_decision jsonb;

create index if not exists idx_bidding_rules_repricing_due
  on bidding_rules (next_check_at, store_id)
  where is_active = true and floor_price > 0;

update bidding_rules
set ceiling_price = null
where ceiling_price is not null;
