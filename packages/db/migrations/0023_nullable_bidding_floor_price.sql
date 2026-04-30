do $$
declare
  constraint_name text;
begin
  for constraint_name in
    select conname
    from pg_constraint
    where conrelid = 'bidding_rules'::regclass
      and contype = 'c'
      and pg_get_constraintdef(oid) like '%floor_price >%'
  loop
    execute format('alter table bidding_rules drop constraint if exists %I', constraint_name);
  end loop;
end $$;

alter table bidding_rules
  alter column floor_price drop not null;

alter table bidding_rules
  add constraint chk_bidding_rules_floor_price_positive_or_null
  check (floor_price is null or floor_price > 0);
