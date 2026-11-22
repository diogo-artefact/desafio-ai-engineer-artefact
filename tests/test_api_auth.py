from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from pydantic_ai.models.function import FunctionModel

from emporio.api import AppContainer, create_app
from emporio.etl.loader import ingest_store_csvs

RAW_DIR = Path("data/raw")


def _make_client(tmp_path: Path) -> TestClient:
    async def noop_stream(messages, info):
        yield "ok"

    container = AppContainer.build(
        db_path=tmp_path / "auth.db",
        embedder=None,
        model=FunctionModel(stream_function=noop_stream),
    )
    return TestClient(create_app(container))


def test_seeded_accounts_login_and_signup_flow(tmp_path: Path) -> None:
    client = _make_client(tmp_path)

    bad_login = client.post(
        "/api/auth/login",
        json={"email": "admin@admin.com", "password": "wrong"},
    )
    assert bad_login.status_code == 401

    admin_res = client.post(
        "/api/auth/login",
        json={"email": "admin@admin.com", "password": "admin123"},
    )
    assert admin_res.status_code == 200
    assert admin_res.json()["user"]["role"] == "admin"

    user_res = client.post(
        "/api/auth/login",
        json={"email": "user@user.com", "password": "user123"},
    )
    assert user_res.status_code == 200
    assert user_res.json()["user"]["role"] == "customer"

    signup = client.post(
        "/api/auth/register",
        json={"name": "Ana", "email": "ana@exemplo.com", "password": "secret123"},
    )
    assert signup.status_code == 201
    assert signup.json()["user"]["role"] == "customer"
    token = signup.json()["token"]

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "ana@exemplo.com"

    dup = client.post(
        "/api/auth/register",
        json={"name": "Ana 2", "email": "ANA@EXEMPLO.COM", "password": "secret123"},
    )
    assert dup.status_code == 409


def test_role_guards_and_per_user_session_isolation(tmp_path: Path) -> None:
    client = _make_client(tmp_path)

    assert client.get("/api/sessions").status_code == 401
    assert client.get("/api/knowledge").status_code == 401
    assert client.get("/api/tools").status_code == 401

    user_token = client.post(
        "/api/auth/login",
        json={"email": "user@user.com", "password": "user123"},
    ).json()["token"]
    user_headers = {"Authorization": f"Bearer {user_token}"}

    assert client.get("/api/knowledge", headers=user_headers).status_code == 403
    assert client.get("/api/tools", headers=user_headers).status_code == 403
    assert (
        client.post(
            "/api/chat",
            headers=user_headers,
            json={"message": "Oi", "enabled_tools": ["search_catalog"]},
        ).status_code
        == 403
    )
    assert (
        client.post("/api/chat", headers=user_headers, json={"message": "Oi"}).status_code == 503
    )

    s_user = client.post("/api/sessions", headers=user_headers, json={"title": "Privada"}).json()
    sid = s_user["session_id"]

    other_token = client.post(
        "/api/auth/register",
        json={"name": "Outro", "email": "outro@exemplo.com", "password": "secret123"},
    ).json()["token"]
    other_headers = {"Authorization": f"Bearer {other_token}"}

    assert client.get("/api/sessions", headers=other_headers).json()["sessions"] == []
    assert client.get(f"/api/sessions/{sid}", headers=other_headers).status_code == 404


def test_admin_gemini4_model_selection_and_guard(tmp_path: Path) -> None:
    client = _make_client(tmp_path)

    user_token = client.post(
        "/api/auth/login",
        json={"email": "user@user.com", "password": "user123"},
    ).json()["token"]
    user_headers = {"Authorization": f"Bearer {user_token}"}
    assert client.get("/api/models", headers=user_headers).status_code == 403
    assert (
        client.put(
            "/api/models",
            headers=user_headers,
            json={"model_id": "google:gemini-4-neon"},
        ).status_code
        == 403
    )

    admin_token = client.post(
        "/api/auth/login",
        json={"email": "admin@admin.com", "password": "admin123"},
    ).json()["token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    initial = client.get("/api/models", headers=admin_headers)
    assert initial.status_code == 200
    payload = initial.json()
    model_ids = [item["model_id"] for item in payload["models"]]
    assert model_ids == [
        "google:gemini-4-hydrogen",
        "google:gemini-4-neon",
        "google:gemini-4-carbon",
        "google:gemini-4-argon",
    ]
    assert payload["active_model"] == "google:gemini-4-hydrogen"

    rejected = client.put(
        "/api/models",
        headers=admin_headers,
        json={"model_id": "google:gemini-2.5-flash"},
    )
    assert rejected.status_code == 400

    updated = client.put(
        "/api/models",
        headers=admin_headers,
        json={"model_id": "google:gemini-4-neon"},
    )
    assert updated.status_code == 200
    assert updated.json()["active_model"] == "google:gemini-4-neon"
    assert client.get("/api/models", headers=admin_headers).json()["active_model"] == (
        "google:gemini-4-neon"
    )


def test_csv_upload_and_startup_seed_all_unique_customers(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    admin_token = client.post(
        "/api/auth/login",
        json={"email": "admin@admin.com", "password": "admin123"},
    ).json()["token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    custom_signup = client.post(
        "/api/auth/register",
        json={
            "name": "Lucas Custom",
            "email": "lucas.mendes@jmail.com",
            "password": "minha-senha-custom",
        },
    )
    assert custom_signup.status_code == 201

    csv_files = [
        ("files", (p.name, p.read_bytes(), "text/csv")) for p in sorted(RAW_DIR.glob("*.csv"))
    ]
    first_upload = client.post("/api/knowledge/csvs", headers=admin_headers, files=csv_files)
    assert first_upload.status_code == 200
    assert first_upload.json()["seeded_customer_users"] == 48

    leticia_login = client.post(
        "/api/auth/login",
        json={"email": "leticia.rocha@jmail.com", "password": "user123"},
    )
    assert leticia_login.status_code == 200
    assert leticia_login.json()["user"]["name"] == "Letícia Gonçalves Rocha"
    assert leticia_login.json()["user"]["role"] == "customer"

    bruno_login = client.post(
        "/api/auth/login",
        json={"email": "bruno.martins@jmail.com", "password": "user123"},
    )
    assert bruno_login.status_code == 200
    assert bruno_login.json()["user"]["name"] == "Bruno Carvalho Martins"

    preserved_custom = client.post(
        "/api/auth/login",
        json={"email": "lucas.mendes@jmail.com", "password": "minha-senha-custom"},
    )
    assert preserved_custom.status_code == 200
    assert preserved_custom.json()["user"]["name"] == "Lucas Custom"

    second_upload = client.post("/api/knowledge/csvs", headers=admin_headers, files=csv_files)
    assert second_upload.status_code == 200
    assert second_upload.json()["seeded_customer_users"] == 0

    preloaded_db = tmp_path / "preloaded.db"
    raw_map = {p.name: p.read_bytes() for p in sorted(RAW_DIR.glob("*.csv"))}
    ingest_store_csvs(raw_map, db_path=preloaded_db)

    async def noop_stream(messages, info):
        yield "ok"

    booted = AppContainer.build(
        db_path=preloaded_db,
        embedder=None,
        model=FunctionModel(stream_function=noop_stream),
    )
    booted_client = TestClient(create_app(booted))
    pedro_login = booted_client.post(
        "/api/auth/login",
        json={"email": "pedro.oliveira@jmail.com", "password": "user123"},
    )
    assert pedro_login.status_code == 200
    assert pedro_login.json()["user"]["name"] == "Pedro Henrique Oliveira"
