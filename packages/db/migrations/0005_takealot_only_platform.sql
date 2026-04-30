update stores
set platform = 'takealot',
    updated_at = now()
where platform <> 'takealot';

alter table stores
  drop constraint if exists chk_stores_platform_takealot;

alter table stores
  add constraint chk_stores_platform_takealot check (platform = 'takealot');
