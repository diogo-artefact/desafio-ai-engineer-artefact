from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic_ai import Agent, RunContext, ToolDefinition

from emporio.agent.events import ALL_TOOL_IDS
from emporio.auth import UserRole
from emporio.domain.rules import (
    calculate_shipping,
    check_store_hours,
    evaluate_return_eligibility,
    is_large_instrument,
    simulate_payment,
)
from emporio.ports import (
    CatalogRepository,
    KnowledgeRepository,
    OrderRepository,
    PolicyRetriever,
)


@dataclass(frozen=True)
class AgentDeps:
    catalog: CatalogRepository
    orders: OrderRepository
    policies: PolicyRetriever
    knowledge: KnowledgeRepository
    enabled_tools: frozenset[str] = field(default_factory=lambda: ALL_TOOL_IDS)
    user_role: UserRole = "customer"
    reference_time: datetime | None = None


def _prepare_if_enabled(tool_id: str):
    async def _prepare(
        ctx: RunContext[AgentDeps],
        tool_def: ToolDefinition,
    ) -> ToolDefinition | None:
        if tool_id not in ctx.deps.enabled_tools:
            return None
        return tool_def

    return _prepare


def _missing_csvs_payload(user_role: UserRole) -> dict[str, Any]:
    if user_role == "admin":
        return {
            "error": "base_not_loaded",
            "missing": "store_csvs",
            "message": (
                "A base operacional da loja (CSVs) ainda não foi carregada. "
                "Envie os arquivos CSV em Ajustes > Base de dados."
            ),
        }
    return {
        "error": "base_not_loaded",
        "message": (
            "Esta consulta está temporariamente indisponível. Informe apenas que não é "
            "possível verificar essa informação agora e oriente contato com a equipe pelo "
            "telefone (67) 3341-4444 ou pelo e-mail contato@emporiodamusica.com.br."
        ),
    }


def _missing_pdf_payload(user_role: UserRole) -> dict[str, Any]:
    if user_role == "admin":
        return {
            "error": "base_not_loaded",
            "missing": "policy_pdf",
            "message": (
                "O manual de políticas (PDF) ainda não foi carregado. "
                "Envie o PDF em Ajustes > Base de dados."
            ),
        }
    return {
        "error": "base_not_loaded",
        "message": (
            "Esta consulta está temporariamente indisponível. Informe apenas que não é "
            "possível verificar essa informação agora e oriente contato com a equipe pelo "
            "telefone (67) 3341-4444 ou pelo e-mail contato@emporiodamusica.com.br."
        ),
    }


def register_tools(agent: Agent[AgentDeps, str]) -> None:
    @agent.tool(name="search_catalog", prepare=_prepare_if_enabled("search_catalog"))
    def search_catalog(
        ctx: RunContext[AgentDeps],
        query: str | None = None,
        category: str | None = None,
        max_price: float | None = None,
        min_price: float | None = None,
        only_available: bool = True,
        only_promotions: bool = False,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Busca instrumentos no catálogo com filtros de categoria, preço, estoque e promoções."""
        status = ctx.deps.knowledge.get_knowledge_status()
        if not status.csvs.loaded:
            return _missing_csvs_payload(ctx.deps.user_role)

        items = ctx.deps.catalog.search_products(
            query=query,
            category=category,
            max_price=max_price,
            min_price=min_price,
            only_available=only_available,
            only_promotions=only_promotions,
            limit=max(1, min(limit, 20)),
        )
        return {
            "count": len(items),
            "categories": ctx.deps.catalog.list_categories(),
            "products": [item.model_dump() for item in items],
        }

    @agent.tool(name="get_product_details", prepare=_prepare_if_enabled("get_product_details"))
    def get_product_details(
        ctx: RunContext[AgentDeps],
        product_id_or_name: str,
    ) -> dict[str, Any]:
        """Retorna ficha completa, estoque, promoções ativas/vencidas, simulação e alternativas."""
        status = ctx.deps.knowledge.get_knowledge_status()
        if not status.csvs.loaded:
            return _missing_csvs_payload(ctx.deps.user_role)

        detail = ctx.deps.catalog.get_product_detail(product_id_or_name)
        if detail is None:
            return {
                "found": False,
                "query": product_id_or_name,
                "message": "Produto não encontrado no catálogo da loja.",
            }

        discount = detail.active_promotion.discount_percent if detail.active_promotion else 0.0
        payment = simulate_payment(detail.price_brl, active_discount_percent=discount)
        alternatives = (
            []
            if detail.is_sellable
            else [
                alt.model_dump()
                for alt in ctx.deps.catalog.find_alternatives(detail.product_id, limit=3)
            ]
        )
        return {
            "found": True,
            "product": detail.model_dump(),
            "payment": payment.model_dump(),
            "alternatives_in_stock": alternatives,
        }

    @agent.tool(
        name="simulate_payment_and_shipping",
        prepare=_prepare_if_enabled("simulate_payment_and_shipping"),
    )
    def simulate_payment_and_shipping(
        ctx: RunContext[AgentDeps],
        product_id_or_name: str | None = None,
        price_brl: float | None = None,
        city: str = "Campo Grande",
    ) -> dict[str, Any]:
        """Calcula PIX (5% se não promocional), parcelas sem juros, combinação e frete."""
        discount = 0.0
        large = False
        resolved_name: str | None = None

        if product_id_or_name:
            status = ctx.deps.knowledge.get_knowledge_status()
            if not status.csvs.loaded:
                return _missing_csvs_payload(ctx.deps.user_role)
            detail = ctx.deps.catalog.get_product_detail(product_id_or_name)
            if detail is None:
                return {
                    "found": False,
                    "message": f"Produto '{product_id_or_name}' não encontrado.",
                }
            price_brl = detail.price_brl
            resolved_name = detail.name
            discount = detail.active_promotion.discount_percent if detail.active_promotion else 0.0
            large = is_large_instrument(detail.category_name, detail.name)

        if price_brl is None or price_brl <= 0:
            return {"error": "Informe o produto ou um valor positivo em reais para simular."}

        payment = simulate_payment(price_brl, active_discount_percent=discount)
        shipping = calculate_shipping(city, payment.effective_price_brl, large_instrument=large)
        return {
            "product_name": resolved_name,
            "payment": payment.model_dump(),
            "shipping": shipping.model_dump(),
        }

    @agent.tool(name="lookup_order", prepare=_prepare_if_enabled("lookup_order"))
    def lookup_order(
        ctx: RunContext[AgentDeps],
        order_id: int,
        contact: str,
    ) -> dict[str, Any]:
        """Consulta pedido mediante verificação em 2 fatores (order_id + e-mail ou telefone)."""
        status = ctx.deps.knowledge.get_knowledge_status()
        if not status.csvs.loaded:
            return _missing_csvs_payload(ctx.deps.user_role)

        order = ctx.deps.orders.verify_and_get_order(order_id=order_id, contact=contact)
        if order is None:
            return {
                "verified": False,
                "message": (
                    "Não foi possível confirmar a titularidade deste pedido com os dados "
                    "informados. Confira o número do pedido e o e-mail ou telefone cadastrado."
                ),
            }

        ref_date = ctx.deps.reference_time.date() if ctx.deps.reference_time else None
        return_check = evaluate_return_eligibility(order, reference_date=ref_date)
        return {
            "verified": True,
            "order": order.model_dump(),
            "return_eligibility": return_check.model_dump(),
        }

    @agent.tool(name="search_store_policies", prepare=_prepare_if_enabled("search_store_policies"))
    def search_store_policies(
        ctx: RunContext[AgentDeps],
        query: str,
        section_number: str | None = None,
    ) -> dict[str, Any]:
        """Consulta o manual de políticas por busca vetorial ou número da seção, mais expediente."""
        status = ctx.deps.knowledge.get_knowledge_status()
        if not status.pdf.loaded:
            return _missing_pdf_payload(ctx.deps.user_role)

        if section_number:
            hits = ctx.deps.policies.get_policy_section(section_number)
        else:
            hits = ctx.deps.policies.search_policies(query, limit=4)

        hours = check_store_hours(ctx.deps.reference_time)
        return {
            "store_hours_now": hours.model_dump(),
            "chunks": [h.model_dump() for h in hits],
        }
