from __future__ import annotations

import io
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic_ai.models.function import FunctionModel

from emporio.api import AppContainer, create_app
from emporio.etl.embeddings import l2_normalize

RAW_DIR = Path("data/raw")


class _StubEmbedder:
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [l2_normalize([1.0, float(i + 1)]) for i, _ in enumerate(texts)]

    def embed_query(self, text: str) -> list[float]:
        return l2_normalize([1.0, 1.0])


def _make_client(tmp_path: Path) -> TestClient:
    async def noop_stream(messages, info):
        yield "ok"

    container = AppContainer.build(
        db_path=tmp_path / "api.db",
        embedder=_StubEmbedder(),
        model=FunctionModel(stream_function=noop_stream),
    )
    return TestClient(create_app(container))


def _auth_headers(client: TestClient, email: str, password: str) -> dict[str, str]:
    res = client.post("/api/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['token']}"}


def test_starts_empty_and_uploads_both_slots_independently(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    admin_headers = _auth_headers(client, "admin@admin.com", "admin123")

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["ready"] is False

    incomplete = client.post(
        "/api/knowledge/csvs",
        headers=admin_headers,
        files=[
            (
                "files",
                (
                    "categories.csv",
                    (RAW_DIR / "desafio_tecnico_ai_eng - categories.csv").read_bytes(),
                    "text/csv",
                ),
            )
        ],
    )
    assert incomplete.status_code == 400

    csv_files = [
        ("files", (p.name, p.read_bytes(), "text/csv")) for p in sorted(RAW_DIR.glob("*.csv"))
    ]
    csv_res = client.post("/api/knowledge/csvs", headers=admin_headers, files=csv_files)
    assert csv_res.status_code == 200
    assert csv_res.json()["report"]["products"] == 65
    assert csv_res.json()["knowledge"]["csvs"]["loaded"] is True
    assert csv_res.json()["knowledge"]["ready"] is False

    bad_pdf = client.post(
        "/api/knowledge/pdf",
        headers=admin_headers,
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert bad_pdf.status_code == 400

    pdf_path = RAW_DIR / "políticas_da_loja.pdf"
    pdf_res = client.post(
        "/api/knowledge/pdf",
        headers=admin_headers,
        files={"file": (pdf_path.name, pdf_path.read_bytes(), "application/pdf")},
    )
    assert pdf_res.status_code == 200
    assert pdf_res.json()["report"]["policy_chunks"] == 26
    assert pdf_res.json()["report"]["embedded_chunks"] == 26
    assert pdf_res.json()["knowledge"]["ready"] is True

    status = client.get("/api/knowledge", headers=admin_headers).json()
    assert status["ready"] is True
    assert len(status["required_csv_tables"]) == 6


def test_csv_upload_accepts_zip_bundle(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    admin_headers = _auth_headers(client, "admin@admin.com", "admin123")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for p in sorted(RAW_DIR.glob("*.csv")):
            archive.writestr(p.name, p.read_bytes())

    res = client.post(
        "/api/knowledge/csvs",
        headers=admin_headers,
        files=[("files", ("loja.zip", buf.getvalue(), "application/zip"))],
    )
    assert res.status_code == 200
    assert res.json()["report"]["products"] == 65


def test_store_info_and_sessions_crud(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    user_headers = _auth_headers(client, "user@user.com", "user123")

    store = client.get("/api/store")
    assert store.status_code == 200
    assert store.json()["phone_primary"] == "(67) 3341-4444"
    assert "hours" in store.json()

    created = client.post("/api/sessions", headers=user_headers, json={"title": "Takamine GD20"})
    assert created.status_code == 201
    sid = created.json()["session_id"]

    listed = client.get("/api/sessions", headers=user_headers).json()["sessions"]
    assert [s["session_id"] for s in listed] == [sid]

    detail = client.get(f"/api/sessions/{sid}", headers=user_headers)
    assert detail.status_code == 200
    assert detail.json()["messages"] == []

    assert client.delete(f"/api/sessions/{sid}", headers=user_headers).status_code == 204
    assert client.get(f"/api/sessions/{sid}", headers=user_headers).status_code == 404
