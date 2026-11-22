from __future__ import annotations

import json
import logging
import re
import secrets
import string
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from google.genai import errors as genai_errors
from sqlalchemy import Integer, cast, delete, exists, func, select
from sqlalchemy.orm import Session

from emporio.auth import AuthenticatedUser, UserRole
from emporio.db.schema import (
    AppSettingRow,
    CategoryRow,
    CustomerRow,
    KnowledgeSourceRow,
    MessageRow,
    OrderDraftRow,
    OrderItemRow,
    OrderRow,
    PolicyChunkRow,
    ProductRow,
    PromotionRow,
    SessionRow,
    SessionSummaryRow,
    UserMemoryRow,
    UserPreferenceRow,
    UserRow,
    create_db_engine,
    init_schema,
)
from emporio.domain.models import (
    KnowledgeSourceStatus,
    KnowledgeStatus,
    OrderDraft,
    OrderInfo,
    OrderItemInfo,
    PolicyChunkHit,
    ProductDetail,
    ProductSummary,
    PromotionInfo,
    SessionCompaction,
    UserMemory,
    UserPersonalization,
)
from emporio.domain.rules import STORE_TZ
from emporio.domain.text import normalize_phone_digits, normalize_text
from emporio.etl.embeddings import Embedder, cosine_similarity

logger = logging.getLogger(__name__)


TRACKING_ALPHABET = string.ascii_uppercase + string.digits


def _utc_iso(dt: datetime | None = None) -> str:
    resolved = dt.astimezone(UTC) if dt is not None else datetime.now(UTC)
    return resolved.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _generate_tracking_code() -> str:
    middle = "".join(secrets.choice(TRACKING_ALPHABET) for _ in range(9))
    return f"BR{middle}BR"


def _format_brl(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _query_terms(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", normalize_text(text)) if len(t) >= 2]


class SQLiteStoreRepository:
    def __init__(self, db_path: Path | str, embedder: Embedder | None = None) -> None:
        self._engine = create_db_engine(db_path)
        self._embedder = embedder
        init_schema(self._engine)

    def _session(self) -> Session:
        return Session(self._engine)

    def _load_promotions_map(
        self,
        session: Session,
        product_ids: list[int],
    ) -> dict[int, list[PromotionInfo]]:
        if not product_ids:
            return {}
        stmt = (
            select(PromotionRow)
            .where(PromotionRow.product_id.in_(product_ids))
            .order_by(PromotionRow.is_active.desc(), PromotionRow.discount_percent.desc())
        )
        grouped: dict[int, list[PromotionInfo]] = {}
        for row in session.scalars(stmt):
            grouped.setdefault(row.product_id, []).append(
                PromotionInfo(
                    promotion_id=row.promotion_id,
                    discount_percent=row.discount_percent,
                    description=row.description,
                    is_active=row.is_active,
                )
            )
        return grouped

    def _to_summary(
        self,
        product: ProductRow,
        category_name: str,
        promos: list[PromotionInfo],
    ) -> ProductSummary:
        active = next((p for p in promos if p.is_active), None)
        return ProductSummary(
            product_id=product.product_id,
            name=product.name,
            category_id=product.category_id,
            category_name=category_name,
            price_brl=product.price_brl,
            stock_quantity=product.stock_quantity,
            status=product.status,
            is_sellable=product.is_sellable,
            active_promotion=active,
        )

    def list_categories(self) -> list[dict[str, Any]]:
        with self._session() as session:
            stmt = (
                select(
                    CategoryRow.category_id,
                    CategoryRow.name,
                    CategoryRow.description,
                    func.count(ProductRow.product_id).label("total_products"),
                    func.coalesce(
                        func.sum(cast(ProductRow.is_sellable, Integer)), 0
                    ).label("sellable_products"),
                )
                .outerjoin(ProductRow, ProductRow.category_id == CategoryRow.category_id)
                .group_by(CategoryRow.category_id, CategoryRow.name, CategoryRow.description)
                .order_by(CategoryRow.category_id)
            )
            return [dict(row._mapping) for row in session.execute(stmt)]

    def search_products(
        self,
        query: str | None = None,
        category: str | None = None,
        max_price: float | None = None,
        min_price: float | None = None,
        only_available: bool = True,
        only_promotions: bool = False,
        limit: int = 10,
    ) -> list[ProductSummary]:
        with self._session() as session:
            stmt = select(ProductRow, CategoryRow.name).join(
                CategoryRow, CategoryRow.category_id == ProductRow.category_id
            )

            if only_available:
                stmt = stmt.where(ProductRow.is_sellable.is_(True))
            if min_price is not None:
                stmt = stmt.where(ProductRow.price_brl >= min_price)
            if max_price is not None:
                stmt = stmt.where(ProductRow.price_brl <= max_price)
            if only_promotions:
                stmt = stmt.where(
                    exists(
                        select(PromotionRow.promotion_id).where(
                            PromotionRow.product_id == ProductRow.product_id,
                            PromotionRow.is_active.is_(True),
                        )
                    )
                )
            if category:
                norm_cat = normalize_text(category)
                matched_ids = [
                    c.category_id
                    for c in session.scalars(select(CategoryRow))
                    if norm_cat in normalize_text(c.name) or normalize_text(c.name) in norm_cat
                ]
                if not matched_ids:
                    return []
                stmt = stmt.where(ProductRow.category_id.in_(matched_ids))

            terms = _query_terms(query) if query and query.strip() else []
            if terms:
                all_terms_stmt = stmt
                for term in terms:
                    all_terms_stmt = all_terms_stmt.where(ProductRow.search_text.contains(term))
                pairs = list(
                    session.execute(
                        all_terms_stmt.order_by(ProductRow.price_brl.asc()).limit(limit)
                    ).all()
                )
                if not pairs and len(terms) > 1:
                    candidates = list(
                        session.execute(stmt.order_by(ProductRow.price_brl.asc())).all()
                    )
                    scored = [
                        (sum(1 for t in terms if t in prod.search_text), prod, cat_name)
                        for prod, cat_name in candidates
                    ]
                    scored = [item for item in scored if item[0] > 0]
                    scored.sort(key=lambda item: (-item[0], item[1].price_brl))
                    pairs = [(prod, cat_name) for _, prod, cat_name in scored[:limit]]
            else:
                pairs = list(
                    session.execute(stmt.order_by(ProductRow.price_brl.asc()).limit(limit)).all()
                )

            promos_map = self._load_promotions_map(session, [prod.product_id for prod, _ in pairs])
            return [
                self._to_summary(prod, cat_name, promos_map.get(prod.product_id, []))
                for prod, cat_name in pairs
            ]

    def get_product_detail(self, product_id_or_name: int | str) -> ProductDetail | None:
        raw_ref = str(product_id_or_name).strip()
        with self._session() as session:
            pair: tuple[ProductRow, str] | None = None
            base = select(ProductRow, CategoryRow.name).join(
                CategoryRow, CategoryRow.category_id == ProductRow.category_id
            )
            if isinstance(product_id_or_name, int) or raw_ref.isdigit():
                row = session.execute(base.where(ProductRow.product_id == int(raw_ref))).first()
                pair = (row[0], row[1]) if row else None
            else:
                norm_ref = normalize_text(raw_ref)
                all_pairs = [(r[0], r[1]) for r in session.execute(base).all()]
                pair = next(
                    ((p, c) for p, c in all_pairs if normalize_text(p.name) == norm_ref), None
                )
                if pair is None:
                    pair = next(
                        ((p, c) for p, c in all_pairs if norm_ref in normalize_text(p.name)), None
                    )
                if pair is None:
                    terms = _query_terms(raw_ref)
                    if terms:
                        scored = [
                            (sum(1 for t in terms if t in p.search_text), p, c)
                            for p, c in all_pairs
                        ]
                        scored = [item for item in scored if item[0] > 0]
                        if scored:
                            scored.sort(key=lambda item: -item[0])
                            pair = (scored[0][1], scored[0][2])

            if pair is None:
                return None

            product, category_name = pair
            promos = self._load_promotions_map(session, [product.product_id]).get(
                product.product_id, []
            )
            active = next((p for p in promos if p.is_active), None)
            expired = [p for p in promos if not p.is_active]
            raw_specs = json.loads(product.specs_json) if product.specs_json else {}
            specs = {str(k): str(v) for k, v in raw_specs.items()}

            return ProductDetail(
                product_id=product.product_id,
                name=product.name,
                category_id=product.category_id,
                category_name=category_name,
                price_brl=product.price_brl,
                stock_quantity=product.stock_quantity,
                status=product.status,
                is_sellable=product.is_sellable,
                active_promotion=active,
                description=product.description,
                specs=specs,
                expired_promotions=expired,
            )

    def find_alternatives(self, product_id: int, limit: int = 3) -> list[ProductSummary]:
        with self._session() as session:
            target = session.get(ProductRow, product_id)
            if target is None:
                return []
            stmt = (
                select(ProductRow, CategoryRow.name)
                .join(CategoryRow, CategoryRow.category_id == ProductRow.category_id)
                .where(
                    ProductRow.category_id == target.category_id,
                    ProductRow.product_id != product_id,
                    ProductRow.is_sellable.is_(True),
                )
                .order_by(func.abs(ProductRow.price_brl - target.price_brl).asc())
                .limit(limit)
            )
            pairs = [(r[0], r[1]) for r in session.execute(stmt).all()]
            promos_map = self._load_promotions_map(session, [p.product_id for p, _ in pairs])
            return [
                self._to_summary(p, cat_name, promos_map.get(p.product_id, []))
                for p, cat_name in pairs
            ]

    def _build_order_info(
        self,
        session: Session,
        order: OrderRow,
        customer: CustomerRow,
    ) -> OrderInfo:
        items_stmt = (
            select(OrderItemRow, ProductRow.name)
            .join(ProductRow, ProductRow.product_id == OrderItemRow.product_id)
            .where(OrderItemRow.order_id == order.order_id)
            .order_by(OrderItemRow.product_id.asc())
        )
        items = [
            OrderItemInfo(
                product_id=item.product_id,
                product_name=prod_name,
                quantity=item.quantity,
            )
            for item, prod_name in session.execute(items_stmt).all()
        ]
        return OrderInfo(
            order_id=order.order_id,
            customer_name=customer.name,
            customer_city=customer.city,
            order_date=order.order_date,
            status=order.status,
            total_brl=order.total_brl,
            payment_method=order.payment_method,
            tracking_code=order.tracking_code,
            estimated_delivery=order.estimated_delivery,
            notes=order.notes,
            items=items,
        )

    def verify_and_get_order(self, order_id: int, contact: str) -> OrderInfo | None:
        raw_contact = contact.strip()
        if not raw_contact:
            return None

        with self._session() as session:
            stmt = (
                select(OrderRow, CustomerRow)
                .join(CustomerRow, CustomerRow.customer_id == OrderRow.customer_id)
                .where(OrderRow.order_id == order_id)
            )
            result = session.execute(stmt).first()
            if result is None:
                return None

            order, customer = result[0], result[1]
            verified = False
            if "@" in raw_contact:
                verified = normalize_text(raw_contact) == customer.email_normalized
            else:
                digits = normalize_phone_digits(raw_contact)
                if len(digits) >= 8:
                    verified = digits == customer.phone_digits or customer.phone_digits.endswith(
                        digits
                    )

            if not verified:
                return None

            return self._build_order_info(session, order, customer)

    def count_customers_by_email(self, email: str) -> int:
        norm = normalize_text(email)
        if not norm or "@" not in norm:
            return 0
        with self._session() as session:
            count = session.scalar(
                select(func.count(CustomerRow.customer_id)).where(
                    CustomerRow.email_normalized == norm
                )
            )
            return int(count or 0)

    def list_orders_for_email(self, email: str) -> list[OrderInfo]:
        norm = normalize_text(email)
        if not norm or "@" not in norm:
            return []
        with self._session() as session:
            stmt = (
                select(OrderRow, CustomerRow)
                .join(CustomerRow, CustomerRow.customer_id == OrderRow.customer_id)
                .where(CustomerRow.email_normalized == norm)
                .order_by(OrderRow.order_date.desc(), OrderRow.order_id.desc())
            )
            return [
                self._build_order_info(session, order, customer)
                for order, customer in session.execute(stmt).all()
            ]

    def match_customer_email_and_phone(self, email: str, phone: str) -> bool:
        norm = normalize_text(email)
        digits = normalize_phone_digits(phone)
        if not norm or "@" not in norm or len(digits) < 8:
            return False
        with self._session() as session:
            customers = session.scalars(
                select(CustomerRow).where(CustomerRow.email_normalized == norm)
            )
            return any(
                digits == c.phone_digits or c.phone_digits.endswith(digits) for c in customers
            )

    def list_orders_for_email_and_phone(self, email: str, phone: str) -> list[OrderInfo]:
        norm = normalize_text(email)
        digits = normalize_phone_digits(phone)
        if not norm or "@" not in norm or len(digits) < 8:
            return []
        with self._session() as session:
            stmt = (
                select(OrderRow, CustomerRow)
                .join(CustomerRow, CustomerRow.customer_id == OrderRow.customer_id)
                .where(CustomerRow.email_normalized == norm)
                .order_by(OrderRow.order_date.desc(), OrderRow.order_id.desc())
            )
            matched: list[OrderInfo] = []
            for order, customer in session.execute(stmt).all():
                if digits == customer.phone_digits or customer.phone_digits.endswith(digits):
                    matched.append(self._build_order_info(session, order, customer))
            return matched

    def get_customer_city_by_email(self, email: str) -> str | None:
        norm = normalize_text(email)
        if not norm or "@" not in norm:
            return None
        with self._session() as session:
            row = session.scalar(
                select(CustomerRow)
                .where(CustomerRow.email_normalized == norm)
                .order_by(CustomerRow.customer_id.asc())
            )
            return row.city if row is not None and row.city.strip() else None

    def search_policies(self, query: str, limit: int = 4) -> list[PolicyChunkHit]:
        with self._session() as session:
            chunks = list(session.scalars(select(PolicyChunkRow)))
        if not chunks:
            return []

        embedded = [c for c in chunks if c.embedding_json]
        if self._embedder is not None and embedded and query.strip():
            try:
                query_vec = self._embedder.embed_query(query)
                scored = [
                    (cosine_similarity(query_vec, json.loads(c.embedding_json or "[]")), c)
                    for c in embedded
                ]
                scored.sort(key=lambda item: item[0], reverse=True)
                return [
                    PolicyChunkHit(
                        chunk_id=c.chunk_id,
                        section_number=c.section_number,
                        parent_title=c.parent_title,
                        title=c.title,
                        content=c.content,
                        page_start=c.page_start,
                        page_end=c.page_end,
                        score=round(score, 6),
                        retrieval_mode="vector",
                    )
                    for score, c in scored[:limit]
                ]
            except (genai_errors.APIError, httpx.HTTPError, OSError) as exc:
                logger.warning("Falha na busca vetorial; usando busca por palavras: %s", exc)

        terms = _query_terms(query)
        if not terms:
            return []
        keyword_hits: list[tuple[int, PolicyChunkRow]] = []
        for c in chunks:
            haystack = normalize_text(f"{c.parent_title} {c.title} {c.content}")
            matches = sum(1 for t in terms if t in haystack)
            if matches > 0:
                keyword_hits.append((matches, c))
        keyword_hits.sort(key=lambda item: (-item[0], item[1].page_start))
        return [
            PolicyChunkHit(
                chunk_id=c.chunk_id,
                section_number=c.section_number,
                parent_title=c.parent_title,
                title=c.title,
                content=c.content,
                page_start=c.page_start,
                page_end=c.page_end,
                score=float(matches),
                retrieval_mode="keyword",
            )
            for matches, c in keyword_hits[:limit]
        ]

    def get_policy_section(self, section_number: str) -> list[PolicyChunkHit]:
        sec = section_number.strip().removeprefix("sec-")
        with self._session() as session:
            stmt = (
                select(PolicyChunkRow)
                .where(
                    (PolicyChunkRow.section_number == sec)
                    | (PolicyChunkRow.section_number.like(f"{sec}.%"))
                )
                .order_by(PolicyChunkRow.page_start.asc(), PolicyChunkRow.chunk_id.asc())
            )
            rows = list(session.scalars(stmt))
        return [
            PolicyChunkHit(
                chunk_id=r.chunk_id,
                section_number=r.section_number,
                parent_title=r.parent_title,
                title=r.title,
                content=r.content,
                page_start=r.page_start,
                page_end=r.page_end,
                score=1.0,
                retrieval_mode="keyword",
            )
            for r in rows
        ]

    def get_knowledge_status(self) -> KnowledgeStatus:
        with self._session() as session:
            rows = {r.source_key: r for r in session.scalars(select(KnowledgeSourceRow))}

        def build(key: Any) -> KnowledgeSourceStatus:
            row = rows.get(key)
            if row is None:
                return KnowledgeSourceStatus(
                    source_key=key,
                    loaded=False,
                    file_names=[],
                    record_count=0,
                    audit_count=0,
                    uploaded_at=None,
                )
            return KnowledgeSourceStatus(
                source_key=key,
                loaded=True,
                file_names=json.loads(row.file_names_json),
                record_count=row.record_count,
                audit_count=row.audit_count,
                uploaded_at=row.uploaded_at,
            )

        csvs = build("store_csvs")
        pdf = build("policy_pdf")
        return KnowledgeStatus(csvs=csvs, pdf=pdf, ready=csvs.loaded and pdf.loaded)

    def _row_to_user(self, row: UserRow) -> AuthenticatedUser:
        return AuthenticatedUser(
            user_id=row.user_id,
            name=row.name,
            email=row.email,
            role=row.role,
        )

    def get_user_by_id(self, user_id: str) -> AuthenticatedUser | None:
        with self._session() as session:
            row = session.get(UserRow, user_id)
            return self._row_to_user(row) if row is not None else None

    def get_user_with_hash_by_email(self, email: str) -> tuple[AuthenticatedUser, str] | None:
        norm = email.strip().lower()
        with self._session() as session:
            row = session.scalar(select(UserRow).where(UserRow.email == norm))
            if row is None:
                return None
            return self._row_to_user(row), row.password_hash

    def create_user(
        self,
        name: str,
        email: str,
        password_hash: str,
        role: UserRole = "customer",
    ) -> AuthenticatedUser:
        norm = email.strip().lower()
        clean_name = name.strip() or norm.split("@")[0]
        now = datetime.now(UTC).isoformat()
        with self._session() as session:
            existing = session.scalar(select(UserRow).where(UserRow.email == norm))
            if existing is not None:
                raise ValueError("Já existe uma conta cadastrada com este e-mail.")
            row = UserRow(
                user_id=uuid.uuid4().hex[:12],
                name=clean_name,
                email=norm,
                password_hash=password_hash,
                role=role,
                created_at=now,
            )
            session.add(row)
            session.commit()
            return self._row_to_user(row)

    def ensure_seed_user(
        self,
        name: str,
        email: str,
        password_hash: str,
        role: UserRole,
    ) -> None:
        norm = email.strip().lower()
        with self._session() as session:
            existing = session.scalar(select(UserRow).where(UserRow.email == norm))
            if existing is not None:
                return
            session.add(
                UserRow(
                    user_id=uuid.uuid4().hex[:12],
                    name=name.strip(),
                    email=norm,
                    password_hash=password_hash,
                    role=role,
                    created_at=datetime.now(UTC).isoformat(),
                )
            )
            session.commit()

    def sync_customer_seed_users(
        self,
        password_factory: Callable[[], str],
    ) -> int:
        with self._session() as session:
            customers = list(
                session.scalars(select(CustomerRow).order_by(CustomerRow.customer_id.asc()))
            )
            if not customers:
                return 0
            existing_emails = set(session.scalars(select(UserRow.email)))
            to_create: list[tuple[str, str]] = []
            seen: set[str] = set()
            for customer in customers:
                norm = customer.email.strip().lower()
                if not norm or "@" not in norm or norm in existing_emails or norm in seen:
                    continue
                seen.add(norm)
                to_create.append((customer.name.strip() or norm.split("@")[0], norm))
            if not to_create:
                return 0
            password_hash = password_factory()
            now = datetime.now(UTC).isoformat()
            session.add_all(
                [
                    UserRow(
                        user_id=uuid.uuid4().hex[:12],
                        name=name,
                        email=email_norm,
                        password_hash=password_hash,
                        role="customer",
                        created_at=now,
                    )
                    for name, email_norm in to_create
                ]
            )
            session.commit()
            return len(to_create)

    def list_sessions(self, user_id: str | None = None) -> list[dict[str, Any]]:
        with self._session() as session:
            stmt = select(SessionRow).order_by(SessionRow.updated_at.desc())
            if user_id is not None:
                stmt = stmt.where(SessionRow.user_id == user_id)
            rows = session.scalars(stmt)
            return [
                {
                    "session_id": r.session_id,
                    "title": r.title,
                    "created_at": r.created_at,
                    "updated_at": r.updated_at,
                }
                for r in rows
            ]

    def get_session(
        self, session_id: str, user_id: str | None = None
    ) -> dict[str, Any] | None:
        with self._session() as session:
            row = session.get(SessionRow, session_id)
            if row is None:
                return None
            if user_id is not None and row.user_id != user_id:
                return None
            return {
                "session_id": row.session_id,
                "title": row.title,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }

    def create_session(
        self, session_id: str, title: str, user_id: str | None = None
    ) -> None:
        now = datetime.now(UTC).isoformat()
        with self._session() as session:
            session.add(
                SessionRow(
                    session_id=session_id,
                    user_id=user_id,
                    title=title,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.commit()

    def update_session_title(self, session_id: str, title: str) -> None:
        with self._session() as session:
            row = session.get(SessionRow, session_id)
            if row is not None:
                row.title = title
                row.updated_at = datetime.now(UTC).isoformat()
                session.commit()

    def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        with self._session() as session:
            stmt = (
                select(MessageRow)
                .where(MessageRow.session_id == session_id)
                .order_by(MessageRow.id.asc())
            )
            return [
                {
                    "id": r.id,
                    "session_id": r.session_id,
                    "role": r.role,
                    "content": r.content,
                    "trace": json.loads(r.trace_json),
                    "created_at": r.created_at,
                }
                for r in session.scalars(stmt)
            ]

    def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        trace: list[dict[str, Any]] | None = None,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        with self._session() as session:
            session.add(
                MessageRow(
                    session_id=session_id,
                    role=role,
                    content=content,
                    trace_json=json.dumps(trace or [], ensure_ascii=False),
                    created_at=now,
                )
            )
            parent = session.get(SessionRow, session_id)
            if parent is not None:
                parent.updated_at = now
            session.commit()

    def delete_session(self, session_id: str, user_id: str | None = None) -> bool:
        with self._session() as session:
            stmt = delete(SessionRow).where(SessionRow.session_id == session_id)
            if user_id is not None:
                stmt = stmt.where(SessionRow.user_id == user_id)
            result = session.execute(stmt)
            session.commit()
            return bool(result.rowcount)

    def get_setting(self, key: str) -> str | None:
        with self._session() as session:
            row = session.get(AppSettingRow, key)
            return row.value if row is not None else None

    def set_setting(self, key: str, value: str) -> None:
        now = datetime.now(UTC).isoformat()
        with self._session() as session:
            row = session.get(AppSettingRow, key)
            if row is None:
                session.add(AppSettingRow(key=key, value=value, updated_at=now))
            else:
                row.value = value
                row.updated_at = now
            session.commit()

    def get_session_compaction(self, session_id: str) -> SessionCompaction | None:
        with self._session() as session:
            row = session.get(SessionSummaryRow, session_id)
            if row is None:
                return None
            return SessionCompaction(
                session_id=row.session_id,
                summary=row.summary,
                compacted_up_to_message_id=row.compacted_up_to_message_id,
                updated_at=row.updated_at,
            )

    def save_session_compaction(
        self,
        session_id: str,
        summary: str,
        compacted_up_to_message_id: int,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        with self._session() as session:
            row = session.get(SessionSummaryRow, session_id)
            if row is None:
                session.add(
                    SessionSummaryRow(
                        session_id=session_id,
                        summary=summary,
                        compacted_up_to_message_id=compacted_up_to_message_id,
                        updated_at=now,
                    )
                )
            else:
                row.summary = summary
                row.compacted_up_to_message_id = compacted_up_to_message_id
                row.updated_at = now
            session.commit()

    def list_user_memories(self, user_id: str, limit: int = 12) -> list[UserMemory]:
        with self._session() as session:
            stmt = (
                select(UserMemoryRow)
                .where(UserMemoryRow.user_id == user_id)
                .order_by(UserMemoryRow.updated_at.desc(), UserMemoryRow.id.desc())
                .limit(limit)
            )
            return [
                UserMemory(
                    fact_key=r.fact_key,
                    content=r.content,
                    updated_at=r.updated_at,
                )
                for r in session.scalars(stmt)
            ]

    def upsert_user_memories(
        self,
        user_id: str,
        memories: list[tuple[str, str]],
    ) -> None:
        if not memories:
            return
        now = datetime.now(UTC).isoformat()
        with self._session() as session:
            for fact_key, content in memories:
                existing = session.scalar(
                    select(UserMemoryRow).where(
                        UserMemoryRow.user_id == user_id,
                        UserMemoryRow.fact_key == fact_key,
                    )
                )
                if existing is None:
                    session.add(
                        UserMemoryRow(
                            user_id=user_id,
                            fact_key=fact_key,
                            content=content,
                            updated_at=now,
                        )
                    )
                else:
                    existing.content = content
                    existing.updated_at = now
            session.commit()

    def delete_user_memory(self, user_id: str, fact_key: str) -> bool:
        with self._session() as session:
            stmt = delete(UserMemoryRow).where(
                UserMemoryRow.user_id == user_id,
                UserMemoryRow.fact_key == fact_key,
            )
            result = session.execute(stmt)
            session.commit()
            return bool(result.rowcount)

    def clear_user_memories(self, user_id: str) -> int:
        with self._session() as session:
            stmt = delete(UserMemoryRow).where(UserMemoryRow.user_id == user_id)
            result = session.execute(stmt)
            session.commit()
            return int(result.rowcount or 0)

    def get_custom_instructions(self, user_id: str) -> UserPersonalization:
        with self._session() as session:
            row = session.get(UserPreferenceRow, user_id)
            if row is None:
                return UserPersonalization(custom_instructions="", updated_at=None)
            return UserPersonalization(
                custom_instructions=row.custom_instructions,
                updated_at=row.updated_at,
            )

    def save_custom_instructions(
        self,
        user_id: str,
        instructions: str,
    ) -> UserPersonalization:
        now = datetime.now(UTC).isoformat()
        clean = instructions.strip()
        with self._session() as session:
            row = session.get(UserPreferenceRow, user_id)
            if row is None:
                session.add(
                    UserPreferenceRow(
                        user_id=user_id,
                        custom_instructions=clean,
                        updated_at=now,
                    )
                )
            else:
                row.custom_instructions = clean
                row.updated_at = now
            session.commit()
        return UserPersonalization(custom_instructions=clean, updated_at=now)

    def _row_to_order_draft(self, row: OrderDraftRow) -> OrderDraft:
        return OrderDraft(
            draft_id=row.draft_id,
            session_id=row.session_id,
            user_id=row.user_id,
            product_id=row.product_id,
            product_name=row.product_name,
            quantity=row.quantity,
            unit_price_brl=row.unit_price_brl,
            discount_percent=row.discount_percent,
            subtotal_brl=row.subtotal_brl,
            shipping_brl=row.shipping_brl,
            shipping_note=row.shipping_note,
            total_brl=row.total_brl,
            payment_method=row.payment_method,
            payment_label=row.payment_label,
            city=row.city,
            status=row.status,
            order_id=row.order_id,
            tracking_code=row.tracking_code,
            created_at=row.created_at,
            confirmed_at=row.confirmed_at,
            deliver_at=row.deliver_at,
            delivered_at=row.delivered_at,
        )

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
    ) -> OrderDraft:
        now = _utc_iso()
        row = OrderDraftRow(
            draft_id=uuid.uuid4().hex[:12],
            session_id=session_id,
            user_id=user_id,
            product_id=product_id,
            product_name=product_name,
            quantity=quantity,
            unit_price_brl=unit_price_brl,
            discount_percent=discount_percent,
            subtotal_brl=subtotal_brl,
            shipping_brl=shipping_brl,
            shipping_note=shipping_note,
            total_brl=total_brl,
            payment_method=payment_method,
            payment_label=payment_label,
            city=city,
            status="pending",
            order_id=None,
            tracking_code="",
            created_at=now,
            confirmed_at=None,
            deliver_at=None,
            delivered_at=None,
        )
        with self._session() as session:
            session.add(row)
            session.commit()
            return self._row_to_order_draft(row)

    def list_session_order_drafts(self, session_id: str) -> list[OrderDraft]:
        with self._session() as session:
            stmt = (
                select(OrderDraftRow)
                .where(OrderDraftRow.session_id == session_id)
                .order_by(OrderDraftRow.created_at.asc())
            )
            return [self._row_to_order_draft(row) for row in session.scalars(stmt)]

    def get_order_draft(
        self, draft_id: str, user_id: str | None = None
    ) -> OrderDraft | None:
        with self._session() as session:
            row = session.get(OrderDraftRow, draft_id)
            if row is None:
                return None
            if user_id is not None and row.user_id != user_id:
                return None
            return self._row_to_order_draft(row)

    def confirm_order_draft(
        self,
        draft_id: str,
        user: AuthenticatedUser,
        auto_delivery_seconds: int = 300,
    ) -> tuple[OrderDraft, dict[str, Any]]:
        now_dt = datetime.now(UTC)
        now_iso = _utc_iso(now_dt)
        deliver_at_iso = _utc_iso(now_dt + timedelta(seconds=max(0, auto_delivery_seconds)))
        local_today = now_dt.astimezone(STORE_TZ).date().isoformat()

        with self._session() as session:
            draft = session.get(OrderDraftRow, draft_id)
            if draft is None or draft.user_id != user.user_id:
                raise LookupError("Pedido não encontrado.")
            if draft.status != "pending":
                raise ValueError("Este pedido já foi confirmado ou cancelado.")

            product = session.get(ProductRow, draft.product_id)
            if (
                product is None
                or not product.is_sellable
                or product.stock_quantity < draft.quantity
            ):
                raise ValueError("Este instrumento não possui estoque suficiente no momento.")

            email_norm = normalize_text(user.email)
            customer = session.scalar(
                select(CustomerRow)
                .where(CustomerRow.email_normalized == email_norm)
                .order_by(CustomerRow.customer_id.asc())
            )
            if customer is None:
                next_cid = int(session.scalar(select(func.max(CustomerRow.customer_id))) or 0) + 1
                customer = CustomerRow(
                    customer_id=next_cid,
                    name=user.name.strip() or user.email,
                    name_normalized=normalize_text(user.name or user.email),
                    phone="",
                    phone_digits="",
                    email=user.email,
                    email_normalized=email_norm,
                    city=draft.city,
                )
                session.add(customer)
                session.flush()

            product.stock_quantity = max(0, product.stock_quantity - draft.quantity)
            product.is_sellable = product.status == "active" and product.stock_quantity > 0

            next_order_id = int(session.scalar(select(func.max(OrderRow.order_id))) or 0) + 1
            tracking_code = _generate_tracking_code()
            session.add(
                OrderRow(
                    order_id=next_order_id,
                    customer_id=customer.customer_id,
                    order_date=local_today,
                    status="confirmed",
                    total_brl=draft.total_brl,
                    payment_method=draft.payment_method,
                    tracking_code=tracking_code,
                    estimated_delivery="",
                    notes="Pedido realizado pelo chat",
                )
            )
            session.flush()
            session.add(
                OrderItemRow(
                    order_id=next_order_id,
                    product_id=draft.product_id,
                    quantity=draft.quantity,
                )
            )

            draft.status = "confirmed"
            draft.order_id = next_order_id
            draft.tracking_code = tracking_code
            draft.confirmed_at = now_iso
            draft.deliver_at = deliver_at_iso

            minutes = max(1, round(auto_delivery_seconds / 60)) if auto_delivery_seconds > 0 else 0
            delivery_hint = (
                f"Para fins de teste, este pedido será marcado automaticamente como entregue "
                f"em {minutes} {'minuto' if minutes == 1 else 'minutos'}."
                if minutes > 0
                else "Para fins de teste, a entrega simulada será concluída em instantes."
            )
            confirmation_text = (
                f"Pedido **#{next_order_id}** confirmado ({draft.quantity}x {draft.product_name}, "
                f"total **{_format_brl(draft.total_brl)}**, {draft.payment_label}). "
                f"Código de rastreio `{tracking_code}`. {delivery_hint}"
            )
            msg = MessageRow(
                session_id=draft.session_id,
                role="assistant",
                content=confirmation_text,
                trace_json="[]",
                created_at=now_iso,
            )
            session.add(msg)
            parent = session.get(SessionRow, draft.session_id)
            if parent is not None:
                parent.updated_at = now_iso
            session.flush()

            message_payload = {
                "id": msg.id,
                "session_id": msg.session_id,
                "role": msg.role,
                "content": msg.content,
                "trace": [],
                "created_at": msg.created_at,
            }
            updated_draft = self._row_to_order_draft(draft)
            session.commit()
            return updated_draft, message_payload

    def cancel_order_draft(self, draft_id: str, user_id: str) -> OrderDraft:
        with self._session() as session:
            draft = session.get(OrderDraftRow, draft_id)
            if draft is None or draft.user_id != user_id:
                raise LookupError("Pedido não encontrado.")
            if draft.status != "pending":
                raise ValueError("Apenas pedidos pendentes podem ser cancelados.")
            draft.status = "cancelled"
            updated = self._row_to_order_draft(draft)
            session.commit()
            return updated

    def finalize_due_deliveries(self, now: datetime | None = None) -> list[OrderDraft]:
        now_dt = now.astimezone(UTC) if now is not None else datetime.now(UTC)
        now_iso = _utc_iso(now_dt)
        local_today = now_dt.astimezone(STORE_TZ).date().isoformat()

        delivered: list[OrderDraft] = []
        with self._session() as session:
            stmt = (
                select(OrderDraftRow)
                .where(
                    OrderDraftRow.status == "confirmed",
                    OrderDraftRow.deliver_at.is_not(None),
                    OrderDraftRow.deliver_at <= now_iso,
                )
                .order_by(OrderDraftRow.deliver_at.asc())
            )
            due_rows = list(session.scalars(stmt))
            if not due_rows:
                return []

            for draft in due_rows:
                if draft.order_id is not None:
                    order = session.get(OrderRow, draft.order_id)
                    if order is not None and order.status != "cancelled":
                        order.status = "delivered"
                        order.estimated_delivery = local_today

                draft.status = "delivered"
                draft.delivered_at = now_iso
                notification = (
                    f"Seu pedido **#{draft.order_id}** ({draft.quantity}x {draft.product_name}) "
                    f"foi marcado como **entregue** (código de rastreio `{draft.tracking_code}`). "
                    "Caso precise de ajuda, troca ou devolução dentro do prazo legal de 7 dias "
                    "corridos, é só avisar por aqui."
                )
                session.add(
                    MessageRow(
                        session_id=draft.session_id,
                        role="assistant",
                        content=notification,
                        trace_json="[]",
                        created_at=now_iso,
                    )
                )
                parent = session.get(SessionRow, draft.session_id)
                if parent is not None:
                    parent.updated_at = now_iso
                delivered.append(self._row_to_order_draft(draft))

            session.commit()
        return delivered
