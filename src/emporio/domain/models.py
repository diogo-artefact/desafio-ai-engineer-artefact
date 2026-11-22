from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

ProductStatus = Literal["active", "discontinued", "coming_soon"]
RetrievalMode = Literal["vector", "keyword"]
KnowledgeSourceKey = Literal["store_csvs", "policy_pdf"]
GuardrailAction = Literal["allow", "block_adversarial", "block_accessories", "block_off_topic"]
OrderDraftStatus = Literal["pending", "confirmed", "cancelled", "delivered"]


class PromotionInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    promotion_id: int
    discount_percent: float
    description: str
    is_active: bool


class ProductSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    product_id: int
    name: str
    category_id: int
    category_name: str
    price_brl: float
    stock_quantity: int
    status: ProductStatus
    is_sellable: bool
    active_promotion: PromotionInfo | None = None


class ProductDetail(ProductSummary):
    description: str
    specs: dict[str, str]
    expired_promotions: list[PromotionInfo]


class InstallmentOption(BaseModel):
    model_config = ConfigDict(frozen=True)

    installments: int
    installment_value_brl: float
    total_brl: float


class PaymentSimulation(BaseModel):
    model_config = ConfigDict(frozen=True)

    list_price_brl: float
    active_discount_percent: float
    effective_price_brl: float
    pix_price_brl: float
    pix_discount_applied: bool
    pix_note: str
    max_installments: int
    installment_options: list[InstallmentOption]
    allows_combined_payment: bool


class ShippingQuote(BaseModel):
    model_config = ConfigDict(frozen=True)

    city: str
    is_campo_grande_metro: bool
    free_shipping: bool
    fixed_cost_brl: float | None
    delivery_window: str
    carrier: str
    notes: str


class OrderItemInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    product_id: int
    product_name: str
    quantity: int


class OrderInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    order_id: int
    customer_name: str
    customer_city: str
    order_date: str
    status: str
    total_brl: float
    payment_method: str
    tracking_code: str
    estimated_delivery: str
    notes: str
    items: list[OrderItemInfo]


class ReturnEligibility(BaseModel):
    model_config = ConfigDict(frozen=True)

    order_id: int
    eligible: bool
    reason: str
    deadline_date: str | None
    days_remaining: int | None
    refund_deadline: str


class StoreHoursStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    is_open: bool
    current_time_local: str
    weekday_pt: str
    schedule_summary: str
    next_opening: str | None


class PolicyChunkHit(BaseModel):
    model_config = ConfigDict(frozen=True)

    chunk_id: str
    section_number: str
    parent_title: str
    title: str
    content: str
    page_start: int
    page_end: int
    score: float
    retrieval_mode: RetrievalMode


class KnowledgeSourceStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_key: KnowledgeSourceKey
    loaded: bool
    file_names: list[str]
    record_count: int
    audit_count: int
    uploaded_at: str | None


class KnowledgeStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    csvs: KnowledgeSourceStatus
    pdf: KnowledgeSourceStatus
    ready: bool


class GuardrailDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    action: GuardrailAction
    intent: str
    intent_probability: float
    prompt_injection_probability: float
    latency_ms: int
    reply: str | None = None
    model: str = ""
    summary: str = ""


class SessionCompaction(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str
    summary: str
    compacted_up_to_message_id: int
    updated_at: str


class UserMemory(BaseModel):
    model_config = ConfigDict(frozen=True)

    fact_key: str
    content: str
    updated_at: str


class UserPersonalization(BaseModel):
    model_config = ConfigDict(frozen=True)

    custom_instructions: str
    updated_at: str | None = None


class InstructionValidationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    allowed: bool
    reason: str | None = None
    override_probability: float = 0.0
    model: str = ""
    latency_ms: int = 0


class OrderPricing(BaseModel):
    model_config = ConfigDict(frozen=True)

    unit_price_brl: float
    discount_percent: float
    subtotal_brl: float
    shipping_brl: float
    shipping_note: str
    total_brl: float
    payment_method: str
    payment_label: str
    city: str


class OrderDraft(BaseModel):
    model_config = ConfigDict(frozen=True)

    draft_id: str
    session_id: str
    user_id: str
    product_id: int
    product_name: str
    quantity: int
    unit_price_brl: float
    discount_percent: float
    subtotal_brl: float
    shipping_brl: float
    shipping_note: str
    total_brl: float
    payment_method: str
    payment_label: str
    city: str
    status: OrderDraftStatus
    order_id: int | None = None
    tracking_code: str = ""
    created_at: str
    confirmed_at: str | None = None
    deliver_at: str | None = None
    delivered_at: str | None = None
