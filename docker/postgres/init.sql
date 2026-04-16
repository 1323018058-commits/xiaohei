-- ProfitLens v3 — PostgreSQL initialization
-- This script runs once when the PostgreSQL container is first created.

-- Enable useful extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";     -- Trigram index for fuzzy text search

-- Performance tuning for 2000-user workload
ALTER SYSTEM SET max_connections = 500;
ALTER SYSTEM SET shared_buffers = '2GB';
ALTER SYSTEM SET effective_cache_size = '6GB';
ALTER SYSTEM SET work_mem = '16MB';
ALTER SYSTEM SET maintenance_work_mem = '256MB';
ALTER SYSTEM SET random_page_cost = 1.1;
ALTER SYSTEM SET effective_io_concurrency = 200;
ALTER SYSTEM SET wal_buffers = '64MB';
ALTER SYSTEM SET checkpoint_completion_target = 0.9;
ALTER SYSTEM SET log_min_duration_statement = 500;  -- Log slow queries > 500ms

SELECT pg_reload_conf();
