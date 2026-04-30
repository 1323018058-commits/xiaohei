create table if not exists auth_phone_verification_codes (
  id uuid primary key default gen_random_uuid(),
  phone varchar(32) not null,
  purpose varchar(32) not null default 'register',
  code_hash varchar(128) not null,
  status varchar(32) not null default 'active',
  expires_at timestamptz not null,
  consumed_at timestamptz,
  attempt_count integer not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (status in ('active', 'consumed', 'expired')),
  check (attempt_count >= 0)
);

create index if not exists idx_auth_phone_codes_lookup
  on auth_phone_verification_codes (phone, purpose, status, created_at desc);

create index if not exists idx_auth_phone_codes_expires
  on auth_phone_verification_codes (expires_at);
