from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from sqlalchemy import func, select

from emporio.db.schema import (
    AuditLogRow,
    KnowledgeSourceRow,
    MessageRow,
    PolicyChunkRow,
    ProductRow,
    SessionRow,
    session_scope,
)
from emporio.etl.embeddings import cosine_similarity, l2_normalize
from emporio.etl.loader import ingest_policy_pdf, ingest_store_csvs, load_raw_dir

RAW_DIR = Path("data/raw")


class _FakeEmbedder:
    def _encode(self, text: str) -> list[float]:
        lower = text.lower()
        raw = [
            1.0 if "arrependimento" in lower or "devolucao" in lower else 0.1,
            1.0 if "frete" in lower or "motoboy" in lower or "jadlog" in lower else 0.1,
            1.0 if "pix" in lower or "parcelamento" in lower else 0.1,
            1.0 if "garantia" in lower or "defeito" in lower else 0.1,
        ]
        return l2_normalize(raw)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._encode(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._encode(text)


def test_independent_csv_and_pdf_uploads_sanitize_and_embed(tmp_path: Path) -> None:
    db_path = tmp_path / "emporio.db"
    report = load_raw_dir(RAW_DIR, db_path, embedder=_FakeEmbedder())

    assert report.csv.categories == 9
    assert report.csv.products == 65
    assert report.csv.sellable_products == 61
    assert report.csv.promotions == 25
    assert report.csv.active_promotions == 4
    assert report.csv.customers == 50
    assert report.csv.orders == 20
    assert report.csv.order_items == 22
    assert report.csv.audit_entries == 9
    assert report.pdf.policy_chunks == 26
    assert report.pdf.embedded_chunks == 26
    assert report.pdf.audit_entries == 2

    with session_scope(db_path) as session:
        sources = {
            r.source_key: r.record_count
            for r in session.scalars(select(KnowledgeSourceRow))
        }
        assert sources == {"store_csvs": 65, "policy_pdf": 26}

        p136 = session.get(ProductRow, 136)
        assert p136 is not None
        assert (p136.status, p136.stock_quantity, p136.is_sellable) == ("discontinued", 0, False)

        p130 = session.get(ProductRow, 130)
        assert p130 is not None
        assert (p130.status, p130.is_sellable) == ("coming_soon", False)

        for pid, forbidden_brand in [
            (135, "fender"),
            (137, "ibanez"),
            (139, "pearl"),
            (140, "tama"),
            (142, "roland"),
            (144, "yamaha"),
        ]:
            prod = session.get(ProductRow, pid)
            assert prod is not None
            assert forbidden_brand not in prod.description.lower()
            assert forbidden_brand in prod.raw_description.lower()

        arrep = session.get(PolicyChunkRow, "sec-4.1")
        assert arrep is not None
        assert "Trocas e Devoluções" in arrep.parent_title
        assert "Arrependimento" in arrep.title
        vec = json.loads(arrep.embedding_json or "[]")
        assert math.isclose(math.sqrt(sum(x * x for x in vec)), 1.0, rel_tol=1e-6)


def test_reuploading_pdf_without_embedder_preserves_csvs_and_sessions(tmp_path: Path) -> None:
    db_path = tmp_path / "emporio.db"
    load_raw_dir(RAW_DIR, db_path, embedder=_FakeEmbedder())

    with session_scope(db_path) as session:
        session.add(
            SessionRow(
                session_id="sess-1",
                title="Teste",
                created_at="2026-02-20T10:00:00Z",
                updated_at="2026-02-20T10:00:00Z",
            )
        )
        session.flush()
        session.add(
            MessageRow(
                session_id="sess-1",
                role="user",
                content="Oi",
                trace_json="[]",
                created_at="2026-02-20T10:00:01Z",
            )
        )

    pdf_path = RAW_DIR / "políticas_da_loja.pdf"
    pdf_report = ingest_policy_pdf(
        pdf_path.read_bytes(),
        db_path=db_path,
        filename=pdf_path.name,
        embedder=None,
    )
    assert pdf_report.policy_chunks == 26
    assert pdf_report.embedded_chunks == 0

    with session_scope(db_path) as session:
        assert session.scalar(select(func.count(ProductRow.product_id))) == 65
        assert session.scalar(select(func.count(SessionRow.session_id))) == 1
        assert session.scalar(select(func.count(MessageRow.id))) == 1
        assert session.scalar(select(func.count(AuditLogRow.id))) == 11


def test_csv_upload_rejects_incomplete_file_set(tmp_path: Path) -> None:
    db_path = tmp_path / "emporio.db"
    only_categories = {
        "categories.csv": (RAW_DIR / "desafio_tecnico_ai_eng - categories.csv").read_bytes()
    }
    with pytest.raises(ValueError, match="Arquivos CSV obrigatórios ausentes"):
        ingest_store_csvs(only_categories, db_path=db_path)


def test_cosine_similarity_properties() -> None:
    a = l2_normalize([3.0, 4.0])
    b = l2_normalize([6.0, 8.0])
    c = l2_normalize([-4.0, 3.0])
    assert math.isclose(cosine_similarity(a, b), 1.0, rel_tol=1e-6)
    assert math.isclose(cosine_similarity(a, c), 0.0, abs_tol=1e-6)
