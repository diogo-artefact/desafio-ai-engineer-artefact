from __future__ import annotations

import io
import uuid
import zipfile
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, File, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pdfplumber.utils.exceptions import PdfminerException
from pydantic import BaseModel

from emporio.api.container import AppContainer
from emporio.domain.rules import check_store_hours
from emporio.etl.loader import REQUIRED_CSV_TABLES, ingest_policy_pdf, ingest_store_csvs

STORE_PROFILE: dict[str, Any] = {
    "name": "Empório da Música",
    "legal_name": "Empório da Música Instrumentos Musicais Ltda.",
    "cnpj": "12.345.678/0001-90",
    "founded": 2008,
    "address": "Rua 14 de Maio, 3200 — Centro, Campo Grande - MS, CEP 79202-333",
    "phone_primary": "(67) 3341-4444",
    "phone_whatsapp_manual": "(67) 3321-4500",
    "email": "contato@emporiodamusica.com.br",
    "scope_note": (
        "Loja exclusiva de instrumentos musicais. Não trabalhamos com acessórios como "
        "cordas avulsas, palhetas, cabos, cases, pedais ou amplificadores."
    ),
    "policies_highlights": [
        {
            "title": "Pagamento",
            "detail": (
                "PIX com 5% de desconto sobre o preço de tabela (não acumula com promoções). "
                "Cartão em até 12x sem juros (mínimo R$ 50 até 3x, R$ 80 de 4x a 6x, "
                "R$ 100 de 7x a 12x). Combinação de formas acima de R$ 2.000,00."
            ),
        },
        {
            "title": "Entregas",
            "detail": (
                "Região metropolitana de Campo Grande: grátis acima de R$ 500,00 ou taxa fixa "
                "de R$ 35,00 (1 a 3 dias úteis por motoboy próprio). Outras cidades via "
                "Correios (PAC/SEDEX) ou Jadlog com seguro."
            ),
        },
        {
            "title": "Trocas e devoluções",
            "detail": (
                "Arrependimento em compras online em até 7 dias corridos após o recebimento "
                "(frete reverso por conta da loja, reembolso em até 10 dias úteis). Defeito "
                "de fabricação em até 30 dias na loja e garantia legal de 90 dias."
            ),
        },
        {
            "title": "Privacidade (LGPD)",
            "detail": (
                "Consultas de pedidos exigem confirmação do número do pedido junto ao e-mail "
                "ou telefone cadastrado."
            ),
        },
    ],
}


class CreateSessionRequest(BaseModel):
    title: str = "Nova conversa"


def _unpack_csv_uploads(raw_files: list[tuple[str, bytes]]) -> dict[str, bytes]:
    extracted: dict[str, bytes] = {}
    for filename, payload in raw_files:
        lower = filename.lower()
        if lower.endswith(".zip"):
            try:
                with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                    for member in archive.infolist():
                        if member.is_dir() or not member.filename.lower().endswith(".csv"):
                            continue
                        extracted[Path(member.filename).name] = archive.read(member)
            except zipfile.BadZipFile as exc:
                raise ValueError("Arquivo .zip inválido.") from exc
        elif lower.endswith(".csv"):
            extracted[Path(filename).name] = payload
    return extracted


def create_app(container: AppContainer | None = None) -> FastAPI:
    deps = container or AppContainer.from_settings()
    api = FastAPI(title="Empório da Música API", version="0.1.0")
    api.add_middleware(
        CORSMiddleware,
        allow_origins=deps.settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    api.state.container = deps

    @api.get("/api/health")
    def health() -> dict[str, Any]:
        knowledge = deps.repo.get_knowledge_status()
        return {
            "status": "ok",
            "ready": knowledge.ready,
            "knowledge": knowledge.model_dump(),
        }

    @api.get("/api/store")
    def store_info() -> dict[str, Any]:
        return {
            **STORE_PROFILE,
            "hours": check_store_hours().model_dump(),
        }

    @api.get("/api/knowledge")
    def knowledge_status() -> dict[str, Any]:
        status = deps.repo.get_knowledge_status()
        return {
            **status.model_dump(),
            "required_csv_tables": list(REQUIRED_CSV_TABLES),
        }

    @api.post("/api/knowledge/csvs")
    async def upload_csvs(files: Annotated[list[UploadFile], File()]) -> dict[str, Any]:
        raw_uploads: list[tuple[str, bytes]] = []
        for upload in files:
            name = upload.filename or ""
            raw_uploads.append((name, await upload.read()))

        try:
            csv_map = _unpack_csv_uploads(raw_uploads)
            if not csv_map:
                raise ValueError(
                    "Envie os 6 arquivos CSV operacionais ou um .zip contendo os CSVs."
                )
            report = ingest_store_csvs(csv_map, db_path=deps.db_path)
        except (ValueError, KeyError, UnicodeDecodeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return {
            "report": asdict(report),
            "knowledge": deps.repo.get_knowledge_status().model_dump(),
        }

    @api.post("/api/knowledge/pdf")
    async def upload_pdf(file: Annotated[UploadFile, File()]) -> dict[str, Any]:
        filename = file.filename or "políticas_da_loja.pdf"
        if not filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Envie um arquivo no formato PDF.")

        payload = await file.read()
        try:
            report = ingest_policy_pdf(
                payload,
                db_path=deps.db_path,
                filename=filename,
                embedder=deps.embedder,
            )
        except (ValueError, OSError, PdfminerException) as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Não foi possível processar o PDF enviado: {exc}",
            ) from exc

        return {
            "report": asdict(report),
            "knowledge": deps.repo.get_knowledge_status().model_dump(),
        }

    @api.get("/api/sessions")
    def list_sessions() -> dict[str, Any]:
        return {"sessions": deps.repo.list_sessions()}

    @api.post("/api/sessions", status_code=201)
    def create_session(body: CreateSessionRequest | None = None) -> dict[str, Any]:
        session_id = uuid.uuid4().hex[:12]
        title = (body.title.strip() if body and body.title.strip() else "Nova conversa")
        deps.repo.create_session(session_id, title)
        sessions = deps.repo.list_sessions()
        created = next(s for s in sessions if s["session_id"] == session_id)
        return created

    @api.get("/api/sessions/{session_id}")
    def get_session(session_id: str) -> dict[str, Any]:
        sessions = deps.repo.list_sessions()
        match = next((s for s in sessions if s["session_id"] == session_id), None)
        if match is None:
            raise HTTPException(status_code=404, detail="Conversa não encontrada.")
        return {
            "session": match,
            "messages": deps.repo.get_messages(session_id),
        }

    @api.delete("/api/sessions/{session_id}", status_code=204)
    def delete_session(session_id: str) -> Response:
        deps.repo.delete_session(session_id)
        return Response(status_code=204)

    return api
