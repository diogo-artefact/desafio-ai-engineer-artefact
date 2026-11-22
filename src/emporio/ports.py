from __future__ import annotations

from typing import Any, Protocol

from emporio.auth import AuthenticatedUser, UserRole
from emporio.domain.models import (
    GuardrailDecision,
    KnowledgeStatus,
    OrderInfo,
    PolicyChunkHit,
    ProductDetail,
    ProductSummary,
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
