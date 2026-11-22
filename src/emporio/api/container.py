from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic_ai.models import Model

from emporio.agent import (
    ConversationService,
    SupportAgent,
    get_default_compactor,
    get_default_guardrail,
    get_default_memory_extractor,
    get_default_title_generator,
)
from emporio.auth import hash_password
from emporio.config import Settings, get_settings
from emporio.db import SQLiteStoreRepository
from emporio.etl.embeddings import Embedder, get_default_embedder
from emporio.ports import (
    ConversationCompactor,
    InputGuardrail,
    TitleGenerator,
    UserMemoryExtractor,
)


@dataclass(frozen=True)
class AppContainer:
    settings: Settings
    db_path: Path
    embedder: Embedder | None
    repo: SQLiteStoreRepository
    agent: SupportAgent
    conversations: ConversationService
    guardrail: InputGuardrail | None = None

    @classmethod
    def build(
        cls,
        *,
        db_path: Path | str,
        embedder: Embedder | None = None,
        model: str | Model | None = None,
        settings: Settings | None = None,
        guardrail: InputGuardrail | None = None,
        title_generator: TitleGenerator | None = None,
        compactor: ConversationCompactor | None = None,
        memory_extractor: UserMemoryExtractor | None = None,
    ) -> AppContainer:
        resolved_settings = settings or get_settings()
        resolved_db = Path(db_path)
        repo = SQLiteStoreRepository(resolved_db, embedder=embedder)
        if resolved_settings.seed_admin_email and resolved_settings.seed_admin_password:
            repo.ensure_seed_user(
                name="Gestor",
                email=resolved_settings.seed_admin_email,
                password_hash=hash_password(resolved_settings.seed_admin_password),
                role="admin",
            )
        if resolved_settings.seed_user_email and resolved_settings.seed_user_password:
            repo.ensure_seed_user(
                name="Cliente",
                email=resolved_settings.seed_user_email,
                password_hash=hash_password(resolved_settings.seed_user_password),
                role="customer",
            )
        agent = SupportAgent(model=model if model is not None else resolved_settings.llm_model)
        conversations = ConversationService(
            agent=agent,
            catalog=repo,
            orders=repo,
            policies=repo,
            knowledge=repo,
            sessions=repo,
            settings_repo=repo,
            default_model=resolved_settings.llm_model,
            guardrail=guardrail,
            title_generator=title_generator,
            compaction_repo=repo,
            memory_repo=repo,
            personalization_repo=repo,
            compactor=compactor,
            memory_extractor=memory_extractor,
        )
        return cls(
            settings=resolved_settings,
            db_path=resolved_db,
            embedder=embedder,
            repo=repo,
            agent=agent,
            conversations=conversations,
            guardrail=guardrail,
        )

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> AppContainer:
        resolved = settings or get_settings()
        return cls.build(
            db_path=resolved.database_path,
            embedder=get_default_embedder(),
            model=resolved.llm_model,
            settings=resolved,
            guardrail=get_default_guardrail(resolved),
            title_generator=get_default_title_generator(resolved),
            compactor=get_default_compactor(resolved),
            memory_extractor=get_default_memory_extractor(resolved),
        )
