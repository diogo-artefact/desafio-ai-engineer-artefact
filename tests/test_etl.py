from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from emporio.db.schema import get_connection
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

    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT source_key, record_count FROM knowledge_sources"
        ).fetchall()
        sources = {r["source_key"]: r["record_count"] for r in rows}
        assert sources == {"store_csvs": 65, "policy_pdf": 26}

        p136 = conn.execute(
            "SELECT status, stock_quantity, is_sellable FROM products WHERE product_id = 136"
        ).fetchone()
        assert (p136["status"], p136["stock_quantity"], p136["is_sellable"]) == (
            "discontinued",
            0,
            0,
        )

        p130 = conn.execute(
            "SELECT status, is_sellable FROM products WHERE product_id = 130"
        ).fetchone()
        assert (p130["status"], p130["is_sellable"]) == ("coming_soon", 0)

        for pid, forbidden_brand in [
            (135, "fender"),
            (137, "ibanez"),
            (139, "pearl"),
            (140, "tama"),
            (142, "roland"),
            (144, "yamaha"),
        ]:
            row = conn.execute(
                "SELECT description, raw_description FROM products WHERE product_id = ?",
                (pid,),
            ).fetchone()
            assert forbidden_brand not in row["description"].lower()
            assert forbidden_brand in row["raw_description"].lower()

        arrep = conn.execute(
            "SELECT parent_title, title, embedding_json "
            "FROM policy_chunks WHERE chunk_id = 'sec-4.1'"
        ).fetchone()
        assert arrep is not None
        assert "Trocas e Devoluções" in arrep["parent_title"]
        assert "Arrependimento" in arrep["title"]
        vec = json.loads(arrep["embedding_json"])
        assert math.isclose(math.sqrt(sum(x * x for x in vec)), 1.0, rel_tol=1e-6)

        fts_prods = conn.execute(
            "SELECT product_id FROM products_fts WHERE products_fts MATCH 'violao'"
        ).fetchall()
        assert len(fts_prods) > 0

        fts_pol = conn.execute(
            "SELECT chunk_id FROM policy_chunks_fts WHERE policy_chunks_fts MATCH 'arrependimento'"
        ).fetchall()
        assert any(r["chunk_id"] == "sec-4.1" for r in fts_pol)
    finally:
        conn.close()


def test_reuploading_pdf_without_embedder_preserves_csvs_and_sessions(tmp_path: Path) -> None:
    db_path = tmp_path / "emporio.db"
    load_raw_dir(RAW_DIR, db_path, embedder=_FakeEmbedder())

    conn = get_connection(db_path)
    try:
        conn.execute(
            "INSERT INTO sessions (session_id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("sess-1", "Teste", "2026-02-20T10:00:00Z", "2026-02-20T10:00:00Z"),
        )
        conn.execute(
            "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            ("sess-1", "user", "Oi", "2026-02-20T10:00:01Z"),
        )
        conn.commit()
    finally:
        conn.close()

    pdf_path = RAW_DIR / "políticas_da_loja.pdf"
    pdf_report = ingest_policy_pdf(
        pdf_path.read_bytes(),
        db_path=db_path,
        filename=pdf_path.name,
        embedder=None,
    )
    assert pdf_report.policy_chunks == 26
    assert pdf_report.embedded_chunks == 0

    conn = get_connection(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 65
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM etl_audit_log").fetchone()[0] == 11
    finally:
        conn.close()


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
