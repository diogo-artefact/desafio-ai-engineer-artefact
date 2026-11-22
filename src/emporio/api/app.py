from __future__ import annotations

import asyncio
import io
import json
import uuid
import zipfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any

import httpx
from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from google.genai import errors as genai_errors
from pdfplumber.utils.exceptions import PdfminerException
from pydantic import BaseModel, Field
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError, UnexpectedModelBehavior

from emporio.agent import (
    ALL_TOOL_IDS,
    ALLOWED_MODEL_IDS,
    AVAILABLE_MODELS,
    TOOL_REGISTRY,
    validate_custom_instructions_rules,
)
from emporio.api.container import AppContainer
from emporio.auth import (
    AuthenticatedUser,
    hash_password,
    issue_token,
    verify_password,
    verify_token,
)
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
                "Na web autenticada, cada conta consulta apenas seus próprios pedidos (com "
                "confirmação por telefone para e-mails compartilhados). Em canais sem login, "
                "como WhatsApp, a consulta exige número do pedido junto ao e-mail ou telefone."
            ),
        },
    ],
}


class LoginRequest(BaseModel):
    email: str = Field(min_length=3)
    password: str = Field(min_length=1)


class RegisterRequest(BaseModel):
    name: str = ""
    email: str = Field(min_length=3)
    password: str = Field(min_length=6)


class CreateSessionRequest(BaseModel):
    title: str = "Nova conversa"


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str = Field(min_length=1)
    enabled_tools: list[str] | None = None


class UpdateModelRequest(BaseModel):
    model_id: str = Field(min_length=1)


class UpdatePersonalizationRequest(BaseModel):
    custom_instructions: str = ""


def _sse_line(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


ADMIN_ONLY_TRACE_TOOLS: frozenset[str] = frozenset({"jev_guardrail"})


def _filter_trace_for_role(trace: list[dict[str, Any]], role: str) -> list[dict[str, Any]]:
    if role == "admin":
        return trace
    return [step for step in trace if step.get("tool_name") not in ADMIN_ONLY_TRACE_TOOLS]


def _filter_event_for_role(payload: dict[str, Any], role: str) -> dict[str, Any] | None:
    if role == "admin":
        return payload
    if (
        payload.get("type") in ("tool_start", "tool_end")
        and payload.get("tool_name") in ADMIN_ONLY_TRACE_TOOLS
    ):
        return None
    if payload.get("type") == "done" and isinstance(payload.get("trace"), list):
        return {**payload, "trace": _filter_trace_for_role(payload["trace"], role)}
    return payload


def _error_event_from(exc: Exception) -> dict[str, Any]:
    status_code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if isinstance(status_code, int) and status_code == 429:
        message = "Limite temporário da API do modelo atingido. Tente novamente em instantes."
    elif isinstance(status_code, int) and status_code >= 500:
        message = "O servidor passou por um pico temporário. Tente novamente em instantes."
    else:
        message = "Não foi possível concluir a consulta ao modelo agora. Tente novamente."
    return {
        "type": "error",
        "status_code": status_code if isinstance(status_code, int) else 503,
        "message": message,
        "detail": str(exc),
    }


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


def _is_valid_email(email: str) -> bool:
    clean = email.strip()
    if "@" not in clean or " " in clean:
        return False
    local, domain = clean.split("@", 1)
    return bool(local) and "." in domain and not domain.startswith(".") and not domain.endswith(".")


def require_user(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> AuthenticatedUser:
    deps: AppContainer = request.app.state.container
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Autenticação obrigatória.")
    token = authorization.removeprefix("Bearer ").strip()
    payload = verify_token(token, deps.settings.auth_secret)
    if payload is None or not isinstance(payload.get("sub"), str):
        raise HTTPException(status_code=401, detail="Sessão expirada ou inválida.")
    user = deps.repo.get_user_by_id(payload["sub"])
    if user is None:
        raise HTTPException(status_code=401, detail="Conta não encontrada.")
    return user


def require_admin(
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> AuthenticatedUser:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito a gestores.")
    return user


def create_app(container: AppContainer | None = None) -> FastAPI:
    deps = container or AppContainer.from_settings()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        async def _delivery_watcher() -> None:
            while True:
                try:
                    deps.repo.finalize_due_deliveries()
                except Exception:
                    pass
                await asyncio.sleep(10)

        watcher = asyncio.create_task(_delivery_watcher())
        try:
            yield
        finally:
            watcher.cancel()
            try:
                await watcher
            except asyncio.CancelledError:
                pass

    api = FastAPI(title="Empório da Música API", version="0.1.0", lifespan=lifespan)
    api.add_middleware(
        CORSMiddleware,
        allow_origins=deps.settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    api.state.container = deps

    @api.post("/api/auth/login")
    def login(body: LoginRequest) -> dict[str, Any]:
        found = deps.repo.get_user_with_hash_by_email(body.email)
        if found is None:
            raise HTTPException(status_code=401, detail="E-mail ou senha inválidos.")
        user, password_hash = found
        if not verify_password(body.password, password_hash):
            raise HTTPException(status_code=401, detail="E-mail ou senha inválidos.")
        token = issue_token(user, deps.settings.auth_secret)
        return {"token": token, "user": user.model_dump()}

    @api.post("/api/auth/register", status_code=201)
    def register(body: RegisterRequest) -> dict[str, Any]:
        if not _is_valid_email(body.email):
            raise HTTPException(status_code=400, detail="Informe um e-mail válido.")
        try:
            user = deps.repo.create_user(
                name=body.name,
                email=body.email,
                password_hash=hash_password(body.password),
                role="customer",
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        token = issue_token(user, deps.settings.auth_secret)
        return {"token": token, "user": user.model_dump()}

    @api.get("/api/auth/me")
    def me(user: Annotated[AuthenticatedUser, Depends(require_user)]) -> dict[str, Any]:
        return {"user": user.model_dump()}

    @api.get("/api/health")
    def health() -> dict[str, Any]:
        knowledge = deps.repo.get_knowledge_status()
        return {"status": "ok", "ready": knowledge.ready}

    @api.get("/api/store")
    def store_info() -> dict[str, Any]:
        return {
            **STORE_PROFILE,
            "hours": check_store_hours().model_dump(),
        }

    @api.get("/api/knowledge")
    def knowledge_status(
        _admin: Annotated[AuthenticatedUser, Depends(require_admin)],
    ) -> dict[str, Any]:
        status = deps.repo.get_knowledge_status()
        return {
            **status.model_dump(),
            "required_csv_tables": list(REQUIRED_CSV_TABLES),
        }

    @api.post("/api/knowledge/csvs")
    async def upload_csvs(
        files: Annotated[list[UploadFile], File()],
        _admin: Annotated[AuthenticatedUser, Depends(require_admin)],
    ) -> dict[str, Any]:
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
            seeded_customer_users = (
                deps.repo.sync_customer_seed_users(
                    lambda: hash_password(deps.settings.seed_user_password)
                )
                if deps.settings.seed_user_password
                else 0
            )
        except (ValueError, KeyError, UnicodeDecodeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return {
            "report": asdict(report),
            "seeded_customer_users": seeded_customer_users,
            "knowledge": deps.repo.get_knowledge_status().model_dump(),
        }

    @api.post("/api/knowledge/pdf")
    async def upload_pdf(
        file: Annotated[UploadFile, File()],
        _admin: Annotated[AuthenticatedUser, Depends(require_admin)],
    ) -> dict[str, Any]:
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
    def list_sessions(
        user: Annotated[AuthenticatedUser, Depends(require_user)],
    ) -> dict[str, Any]:
        return {"sessions": deps.repo.list_sessions(user_id=user.user_id)}

    @api.post("/api/sessions", status_code=201)
    def create_session(
        user: Annotated[AuthenticatedUser, Depends(require_user)],
        body: CreateSessionRequest | None = None,
    ) -> dict[str, Any]:
        session_id = uuid.uuid4().hex[:12]
        title = body.title.strip() if body and body.title.strip() else "Nova conversa"
        deps.repo.create_session(session_id, title, user_id=user.user_id)
        created = deps.repo.get_session(session_id, user_id=user.user_id)
        if created is None:
            raise HTTPException(status_code=500, detail="Erro ao criar conversa.")
        return created

    @api.get("/api/sessions/{session_id}")
    def get_session(
        session_id: str,
        user: Annotated[AuthenticatedUser, Depends(require_user)],
    ) -> dict[str, Any]:
        deps.repo.finalize_due_deliveries()
        match = deps.repo.get_session(session_id, user_id=user.user_id)
        if match is None:
            raise HTTPException(status_code=404, detail="Conversa não encontrada.")
        messages = [
            {**msg, "trace": _filter_trace_for_role(msg.get("trace", []), user.role)}
            for msg in deps.repo.get_messages(session_id)
        ]
        order_drafts = [
            draft.model_dump() for draft in deps.repo.list_session_order_drafts(session_id)
        ]
        return {
            "session": match,
            "messages": messages,
            "order_drafts": order_drafts,
        }

    @api.post("/api/orders/drafts/{draft_id}/confirm")
    def confirm_order_draft(
        draft_id: str,
        user: Annotated[AuthenticatedUser, Depends(require_user)],
    ) -> dict[str, Any]:
        deps.repo.finalize_due_deliveries()
        try:
            draft, message = deps.repo.confirm_order_draft(
                draft_id,
                user,
                auto_delivery_seconds=deps.settings.order_auto_delivery_seconds,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "draft": draft.model_dump(),
            "message": message,
        }

    @api.post("/api/orders/drafts/{draft_id}/cancel")
    def cancel_order_draft(
        draft_id: str,
        user: Annotated[AuthenticatedUser, Depends(require_user)],
    ) -> dict[str, Any]:
        try:
            draft = deps.repo.cancel_order_draft(draft_id, user.user_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"draft": draft.model_dump()}

    @api.delete("/api/sessions/{session_id}", status_code=204)
    def delete_session(
        session_id: str,
        user: Annotated[AuthenticatedUser, Depends(require_user)],
    ) -> Response:
        deps.repo.delete_session(session_id, user_id=user.user_id)
        return Response(status_code=204)

    @api.get("/api/memories")
    def list_memories(
        user: Annotated[AuthenticatedUser, Depends(require_user)],
    ) -> dict[str, Any]:
        return {
            "memories": [
                item.model_dump() for item in deps.repo.list_user_memories(user.user_id)
            ]
        }

    @api.delete("/api/memories/{fact_key}", status_code=204)
    def delete_memory(
        fact_key: str,
        user: Annotated[AuthenticatedUser, Depends(require_user)],
    ) -> Response:
        deps.repo.delete_user_memory(user.user_id, fact_key)
        return Response(status_code=204)

    @api.delete("/api/memories", status_code=204)
    def clear_memories(
        user: Annotated[AuthenticatedUser, Depends(require_user)],
    ) -> Response:
        deps.repo.clear_user_memories(user.user_id)
        return Response(status_code=204)

    @api.get("/api/personalization")
    def get_personalization(
        user: Annotated[AuthenticatedUser, Depends(require_user)],
    ) -> dict[str, Any]:
        pref = deps.repo.get_custom_instructions(user.user_id)
        return {
            **pref.model_dump(),
            "memories": [
                item.model_dump() for item in deps.repo.list_user_memories(user.user_id)
            ],
        }

    @api.put("/api/personalization")
    async def update_personalization(
        body: UpdatePersonalizationRequest,
        user: Annotated[AuthenticatedUser, Depends(require_user)],
    ) -> dict[str, Any]:
        clean = body.custom_instructions.strip()
        if clean:
            rule_error = validate_custom_instructions_rules(clean)
            if rule_error is not None:
                raise HTTPException(status_code=400, detail=rule_error)
            if deps.guardrail is not None:
                validation = await deps.guardrail.validate_instructions(clean)
                if not validation.allowed:
                    raise HTTPException(
                        status_code=400,
                        detail=validation.reason or "Instruções recusadas pelo guardrail.",
                    )
        saved = deps.repo.save_custom_instructions(user.user_id, clean)
        return {
            **saved.model_dump(),
            "memories": [
                item.model_dump() for item in deps.repo.list_user_memories(user.user_id)
            ],
        }

    @api.get("/api/tools")
    def list_tools(
        _admin: Annotated[AuthenticatedUser, Depends(require_admin)],
    ) -> dict[str, Any]:
        return {
            "tools": [
                {
                    "tool_id": meta.tool_id,
                    "label": meta.label,
                    "description": meta.description,
                }
                for meta in TOOL_REGISTRY
            ]
        }

    def _models_payload() -> dict[str, Any]:
        return {
            "active_model": deps.conversations.resolve_active_model(),
            "models": [
                {
                    "model_id": meta.model_id,
                    "label": meta.label,
                    "description": meta.description,
                }
                for meta in AVAILABLE_MODELS
            ],
        }

    @api.get("/api/models")
    def list_models(
        _admin: Annotated[AuthenticatedUser, Depends(require_admin)],
    ) -> dict[str, Any]:
        return _models_payload()

    @api.put("/api/models")
    def update_model(
        body: UpdateModelRequest,
        _admin: Annotated[AuthenticatedUser, Depends(require_admin)],
    ) -> dict[str, Any]:
        chosen = body.model_id.strip()
        if chosen not in ALLOWED_MODEL_IDS:
            raise HTTPException(
                status_code=400,
                detail="Modelo indisponível. Escolha um dos modelos Gemini 4.",
            )
        deps.repo.set_setting("active_model", chosen)
        return _models_payload()

    @api.post("/api/chat")
    async def chat_stream(
        body: ChatRequest,
        user: Annotated[AuthenticatedUser, Depends(require_user)],
    ) -> StreamingResponse:
        clean_message = body.message.strip()
        if not clean_message:
            raise HTTPException(status_code=422, detail="A mensagem não pode estar vazia.")

        if body.enabled_tools is not None:
            if user.role != "admin":
                raise HTTPException(
                    status_code=403,
                    detail="Apenas gestores podem alterar ferramentas ativas.",
                )
            unknown = sorted(set(body.enabled_tools) - ALL_TOOL_IDS)
            if unknown:
                raise HTTPException(
                    status_code=400,
                    detail="Ferramentas desconhecidas: " + ", ".join(unknown),
                )
            enabled = frozenset(body.enabled_tools)
        else:
            enabled = ALL_TOOL_IDS

        if user.role == "customer" and not deps.repo.get_knowledge_status().ready:
            raise HTTPException(
                status_code=503,
                detail="Nosso atendimento virtual não está disponível no momento.",
            )

        deps.repo.finalize_due_deliveries()
        requested_sid = (body.session_id or "").strip()
        if requested_sid:
            existing = deps.repo.get_session(requested_sid)
            if existing is not None and deps.repo.get_session(requested_sid, user.user_id) is None:
                raise HTTPException(status_code=404, detail="Conversa não encontrada.")
            session_id = requested_sid
        else:
            session_id = uuid.uuid4().hex[:12]

        async def event_generator() -> AsyncIterator[str]:
            yield _sse_line({"type": "session", "session_id": session_id})
            try:
                async for event in deps.conversations.stream_message(
                    session_id=session_id,
                    message=clean_message,
                    enabled_tools=enabled,
                    user_id=user.user_id,
                    user_role=user.role,
                    user_name=user.name,
                    user_email=user.email,
                ):
                    filtered = _filter_event_for_role(event.model_dump(), user.role)
                    if filtered is not None:
                        yield _sse_line(filtered)
            except (
                ModelHTTPError,
                ModelAPIError,
                UnexpectedModelBehavior,
                genai_errors.APIError,
                httpx.HTTPError,
                OSError,
            ) as exc:
                yield _sse_line(_error_event_from(exc))

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    return api
