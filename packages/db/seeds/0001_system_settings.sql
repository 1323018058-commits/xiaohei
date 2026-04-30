insert into system_settings (
  setting_key,
  value_type,
  value_json,
  description,
  change_reason
) values
  ('auth_enabled', 'boolean', 'true'::jsonb, 'Auth release switch', 'initial release switch seed'),
  ('admin_enabled', 'boolean', 'true'::jsonb, 'Admin release switch', 'initial release switch seed'),
  ('store_sync_enabled', 'boolean', 'true'::jsonb, 'Store sync release switch', 'initial release switch seed'),
  ('fulfillment_write_enabled', 'boolean', 'true'::jsonb, 'Fulfillment write release switch', 'initial release switch seed'),
  ('autobid_read_enabled', 'boolean', 'true'::jsonb, 'Autobid read capability', 'initial release switch seed'),
  ('autobid_write_enabled', 'boolean', 'false'::jsonb, 'Autobid write capability', 'initial release switch seed'),
  ('listing_jobs_enabled', 'boolean', 'false'::jsonb, 'Listing jobs capability', 'initial release switch seed'),
  ('finance_recalc_enabled', 'string', to_jsonb('restricted'::text), 'Finance recalculation capability', 'initial release switch seed'),
  ('extension_pricing_formula_version', 'string', to_jsonb('takealot_air_margin_v1'::text), 'Extension pricing formula version', 'initial extension pricing seed'),
  ('extension_pricing_cny_to_zar_rate', 'number', to_jsonb(2.49::numeric), 'CNY to ZAR conversion rate used by extension pricing', 'initial extension pricing seed'),
  ('extension_pricing_payout_rate', 'number', to_jsonb(0.8275::numeric), 'Payout rate after platform deductions', 'initial extension pricing seed'),
  ('extension_pricing_withdraw_fx_rate', 'number', to_jsonb(0.04965::numeric), 'Withdraw plus FX loss rate', 'initial extension pricing seed'),
  ('extension_pricing_purchase_vat_rate', 'number', to_jsonb(0.747::numeric), 'Purchase VAT/tax converted cost rate', 'initial extension pricing seed'),
  ('extension_pricing_tail_shipping_fee_zar', 'number', to_jsonb(55::numeric), 'Last-mile shipping fee in ZAR', 'initial extension pricing seed'),
  ('extension_pricing_tail_vat_fee_zar', 'number', to_jsonb(8.25::numeric), 'Last-mile VAT fee in ZAR', 'initial extension pricing seed'),
  ('extension_pricing_default_air_freight_cny_per_kg', 'number', to_jsonb(79::numeric), 'Default air freight unit price in CNY/kg', 'initial extension pricing seed'),
  ('maintenance_mode', 'boolean', 'false'::jsonb, 'Maintenance mode', 'initial release switch seed')
on conflict (setting_key) do update set
  value_type = excluded.value_type,
  value_json = excluded.value_json,
  description = excluded.description,
  change_reason = excluded.change_reason,
  version = system_settings.version + 1,
  updated_at = now();
