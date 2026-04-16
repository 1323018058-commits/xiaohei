# Product Image Sync Design

Date: 2026-04-14
Project: ProfitLens v3
Scope: Sync Takealot product images into ERP product records and display them in ERP product views

## Background

The ERP already has an `image_url` field on `bid_products`, and backend APIs already return that field to the frontend. However, the current store/product sync flow does not reliably populate product images, and the main ERP product views do not render thumbnails.

Current state:

- `bid_products.image_url` exists and is exposed by backend APIs.
- `sync_bid_products()` mainly reads `offer.get("image_url")`, which is not reliable enough across Takealot offer payload variants.
- `商品管理` (`ProductListView`) does not display product images.
- `自动出价` (`BidConsoleView`) does not display product images.

## Goals

- Persist a usable product main image into ERP during product sync.
- Improve image fill rate without redesigning the data model.
- Display thumbnails in both `商品管理` and `自动出价`.
- Keep API contracts stable where possible.
- Keep the solution small and low-risk.

## Non-Goals

- Downloading or caching images into local/object storage.
- Introducing multi-image galleries in ERP.
- Refactoring product sync into a new service layer.
- Reworking listing, dropship, or library image flows.

## Approaches Considered

### Approach A — Sync main image with fallback enrichment (Recommended)

During product sync, keep using the offer payload as the primary source, but normalize image extraction and add a fallback path when `image_url` is missing. Then render the existing `image_url` in ERP list views.

Pros:

- Minimal schema impact.
- Reuses existing `image_url` field and API response shape.
- High probability of improving image coverage.
- Small frontend change.

Cons:

- Sync may do extra remote requests for products missing images.
- Still depends on upstream remote image URLs.

### Approach B — UI-only rendering

Only add thumbnail rendering to ERP views without improving sync.

Pros:

- Fastest implementation.

Cons:

- Does not solve missing images in stored ERP records.
- Many products would still show blanks.

### Approach C — Mirror images into local/object storage

Fetch images, store them under ERP-controlled URLs, and render internal asset links.

Pros:

- Best long-term stability.

Cons:

- Requires storage lifecycle, cleanup, and additional infrastructure.
- Too large for this change.

## Chosen Design

Implement Approach A.

### Backend sync behavior

Update the product sync flow so that each synced offer resolves a main image using a prioritized extraction strategy:

1. Use the direct image field from the offer payload when present.
2. Check common alternative image keys found in seller/marketplace payloads.
3. If still missing and the offer has an `offer_id`, fetch richer offer details and derive a main image from that response.
4. Preserve an already-stored `image_url` if the current sync payload has no usable image and the fallback lookup also yields nothing.

This keeps sync idempotent and avoids accidentally blanking images that were previously populated.

### Frontend rendering behavior

Render a small thumbnail column in:

- `商品管理` (`ProductListView`)
- `自动出价` (`BidConsoleView`)

Rendering rules:

- Show image thumbnail when `image_url` exists.
- Show a compact placeholder when missing or failed.
- Keep row height reasonable and avoid large layout shifts.
- Do not add modal/gallery behavior in this change.

## Detailed Design

### 1. Image extraction in product sync

Target file:

- `backend/app/services/bid_service.py`

Add a small helper near sync logic to resolve a main image from offer/detail payloads. The helper should:

- Accept a payload dictionary.
- Look for common direct URL fields first.
- Check simple list-shaped image collections if present.
- Return the first non-empty string URL.

Then update `sync_bid_products()` to:

- Resolve image from the current offer payload.
- If empty, call a richer detail endpoint for that offer and try again.
- Only overwrite `existing.image_url` when a non-empty image URL is found.
- For new products, store the resolved image URL if found; otherwise leave it empty.

### 2. Fallback source selection

Target file:

- `backend/app/services/takealot_api.py`

If existing available methods are insufficient for reliable image extraction, add a small helper for richer offer detail retrieval using the Marketplace API or the most suitable existing seller endpoint already used by this codebase.

Requirements:

- Reuse existing retry behavior in `TakealotSellerAPI`.
- Keep the helper read-only.
- Return raw detail payload or a minimal parsed structure suitable for image extraction.

### 3. API response compatibility

Target files:

- `backend/app/api/products.py`
- `backend/app/api/bids.py`

No response shape changes are required if `image_url` is already returned. Confirm both list endpoints continue returning `image_url` for frontend use.

### 4. Product list thumbnail UI

Target file:

- `frontend/src/views/ProductListView.vue`

Add a left-side thumbnail column or thumbnail+title presentation with these rules:

- Use a small square image.
- Keep object-fit cover.
- Show fallback placeholder if `image_url` is empty.
- Preserve current detail dialog behavior.

### 5. Bid console thumbnail UI

Target file:

- `frontend/src/views/BidConsoleView.vue`

Add a thumbnail column to help identify products in the repricing table:

- Small square image.
- Same fallback behavior as product list.
- Keep columns compact so pricing controls remain usable.

## Data Flow

1. User clicks product sync in ERP.
2. Backend fetches offers from Takealot.
3. For each offer, ERP resolves a main image URL from the offer payload.
4. If needed, ERP performs a detail fallback lookup to resolve the image.
5. ERP upserts `bid_products.image_url`.
6. Product list and bid console fetch normal product APIs.
7. Frontend renders thumbnails from `image_url`.

## Error Handling

- If remote image extraction fails, do not fail the entire sync for that product unless the broader offer sync already fails.
- If detail fallback fails, continue syncing other fields and leave image unchanged/blank.
- If frontend image load fails, show placeholder instead of broken layout.

## Testing and Verification

Backend:

- Add or update focused tests around image resolution helper behavior if a nearby backend test pattern exists.
- Validate that sync preserves existing image values when new payloads omit image data.
- Validate fallback extraction for alternate payload shapes if test coverage is practical in this repo.

Frontend:

- Build the frontend to verify the new thumbnail UI compiles.
- Check that both views render with and without `image_url`.

Command verification target:

- `cd /Users/Apple/Projects/profitlens-v3/frontend && npm run build`
- `cd /Users/Apple/Projects/profitlens-v3/frontend && npm run lint`
- `cd /Users/Apple/Projects/profitlens-v3 && python3 -m compileall -q backend/app`

## Risks

- Takealot payload image fields may vary by endpoint; fallback logic must be defensive.
- Extra detail lookups may slow sync for image-less products.
- Remote images may still expire or change upstream because URLs remain externally hosted.

## Implementation Notes

- Prefer a small extraction helper over spreading image parsing logic inline.
- Preserve existing sync semantics for pricing, stock, and product identifiers.
- Do not expand schema or storage unless a later project explicitly requires it.

## Acceptance Criteria

- After product sync, ERP stores `image_url` for substantially more products than before.
- `商品管理` shows product thumbnails.
- `自动出价` shows product thumbnails.
- Existing product APIs remain compatible.
- Frontend build passes and backend Python compilation passes.
