alter table tenant_subscriptions
  drop constraint if exists tenant_subscriptions_status_check;

alter table tenant_subscriptions
  add constraint tenant_subscriptions_status_check
  check (status in ('unactivated', 'trialing', 'active', 'past_due', 'paused', 'cancelled'));

alter table tenant_plan_limits
  add column if not exists extension_enabled boolean not null default false;

alter table tenant_plan_limits
  add column if not exists listing_enabled boolean not null default false;

update tenant_plan_limits
set
  extension_enabled = case when plan in ('growth', 'scale', 'war-room') then true else false end,
  listing_enabled = case when plan in ('growth', 'scale', 'war-room') then true else false end,
  updated_at = now();

create table if not exists activation_cards (
  id uuid primary key default gen_random_uuid(),
  code_hash varchar(128) not null unique,
  code_suffix varchar(16) not null,
  days integer not null,
  status varchar(32) not null default 'active',
  note text,
  created_by uuid references users(id),
  redeemed_by uuid references users(id),
  redeemed_tenant_id uuid references tenants(id),
  redeemed_at timestamptz,
  voided_by uuid references users(id),
  voided_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (days > 0 and days <= 3660),
  check (status in ('active', 'redeemed', 'voided'))
);

create index if not exists idx_activation_cards_status_created
  on activation_cards (status, created_at desc);

create index if not exists idx_activation_cards_redeemed_tenant
  on activation_cards (redeemed_tenant_id, redeemed_at desc);
