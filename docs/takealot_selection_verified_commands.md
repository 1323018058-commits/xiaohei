# Takealot selection verified commands

Verified on 2026-04-27.

## Category discovery

Cross-department smoke sample:

```powershell
python packages/db/scripts/takealot_selection_discover_categories.py `
  --limit 50 `
  --limit-per-department 5 `
  --max-requests 260 `
  --max-requests-per-department 50 `
  --max-seconds-per-department 12 `
  --output .tmp_selection_categories_cross_dept_50_timed.csv `
  --concurrency 2 `
  --request-delay-ms 250 `
  --timeout 8 `
  --max-retries 1 `
  --retry-base-delay-ms 1500 `
  --retry-max-delay-ms 6000
```

Observed result: 50 leaf categories, 182 fetches, 0 retries, 0 rate limits, about 110 seconds.

## Crawl URL template

The public Takealot endpoint accepted this list URL template:

```text
https://api.takealot.com/rest/v-1-16-0/searches/products,filters,facets,sort_options,breadcrumbs,slots_audience,context,seo,layout?customer_id=-1452878711&client_id=413cba4d-fb82-474e-b89b-0dd65cb38d81&department_slug={department_slug}&category_slug={category_slug}&filter=Price:{price_filter}
```

`filter=Price:{price_filter}` was verified; `price_min` and `price_max` did not filter results on this endpoint.

## URL preview

```powershell
python packages/db/scripts/takealot_selection_crawl.py `
  --url-template "https://api.takealot.com/rest/v-1-16-0/searches/products,filters,facets,sort_options,breadcrumbs,slots_audience,context,seo,layout?customer_id=-1452878711&client_id=413cba4d-fb82-474e-b89b-0dd65cb38d81&department_slug={department_slug}&category_slug={category_slug}&filter=Price:{price_filter}" `
  --categories-file .tmp_selection_categories_cross_dept_50_timed.csv `
  --price-ranges 500:750 `
  --max-buckets 2 `
  --page-size 12 `
  --preview-urls 3
```

## Dry-run crawl

```powershell
python packages/db/scripts/takealot_selection_crawl.py `
  --url-template "https://api.takealot.com/rest/v-1-16-0/searches/products,filters,facets,sort_options,breadcrumbs,slots_audience,context,seo,layout?customer_id=-1452878711&client_id=413cba4d-fb82-474e-b89b-0dd65cb38d81&department_slug={department_slug}&category_slug={category_slug}&filter=Price:{price_filter}" `
  --categories-file .tmp_selection_categories_cross_dept_50_timed.csv `
  --price-ranges 500:750 `
  --max-buckets 2 `
  --max-pages-per-bucket 1 `
  --page-size 12 `
  --max-products 24 `
  --concurrency 1 `
  --detail-concurrency 1 `
  --request-delay-ms 250 `
  --timeout 20 `
  --max-retries 1 `
  --raw-payload-mode none `
  --output-jsonl .tmp_selection_products_dryrun.jsonl `
  --dry-run
```

Observed result: 1 request, 24 parsed product records, 0 retries, 0 rate limits, 0 failures, about 2.2 seconds.

## Real write smoke

```powershell
python packages/db/scripts/takealot_selection_crawl.py `
  --url-template "https://api.takealot.com/rest/v-1-16-0/searches/products,filters,facets,sort_options,breadcrumbs,slots_audience,context,seo,layout?customer_id=-1452878711&client_id=413cba4d-fb82-474e-b89b-0dd65cb38d81&department_slug={department_slug}&category_slug={category_slug}&filter=Price:{price_filter}" `
  --categories-file .tmp_selection_categories_cross_dept_50_timed.csv `
  --price-ranges 500:750 `
  --max-buckets 2 `
  --max-pages-per-bucket 1 `
  --page-size 12 `
  --max-products 24 `
  --concurrency 1 `
  --detail-concurrency 1 `
  --request-delay-ms 250 `
  --timeout 20 `
  --max-retries 1 `
  --raw-payload-mode none `
  --output-jsonl .tmp_selection_products_write_smoke.jsonl
```

Observed run `f68a02e2-2659-437e-8c66-6d053c5cbc3c`: succeeded, 24 discovered, 24 processed, 0 failures, 0 rate limits.

## Real write pilot

```powershell
python packages/db/scripts/takealot_selection_crawl.py `
  --url-template "https://api.takealot.com/rest/v-1-16-0/searches/products,filters,facets,sort_options,breadcrumbs,slots_audience,context,seo,layout?customer_id=-1452878711&client_id=413cba4d-fb82-474e-b89b-0dd65cb38d81&department_slug={department_slug}&category_slug={category_slug}&filter=Price:{price_filter}" `
  --categories-file .tmp_selection_categories_cross_dept_50_timed.csv `
  --price-ranges 500:750 `
  --max-buckets 50 `
  --max-pages-per-bucket 1 `
  --page-size 12 `
  --max-products 500 `
  --concurrency 2 `
  --detail-concurrency 1 `
  --request-delay-ms 250 `
  --timeout 20 `
  --max-retries 1 `
  --raw-payload-mode none `
  --output-jsonl .tmp_selection_products_write_pilot.jsonl
```

Observed run `316a2924-bd7c-49b4-ad24-7f84d29800bf`: succeeded, 23 requests, 500 discovered, 500 processed, 0 failures, 0 rate limits, about 50 seconds. Direct DB check found 500 snapshots and 500 distinct products for the run.

## Real write expanded pilot

```powershell
python packages/db/scripts/takealot_selection_crawl.py `
  --url-template "https://api.takealot.com/rest/v-1-16-0/searches/products,filters,facets,sort_options,breadcrumbs,slots_audience,context,seo,layout?customer_id=-1452878711&client_id=413cba4d-fb82-474e-b89b-0dd65cb38d81&department_slug={department_slug}&category_slug={category_slug}&filter=Price:{price_filter}" `
  --categories-file .tmp_selection_categories_cross_dept_50_timed.csv `
  --max-buckets 650 `
  --max-pages-per-bucket 1 `
  --page-size 24 `
  --max-products 2000 `
  --concurrency 2 `
  --detail-concurrency 1 `
  --request-delay-ms 300 `
  --timeout 20 `
  --max-retries 1 `
  --raw-payload-mode none `
  --output-jsonl .tmp_selection_products_write_2k.jsonl
```

Observed run `64568a6a-9ce0-4d5f-9ad8-81ab2fb4b1e9`: succeeded, 115 requests, 2000 discovered, 2000 processed, 0 failures, 0 rate limits, about 253 seconds. Direct DB check found 2000 snapshots and 2000 distinct products. Main-category distribution: Books 770, Home & Kitchen 664, Fashion 548, Office & Stationery 18.

## Plan-only check

```powershell
python packages/db/scripts/takealot_selection_crawl.py `
  --url-template "https://api.takealot.com/rest/v-1-16-0/searches/products,filters,facets,sort_options,breadcrumbs,slots_audience,context,seo,layout?customer_id=-1452878711&client_id=413cba4d-fb82-474e-b89b-0dd65cb38d81&department_slug={department_slug}&category_slug={category_slug}&filter=Price:{price_filter}" `
  --categories-file .tmp_selection_categories_cross_dept_50_timed.csv `
  --max-buckets 1000 `
  --dry-run `
  --plan-only `
  --no-persist-plan
```

Observed result: 50 categories produce 650 initial buckets with the default Takealot price profile.
