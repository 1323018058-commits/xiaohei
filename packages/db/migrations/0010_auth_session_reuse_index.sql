create index if not exists idx_auth_sessions_user_active_recent
on auth_sessions (user_id, status, created_at desc)
where status = 'active';
