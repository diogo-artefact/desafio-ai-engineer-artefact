from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import UTC, datetime
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
    OrderItemRow,
    OrderRow,
    PolicyChunkRow,
    ProductRow,
    PromotionRow,
    SessionRow,
    UserRow,
    create_db_engine,
    init_schema,
)
from emporio.domain.models import (
    KnowledgeSourceStatus,
    KnowledgeStatus,
    OrderInfo,
    OrderItemInfo,
    PolicyChunkHit,
    ProductDetail,
    ProductSummary,
    PromotionInfo,
)
from emporio.domain.text import normalize_phone_digits, normalize_text
from emporio.etl.embeddings import Embedder, cosine_similarity

logger = logging.getLogger(__name__)


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

            items_stmt = (
                select(OrderItemRow, ProductRow.name)
                .join(ProductRow, ProductRow.product_id == OrderItemRow.product_id)
                .where(OrderItemRow.order_id == order_id)
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
