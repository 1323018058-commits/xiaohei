create extension if not exists pgcrypto;

create table if not exists tenants (
  id uuid primary key default gen_random_uuid(),
  slug varchar(64) not null unique,
  name varchar(128) not null,
  status varchar(32) not null default 'active',
  plan varchar(64) not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (status in ('active', 'disabled', 'suspended'))
);

create index if not exists idx_tenants_status on tenants (status);

create table if not exists users (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id),
  username varchar(128) not null unique,
  email varchar(255),
  role varchar(32) not null,
  status varchar(32) not null,
  expires_at timestamptz,
  force_password_reset boolean not null default false,
  last_login_at timestamptz,
  version bigint not null default 1,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (role in ('super_admin', 'tenant_admin', 'operator', 'warehouse')),
  check (status in ('pending', 'active', 'locked', 'expired', 'disabled'))
);

create index if not exists idx_users_tenant_status on users (tenant_id, status);
create index if not exists idx_users_tenant_role on users (tenant_id, role);

create table if not exists user_passwords (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null unique references users(id),
  password_hash varchar(255) not null,
  password_version integer not null default 1,
  updated_at timestamptz not null default now()
);

create table if not exists auth_sessions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id),
  session_token varchar(255) not null unique,
  status varchar(32) not null,
  ip inet,
  user_agent text,
  expires_at timestamptz not null,
  revoked_at timestamptz,
  created_at timestamptz not null default now(),
  check (status in ('active', 'revoked', 'forced_logout'))
);

create index if not exists idx_auth_sessions_user_status on auth_sessions (user_id, status);
create index if not exists idx_auth_sessions_expires_at on auth_sessions (expires_at);

create table if not exists user_feature_flags (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id),
  feature_key varchar(64) not null,
  enabled boolean not null,
  source varchar(32) not null default 'manual',
  updated_by uuid references users(id),
  version bigint not null default 1,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id, feature_key)
);

create index if not exists idx_user_feature_flags_key_enabled
  on user_feature_flags (feature_key, enabled);

create table if not exists system_settings (
  id uuid primary key default gen_random_uuid(),
  setting_key varchar(128) not null unique,
  value_type varchar(32) not null,
  value_json jsonb not null,
  description text,
  updated_by uuid references users(id),
  change_reason text,
  version bigint not null default 1,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (value_type in ('boolean', 'string', 'number', 'json'))
);

create index if not exists idx_system_settings_key on system_settings (setting_key);

create table if not exists audit_logs (
  id uuid primary key default gen_random_uuid(),
  request_id varchar(128) not null,
  tenant_id uuid references tenants(id),
  store_id uuid,
  actor_type varchar(32) not null,
  actor_user_id uuid references users(id),
  actor_role varchar(32),
  actor_display_name varchar(128),
  impersonator_user_id uuid references users(id),
  session_id uuid references auth_sessions(id),
  source varchar(32) not null,
  ip inet,
  user_agent text,
  action varchar(128) not null,
  action_label varchar(128) not null,
  risk_level varchar(32) not null,
  target_type varchar(64) not null,
  target_id varchar(128),
  target_label varchar(128),
  before jsonb,
  after jsonb,
  diff jsonb,
  reason text,
  result varchar(32) not null,
  error_code varchar(64),
  idempotency_key varchar(128),
  task_id uuid,
  approval_id uuid,
  metadata jsonb,
  created_at timestamptz not null default now(),
  check (actor_type in ('user', 'system_worker', 'scheduler', 'support')),
  check (source in ('web', 'api', 'worker', 'extension', 'scheduler')),
  check (risk_level in ('low', 'medium', 'high', 'critical')),
  check (result in ('success', 'failed', 'partial', 'blocked'))
);

create index if not exists idx_audit_logs_tenant_created
  on audit_logs (tenant_id, created_at desc);
create index if not exists idx_audit_logs_action_created
  on audit_logs (action, created_at desc);
create index if not exists idx_audit_logs_target
  on audit_logs (target_type, target_id);

create table if not exists task_definitions (
  id uuid primary key default gen_random_uuid(),
  task_type varchar(128) not null unique,
  domain varchar(64) not null,
  display_name varchar(128) not null,
  queue_name varchar(64) not null,
  priority varchar(32) not null default 'medium',
  max_retries integer not null default 3,
  lease_timeout_seconds integer not null default 900,
  is_cancellable boolean not null default true,
  is_high_risk boolean not null default false,
  idempotency_scope varchar(128),
  retention_days integer not null default 30,
  enabled boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists stores (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id),
  name varchar(128) not null,
  platform varchar(32) not null default 'takealot',
  status varchar(32) not null,
  api_key_status varchar(32),
  last_synced_at timestamptz,
  deleted_at timestamptz,
  version bigint not null default 1,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint chk_stores_platform_takealot check (platform = 'takealot'),
  unique (tenant_id, name)
);

create index if not exists idx_stores_tenant_status on stores (tenant_id, status);
create index if not exists idx_stores_platform_status on stores (platform, status);

create table if not exists store_credentials (
  id uuid primary key default gen_random_uuid(),
  store_id uuid not null unique references stores(id),
  api_key_encrypted text not null,
  masked_api_key varchar(64) not null,
  credential_status varchar(32) not null,
  last_validated_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_store_credentials_status
  on store_credentials (credential_status);

create table if not exists store_feature_policies (
  id uuid primary key default gen_random_uuid(),
  store_id uuid not null unique references stores(id),
  bidding_enabled boolean not null default false,
  listing_enabled boolean not null default false,
  sync_enabled boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists task_runs (
  id uuid primary key default gen_random_uuid(),
  task_type varchar(128) not null,
  domain varchar(64) not null,
  status varchar(32) not null,
  stage varchar(64) not null,
  progress_percent numeric(5,2),
  progress_current integer,
  progress_total integer,
  priority varchar(32) not null default 'medium',
  queue_name varchar(64) not null,
  tenant_id uuid references tenants(id),
  store_id uuid references stores(id),
  actor_user_id uuid references users(id),
  actor_role varchar(32),
  source_type varchar(32),
  target_type varchar(64),
  target_id varchar(128),
  request_id varchar(128) not null,
  idempotency_key varchar(128),
  parent_task_id uuid,
  root_task_id uuid,
  dependency_state varchar(64),
  attempt_count integer not null default 0,
  max_retries integer not null default 3,
  retryable boolean not null default true,
  next_retry_at timestamptz,
  lease_owner varchar(128),
  lease_token varchar(128),
  lease_expires_at timestamptz,
  started_at timestamptz,
  finished_at timestamptz,
  last_heartbeat_at timestamptz,
  cancel_requested_at timestamptz,
  cancel_reason text,
  error_code varchar(64),
  error_msg text,
  error_details jsonb,
  ui_meta jsonb,
  input_payload_ref text,
  output_payload_ref text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (status in (
    'created',
    'queued',
    'leased',
    'running',
    'waiting_dependency',
    'waiting_retry',
    'cancel_requested',
    'cancelled',
    'succeeded',
    'failed_retryable',
    'failed_final',
    'dead_letter',
    'manual_intervention',
    'timed_out',
    'quarantined'
  ))
);

create index if not exists idx_task_runs_status_created
  on task_runs (status, created_at desc);
create index if not exists idx_task_runs_tenant_created
  on task_runs (tenant_id, created_at desc);
create index if not exists idx_task_runs_task_type_status
  on task_runs (task_type, status);
create index if not exists idx_task_runs_request_id
  on task_runs (request_id);
create index if not exists idx_task_runs_target
  on task_runs (target_type, target_id);

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'fk_audit_logs_task_id'
  ) then
    alter table audit_logs
      add constraint fk_audit_logs_task_id
      foreign key (task_id) references task_runs(id);
  end if;
end $$;

create table if not exists task_events (
  id uuid primary key default gen_random_uuid(),
  task_id uuid not null references task_runs(id),
  event_type varchar(128) not null,
  from_status varchar(32),
  to_status varchar(32),
  stage varchar(64),
  message text,
  details jsonb,
  source varchar(32) not null,
  source_id varchar(128),
  created_at timestamptz not null default now()
);

create index if not exists idx_task_events_task_created
  on task_events (task_id, created_at desc);
create index if not exists idx_task_events_type_created
  on task_events (event_type, created_at desc);
