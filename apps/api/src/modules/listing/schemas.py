from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ListingJobResponse(BaseModel):
    job_id: str
    tenant_id: str
    store_id: str
    product_id: str | None
    guardrail_id: str | None
    entry_task_id: str | None
    processing_task_id: str | None
    platform: str
    source: str
    source_ref: str | None
    title: str
    status: str
    stage: str
    note: str | None
    raw_payload: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class ListingJobListResponse(BaseModel):
    jobs: list[ListingJobResponse]


class TakealotCategoryItem(BaseModel):
    id: str
    category_id: int
    division: str
    department: str
    main_category_id: int
    main_category_name: str
    lowest_category_name: str
    lowest_category_raw: str
    path_en: str
    path_zh: str
    min_required_images: int
    compliance_certificates: list[str] = Field(default_factory=list)
    image_requirement_texts: list[str] = Field(default_factory=list)
    required_attributes: list[str | dict[str, Any]] = Field(default_factory=list)
    optional_attributes: list[str | dict[str, Any]] = Field(default_factory=list)
    loadsheet_template_id: str | None = None
    loadsheet_template_name: str = ""
    attributes_ready: bool = False
    attribute_source: str = "missing"
    attribute_message: str | None = None
    translation_source: str = "rules"
    match_score: float | None = None
    source: str = "catalog"


class TakealotCategorySearchResponse(BaseModel):
    items: list[TakealotCategoryItem]
    total: int
    page: int
    page_size: int
    catalog_ready: bool
    message: str | None = None


class TakealotCategoryRequirementsResponse(TakealotCategoryItem):
    catalog_ready: bool = True
    message: str | None = None
    matching_variants: int = 1
    raw_payload: dict[str, Any] | None = None


class TakealotBrandItem(BaseModel):
    id: str
    brand_id: str
    brand_name: str
    match_score: float | None = None
    source: str = "catalog"


class TakealotBrandSearchResponse(BaseModel):
    items: list[TakealotBrandItem]
    total: int
    page: int
    page_size: int
    catalog_ready: bool
    message: str | None = None


class CategoryMatchRequest(BaseModel):
    description: str = Field(..., min_length=1, max_length=1000)
    language_hint: str | None = Field(default=None, max_length=32)
    limit: int = Field(default=5, ge=1, le=5)
    use_ai: bool = True


class CategoryMatchSuggestion(BaseModel):
    category_id: int
    path_en: str
    path_zh: str
    confidence: float
    min_required_images: int
    compliance_certificates: list[str] = Field(default_factory=list)
    image_requirement_texts: list[str] = Field(default_factory=list)
    required_attributes: list[str | dict[str, Any]] = Field(default_factory=list)
    optional_attributes: list[str | dict[str, Any]] = Field(default_factory=list)
    loadsheet_template_id: str | None = None
    loadsheet_template_name: str = ""
    division: str = ""
    department: str = ""
    main_category_id: int = 0
    main_category_name: str = ""
    lowest_category_name: str = ""
    lowest_category_raw: str = ""
    attributes_ready: bool = False
    attribute_source: str = "missing"
    attribute_message: str | None = None
    translation_source: str = "rules"
    matched_keywords: list[str] = Field(default_factory=list)
    match_reasons: list[str] = Field(default_factory=list)
    source: str = "rules"


class CategoryMatchResponse(BaseModel):
    suggestions: list[CategoryMatchSuggestion]
    total_candidates: int
    catalog_ready: bool
    ai_used: bool
    vector_used: bool = False
    vector_candidates: int = 0
    keyword_candidates: int = 0
    fuzzy_candidates: int = 0
    embedding_model: str | None = None
    embedding_dimensions: int | None = None
    translation_used: bool = False
    translation_model: str | None = None
    match_strategy: str = "keyword_rules"
    normalized_keywords: list[str] = Field(default_factory=list)
    message: str | None = None


class DynamicAttributeDraft(BaseModel):
    key: str
    value: Any | None = None
    value_type: str | None = None
    source: str = "fallback"
    warning: str | None = None


class ListingGeneratedContent(BaseModel):
    category_id: int
    category_path_en: str
    category_path_zh: str
    title: str
    subtitle: str
    description: str
    whats_in_the_box: str
    length_cm: float
    width_cm: float
    height_cm: float
    weight_g: int
    dynamic_attributes: list[DynamicAttributeDraft] = Field(default_factory=list)


class ListingAiAutopilotRequest(BaseModel):
    product_description: str = Field(..., min_length=1, max_length=2000)
    category_id: int = Field(..., ge=1)
    brand_name: str = Field(default="", max_length=255)
    required_attributes: list[str | dict[str, Any]] = Field(default_factory=list)
    optional_attributes: list[str | dict[str, Any]] = Field(default_factory=list)
    language_hint: str | None = Field(default=None, max_length=32)
    use_ai: bool = True


class ListingAiAutopilotResponse(ListingGeneratedContent):
    ai_used: bool
    fallback_used: bool
    warnings: list[str] = Field(default_factory=list)


class ListingImageAsset(BaseModel):
    id: str | None = None
    tenant_id: str | None = None
    store_id: str | None = None
    submission_id: str | None = None
    asset_type: str = "image"
    source: str
    original_file_name: str | None = None
    file_name: str | None = None
    storage_path: str | None = None
    public_url: str | None = None
    external_url: str | None = None
    content_type: str | None = None
    size_bytes: int | None = None
    checksum_sha256: str | None = None
    width: int | None = None
    height: int | None = None
    sort_order: int = 0
    validation_status: str = "pending"
    validation_errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ListingImageUploadResponse(BaseModel):
    items: list[ListingImageAsset]
    warnings: list[str] = Field(default_factory=list)


class ListingImageUrlValidateRequest(BaseModel):
    image_url: str = Field(..., min_length=1, max_length=2048)
    check_remote: bool = True


class ListingImageUrlValidateResponse(BaseModel):
    image_url: str
    valid: bool
    content_type: str | None = None
    size_bytes: int | None = None
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class ListingImageRequirementCheckRequest(BaseModel):
    category_id: int = Field(..., ge=1)
    image_urls: list[str] = Field(default_factory=list)
    asset_ids: list[str] = Field(default_factory=list)


class ListingImageRequirementCheckResponse(BaseModel):
    passed: bool
    required_count: int
    current_count: int
    missing_count: int
    warnings: list[str] = Field(default_factory=list)
    valid_image_urls: list[str] = Field(default_factory=list)
    valid_asset_ids: list[str] = Field(default_factory=list)


class ListingLoadsheetValidationIssue(BaseModel):
    level: str = Field(..., pattern="^(error|warning)$")
    field: str
    message: str


class ListingLoadsheetAsset(BaseModel):
    asset_id: str | None = None
    storage_path: str | None = None
    public_url: str | None = None
    content_type: str
    size_bytes: int
    checksum_sha256: str


class ListingLoadsheetPreviewRequest(BaseModel):
    store_id: str = Field(..., min_length=1)
    category_id: int = Field(..., ge=1)
    brand_id: str | None = Field(default=None, max_length=128)
    brand_name: str = Field(default="", max_length=255)
    sku: str = Field(default="", max_length=128)
    barcode: str = Field(default="", max_length=128)
    title: str = Field(default="", max_length=255)
    subtitle: str = Field(default="", max_length=255)
    description: str = Field(default="", max_length=5000)
    whats_in_the_box: str = Field(default="", max_length=2000)
    selling_price: float | None = None
    rrp: float | None = None
    stock_quantity: int | None = None
    minimum_leadtime_days: int | None = None
    seller_warehouse_id: str = Field(default="", max_length=128)
    length_cm: float | None = None
    width_cm: float | None = None
    height_cm: float | None = None
    weight_g: float | None = None
    image_urls: list[str] = Field(default_factory=list)
    asset_ids: list[str] = Field(default_factory=list)
    dynamic_attributes: dict[str, Any] | list[DynamicAttributeDraft] = Field(default_factory=dict)


class ListingLoadsheetPreviewResponse(BaseModel):
    valid: bool
    issues: list[ListingLoadsheetValidationIssue] = Field(default_factory=list)
    loadsheet_asset: ListingLoadsheetAsset | None = None
    generated_fields: dict[str, Any] = Field(default_factory=dict)
    missing_required_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ListingSubmissionCreateRequest(BaseModel):
    category_id: int = Field(..., ge=1)
    brand_id: str | None = Field(default=None, max_length=128)
    brand_name: str = Field(default="", max_length=255)
    sku: str = Field(default="", max_length=128)
    barcode: str = Field(default="", max_length=128)
    title: str = Field(default="", max_length=255)
    subtitle: str = Field(default="", max_length=255)
    description: str = Field(default="", max_length=5000)
    whats_in_the_box: str = Field(default="", max_length=2000)
    selling_price: float | None = None
    rrp: float | None = None
    stock_quantity: int | None = None
    minimum_leadtime_days: int | None = None
    seller_warehouse_id: str = Field(default="", max_length=128)
    length_cm: float | None = None
    width_cm: float | None = None
    height_cm: float | None = None
    weight_g: float | None = None
    image_urls: list[str] = Field(default_factory=list)
    asset_ids: list[str] = Field(default_factory=list)
    dynamic_attributes: dict[str, Any] | list[DynamicAttributeDraft] = Field(default_factory=dict)
    submit_immediately: bool = False


class ListingSubmissionItem(BaseModel):
    submission_id: str
    tenant_id: str
    store_id: str
    listing_id: str | None = None
    task_id: str | None = None
    status: str
    stage: str
    review_status: str
    sku: str
    barcode: str
    title: str
    category_id: int
    category_path: str
    brand_id: str = ""
    brand_name: str = ""
    selling_price: float | None = None
    rrp: float | None = None
    stock_quantity: int
    minimum_leadtime_days: int
    takealot_submission_id: str = ""
    takealot_offer_id: str = ""
    platform_product_id: str | None = None
    official_status: str = ""
    error_code: str | None = None
    error_message: str | None = None
    offer_error_message: str | None = None
    loadsheet_asset: ListingLoadsheetAsset | None = None
    validation_issues: list[ListingLoadsheetValidationIssue] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    submitted_at: datetime | None = None
    last_checked_at: datetime | None = None
    last_status_sync_at: datetime | None = None
    finalized_at: datetime | None = None


class ListingSubmissionCreateResponse(BaseModel):
    submission_id: str | None = None
    task_id: str | None = None
    status: str
    stage: str
    message: str
    reused_existing: bool = False
    submit_immediately: bool = False
    submit_succeeded: bool | None = None
    takealot_submission_id: str = ""
    official_status: str = ""
    error_code: str | None = None
    error_message: str | None = None
    loadsheet_asset: ListingLoadsheetAsset | None = None
    validation_issues: list[ListingLoadsheetValidationIssue] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ListingSubmissionListResponse(BaseModel):
    items: list[ListingSubmissionItem]
    total: int
    page: int
    page_size: int


class ListingSubmissionDetailResponse(ListingSubmissionItem):
    content_payload: dict[str, Any] | None = None
    loadsheet_payload: dict[str, Any] | None = None
    official_response: dict[str, Any] | None = None


class ListingSubmissionStatusItem(BaseModel):
    submission_id: str
    store_id: str
    task_id: str | None = None
    status: str
    stage: str
    review_status: str
    official_status: str = ""
    takealot_submission_id: str = ""
    takealot_offer_id: str = ""
    listing_id: str | None = None
    platform_product_id: str | None = None
    last_checked_at: datetime | None = None
    last_status_sync_at: datetime | None = None
    finalized_at: datetime | None = None
    message: str | None = None
    warnings: list[str] = Field(default_factory=list)


class ListingSubmissionSyncResponse(BaseModel):
    store_id: str | None = None
    submission_id: str | None = None
    task_id: str | None = None
    queued_count: int = 0
    status: str
    message: str
    items: list[ListingSubmissionStatusItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ListingFinalizeOfferResponse(BaseModel):
    submission_id: str
    task_id: str | None = None
    status: str
    stage: str
    review_status: str
    takealot_offer_id: str = ""
    listing_id: str | None = None
    platform_product_id: str | None = None
    message: str
    warnings: list[str] = Field(default_factory=list)
