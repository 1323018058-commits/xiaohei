create table if not exists tenant_plan_limits (
  plan varchar(64) primary key,
  display_name varchar(128) not null,
  max_users integer not null,
  max_stores integer not null,
  max_active_sync_tasks integer not null,
  max_listings integer not null,
  autobid_enabled boolean not null default false,
  sync_enabled boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (max_users > 0),
  check (max_stores > 0),
  check (max_active_sync_tasks > 0),
  check (max_listings > 0)
);

insert into tenant_plan_limits (
  plan,
  display_name,
  max_users,
  max_stores,
  max_active_sync_tasks,
  max_listings,
  autobid_enabled,
  sync_enabled
) values
  ('starter', 'Starter', 3, 1, 2, 500, false, true),
  ('growth', 'Growth', 10, 3, 5, 5000, true, true),
  ('scale', 'Scale', 100, 20, 20, 50000, true, true),
  ('war-room', 'War Room', 1000, 200, 100, 1000000, true, true)
on conflict (plan) do update set
  display_name = excluded.display_name,
  max_users = excluded.max_users,
  max_stores = excluded.max_stores,
  max_active_sync_tasks = excluded.max_active_sync_tasks,
  max_listings = excluded.max_listings,
  autobid_enabled = excluded.autobid_enabled,
  sync_enabled = excluded.sync_enabled,
  updated_at = now();

create table if not exists tenant_subscriptions (
  tenant_id uuid primary key references tenants(id),
  plan varchar(64) not null references tenant_plan_limits(plan),
  status varchar(32) not null default 'active',
  trial_ends_at timestamptz,
  current_period_ends_at timestamptz,
  updated_by uuid references users(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (status in ('trialing', 'active', 'past_due', 'paused', 'cancelled'))
);

create index if not exists idx_tenant_subscriptions_plan_status
  on tenant_subscriptions (plan, status);

insert into tenant_subscriptions (
  tenant_id,
  plan,
  status,
  created_at,
  updated_at
)
select
  t.id,
  case
    when tpl.plan is not null then t.plan
    else 'war-room'
  end as plan,
  'active',
  now(),
  now()
from tenants t
left join tenant_plan_limits tpl on tpl.plan = t.plan
on conflict (tenant_id) do nothing;
