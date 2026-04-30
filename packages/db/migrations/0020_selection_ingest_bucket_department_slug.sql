alter table selection_ingest_buckets
  add column if not exists department_slug text;
