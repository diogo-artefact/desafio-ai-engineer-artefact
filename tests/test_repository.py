from __future__ import annotations

from pathlib import Path

from emporio.db.repository import SQLiteStoreRepository
from emporio.etl.embeddings import l2_normalize
from emporio.etl.loader import load_raw_dir

RAW_DIR = Path("data/raw")


class _SemanticEmbedder:
    def _encode(self, text: str) -> list[float]:
        lower = text.lower()
        raw = [
            1.0 if any(w in lower for w in ("arrependimento", "desistir")) else 0.05,
            1.0 if any(w in lower for w in ("motoboy", "jadlog", "sedex", "correios")) else 0.05,
            1.0 if any(w in lower for w in ("pix", "parcela", "cartao")) else 0.05,
            1.0 if any(w in lower for w in ("garantia", "defeito", "fabricante")) else 0.05,
        ]
        return l2_normalize(raw)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._encode(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._encode(text)


def test_empty_database_starts_unloaded_without_crashing(tmp_path: Path) -> None:
    repo = SQLiteStoreRepository(tmp_path / "empty.db")
    status = repo.get_knowledge_status()
    assert status.ready is False
    assert status.csvs.loaded is False
    assert status.pdf.loaded is False
    assert repo.search_products(query="violao") == []
    assert repo.search_policies("devolucao") == []


def test_catalog_search_filters_promotions_and_alternatives(tmp_path: Path) -> None:
    db_path = tmp_path / "emporio.db"
    embedder = _SemanticEmbedder()
    load_raw_dir(RAW_DIR, db_path, embedder=embedder)
    repo = SQLiteStoreRepository(db_path, embedder=embedder)

    guitars = repo.search_products(category="Violões", max_price=1000.0, only_available=True)
    assert len(guitars) > 0
    assert all(p.category_name == "Violões" for p in guitars)
    assert all(p.price_brl <= 1000.0 and p.is_sellable for p in guitars)

    accent_free = repo.search_products(query="violao nylon")
    assert len(accent_free) > 0

    crafter = repo.get_product_detail("Crafter HT-100")
    assert crafter is not None
    assert crafter.active_promotion is not None
    assert crafter.active_promotion.discount_percent == 18.0

    takamine = repo.get_product_detail("Takamine GD20")
    assert takamine is not None
    assert takamine.active_promotion is None
    assert any(p.discount_percent == 12.0 for p in takamine.expired_promotions)

    giannini = repo.get_product_detail("Giannini GF-3D")
    assert giannini is not None
    assert giannini.is_sellable is False
    assert giannini.stock_quantity == 0
    alternatives = repo.find_alternatives(giannini.product_id, limit=3)
    assert len(alternatives) == 3
    assert all(a.is_sellable and a.category_id == giannini.category_id for a in alternatives)


def test_order_verification_enforces_two_factor_match(tmp_path: Path) -> None:
    db_path = tmp_path / "emporio.db"
    load_raw_dir(RAW_DIR, db_path)
    repo = SQLiteStoreRepository(db_path)

    assert repo.verify_and_get_order(10, "wrong@jmail.com") is None
    assert repo.verify_and_get_order(10, "67999990000") is None

    by_email = repo.verify_and_get_order(10, "BRUNO.MARTINS@JMAIL.COM")
    assert by_email is not None
    assert by_email.order_id == 10
    assert by_email.customer_name == "Bruno Carvalho Martins"
    assert by_email.items[0].product_id == 135

    by_phone = repo.verify_and_get_order(10, "98543-2109")
    assert by_phone is not None
    assert by_phone.order_id == 10


def test_vector_policy_search_finds_paraphrases_and_falls_back_to_keywords(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "emporio.db"
    embedder = _SemanticEmbedder()
    load_raw_dir(RAW_DIR, db_path, embedder=embedder)

    vector_repo = SQLiteStoreRepository(db_path, embedder=embedder)
    hits = vector_repo.search_policies("posso desistir da compra online?", limit=3)
    assert len(hits) > 0
    assert all(h.retrieval_mode == "vector" for h in hits)
    assert any(h.chunk_id == "sec-4.1" for h in hits)

    keyword_repo = SQLiteStoreRepository(db_path, embedder=None)
    fallback_hits = keyword_repo.search_policies("arrependimento", limit=3)
    assert len(fallback_hits) > 0
    assert all(h.retrieval_mode == "keyword" for h in fallback_hits)
    assert any(h.chunk_id == "sec-4.1" for h in fallback_hits)

    section_4 = vector_repo.get_policy_section("4")
    assert [h.section_number for h in section_4] == ["4", "4.1", "4.2", "4.3", "4.4"]


def test_session_persistence_roundtrip(tmp_path: Path) -> None:
    repo = SQLiteStoreRepository(tmp_path / "sessions.db")
    repo.create_session("s1", "Violões")
    repo.append_message("s1", "user", "Quais violões até 1000?")
    repo.append_message(
        "s1",
        "assistant",
        "Temos opções em estoque.",
        trace=[{"type": "tool", "label": "Consultou catálogo"}],
    )
    sessions = repo.list_sessions()
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == "s1"

    msgs = repo.get_messages("s1")
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[1]["trace"][0]["label"] == "Consultou catálogo"

    repo.delete_session("s1")
    assert repo.list_sessions() == []
    assert repo.get_messages("s1") == []
