create index if not exists idx_auth_sessions_user_id on auth_sessions (user_id);
create index if not exists idx_users_username_status on users (username, status);
