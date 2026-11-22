from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol

from emporio.auth import AuthenticatedUser, UserRole
from emporio.domain.models import (
    GuardrailDecision,
    InstructionValidationResult,
    KnowledgeStatus,
    OrderDraft,
    OrderInfo,
    PolicyChunkHit,
    ProductDetail,
    ProductSummary,
    SessionCompaction,
    UserMemory,
    UserPersonalization,
)


class CatalogRepository(Protocol):
    def list_categories(self) -> list[dict[str, Any]]: ...

    def search_products(
        self,
        query: str | None = None,
        category: str | None = None,
        max_price: float | None = None,
        min_price: float | None = None,
        only_available: bool = True,
        only_promotions: bool = False,
        limit: int = 10,
    ) -> list[ProductSummary]: ...

    def get_product_detail(self, product_id_or_name: int | str) -> ProductDetail | None: ...

    def find_alternatives(self, product_id: int, limit: int = 3) -> list[ProductSummary]: ...


class OrderRepository(Protocol):
    def verify_and_get_order(self, order_id: int, contact: str) -> OrderInfo | None: ...

    def count_customers_by_email(self, email: str) -> int: ...

    def list_orders_for_email(self, email: str) -> list[OrderInfo]: ...

    def match_customer_email_and_phone(self, email: str, phone: str) -> bool: ...

    def list_orders_for_email_and_phone(self, email: str, phone: str) -> list[OrderInfo]: ...

    def get_customer_city_by_email(self, email: str) -> str | None: ...


class OrderDraftRepository(Protocol):
    def create_order_draft(
        self,
        *,
        session_id: str,
        user_id: str,
        product_id: int,
        product_name: str,
        quantity: int,
        unit_price_brl: float,
        discount_percent: float,
        subtotal_brl: float,
        shipping_brl: float,
        shipping_note: str,
        total_brl: float,
        payment_method: str,
        payment_label: str,
        city: str,
    ) -> OrderDraft: ...

    def list_session_order_drafts(self, session_id: str) -> list[OrderDraft]: ...

    def get_order_draft(
        self, draft_id: str, user_id: str | None = None
    ) -> OrderDraft | None: ...

    def confirm_order_draft(
        self,
        draft_id: str,
        user: AuthenticatedUser,
        auto_delivery_seconds: int = 300,
    ) -> tuple[OrderDraft, dict[str, Any]]: ...

    def cancel_order_draft(self, draft_id: str, user_id: str) -> OrderDraft: ...

    def finalize_due_deliveries(self, now: datetime | None = None) -> list[OrderDraft]: ...


class PolicyRetriever(Protocol):
    def search_policies(self, query: str, limit: int = 4) -> list[PolicyChunkHit]: ...

    def get_policy_section(self, section_number: str) -> list[PolicyChunkHit]: ...


class KnowledgeRepository(Protocol):
    def get_knowledge_status(self) -> KnowledgeStatus: ...


class SettingsRepository(Protocol):
    def get_setting(self, key: str) -> str | None: ...

    def set_setting(self, key: str, value: str) -> None: ...


class InputGuardrail(Protocol):
    async def check(
        self,
        message: str,
        history: list[dict[str, Any]],
    ) -> GuardrailDecision: ...

    async def validate_instructions(
        self,
        instructions: str,
    ) -> InstructionValidationResult: ...


class TitleGenerator(Protocol):
    async def generate(self, message: str) -> str | None: ...


class CompactionRepository(Protocol):
    def get_session_compaction(self, session_id: str) -> SessionCompaction | None: ...

    def save_session_compaction(
        self,
        session_id: str,
        summary: str,
        compacted_up_to_message_id: int,
    ) -> None: ...


class MemoryRepository(Protocol):
    def list_user_memories(self, user_id: str, limit: int = 12) -> list[UserMemory]: ...

    def upsert_user_memories(
        self, user_id: str, memories: list[tuple[str, str]]
    ) -> None: ...

    def delete_user_memory(self, user_id: str, fact_key: str) -> bool: ...

    def clear_user_memories(self, user_id: str) -> int: ...


class PersonalizationRepository(Protocol):
    def get_custom_instructions(self, user_id: str) -> UserPersonalization: ...

    def save_custom_instructions(
        self, user_id: str, instructions: str
    ) -> UserPersonalization: ...


class ConversationCompactor(Protocol):
    async def compact(
        self,
        previous_summary: str | None,
        messages: list[dict[str, Any]],
    ) -> str | None: ...


class UserMemoryExtractor(Protocol):
    async def extract(
        self,
        user_message: str,
        assistant_response: str,
        existing: list[UserMemory],
    ) -> list[tuple[str, str]]: ...


class UserRepository(Protocol):
    def get_user_by_id(self, user_id: str) -> AuthenticatedUser | None: ...

    def get_user_with_hash_by_email(
        self, email: str
    ) -> tuple[AuthenticatedUser, str] | None: ...

    def create_user(
        self,
        name: str,
        email: str,
        password_hash: str,
        role: UserRole = "customer",
    ) -> AuthenticatedUser: ...

    def ensure_seed_user(
        self,
        name: str,
        email: str,
        password_hash: str,
        role: UserRole,
    ) -> None: ...

    def sync_customer_seed_users(
        self,
        password_factory: Callable[[], str],
    ) -> int: ...


class SessionRepository(Protocol):
    def list_sessions(self, user_id: str | None = None) -> list[dict[str, Any]]: ...

    def get_session(
        self, session_id: str, user_id: str | None = None
    ) -> dict[str, Any] | None: ...

    def create_session(
        self, session_id: str, title: str, user_id: str | None = None
    ) -> None: ...

    def update_session_title(self, session_id: str, title: str) -> None: ...

    def get_messages(self, session_id: str) -> list[dict[str, Any]]: ...

    def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        trace: list[dict[str, Any]] | None = None,
    ) -> None: ...

    def delete_session(self, session_id: str, user_id: str | None = None) -> bool: ...
