from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from pydantic_ai import Agent, RunContext, ToolDefinition

from emporio.agent.events import ALL_TOOL_IDS
from emporio.auth import UserRole
from emporio.domain.rules import (
    build_order_pricing,
    calculate_shipping,
    check_store_hours,
    evaluate_return_eligibility,
    is_large_instrument,
    simulate_payment,
)
from emporio.domain.text import normalize_phone_digits
from emporio.ports import (
    CatalogRepository,
    KnowledgeRepository,
    OrderDraftRepository,
    OrderRepository,
    PolicyRetriever,
)

MAX_FAILED_ORDER_LOOKUPS_PER_SESSION = 5


@dataclass
class OrderSecurityState:
    failed_attempts: int = 0

    def is_locked(self) -> bool:
        return self.failed_attempts >= MAX_FAILED_ORDER_LOOKUPS_PER_SESSION

    def record_failure(self) -> int:
        self.failed_attempts += 1
        return self.failed_attempts


@dataclass(frozen=True)
class AgentDeps:
    catalog: CatalogRepository
    orders: OrderRepository
    policies: PolicyRetriever
    knowledge: KnowledgeRepository
    enabled_tools: frozenset[str] = field(default_factory=lambda: ALL_TOOL_IDS)
    user_role: UserRole = "customer"
    user_id: str | None = None
    user_name: str | None = None
    user_email: str | None = None
    session_id: str | None = None
    reference_time: datetime | None = None
    order_security: OrderSecurityState = field(default_factory=OrderSecurityState)
    drafts: OrderDraftRepository | None = None


def _prepare_if_enabled(tool_id: str):
    async def _prepare(
        ctx: RunContext[AgentDeps],
        tool_def: ToolDefinition,
    ) -> ToolDefinition | None:
        if tool_id not in ctx.deps.enabled_tools:
            return None
        return tool_def

    return _prepare


async def _prepare_lookup_order(
    ctx: RunContext[AgentDeps],
    tool_def: ToolDefinition,
) -> ToolDefinition | None:
    if "lookup_order" not in ctx.deps.enabled_tools:
        return None
    if ctx.deps.user_role == "customer" and ctx.deps.user_email:
        return replace(
            tool_def,
            description=(
                "Consulta pedidos da conta autenticada do cliente (order_id opcional; "
                "só informe contact com o telefone se solicitado para desambiguar e-mail "
                "duplicado)."
            ),
        )
    schema = dict(tool_def.parameters_json_schema)
    schema["required"] = ["order_id", "contact"]
    return replace(
        tool_def,
        description=(
            "Consulta pedido mediante verificação obrigatória em 2 fatores (order_id e "
            "contact com e-mail ou telefone cadastrado). Nunca chame sem ambos os dados."
        ),
        parameters_json_schema=schema,
    )


async def _prepare_order_draft_tool(
    ctx: RunContext[AgentDeps],
    tool_def: ToolDefinition,
) -> ToolDefinition | None:
    if (
        "prepare_order_draft" not in ctx.deps.enabled_tools
        or ctx.deps.drafts is None
        or not ctx.deps.user_id
        or not ctx.deps.session_id
    ):
        return None
    return tool_def


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

    @agent.tool(name="lookup_order", prepare=_prepare_lookup_order)
    def lookup_order(
        ctx: RunContext[AgentDeps],
        order_id: int | None = None,
        contact: str | None = None,
    ) -> dict[str, Any]:
        """Consulta pedidos do cliente autenticado ou verifica pedido por 2 fatores."""
        status = ctx.deps.knowledge.get_knowledge_status()
        if not status.csvs.loaded:
            return _missing_csvs_payload(ctx.deps.user_role)

        if ctx.deps.order_security.is_locked():
            return {
                "verified": False,
                "gateway": "rate_limit",
                "message": (
                    "Limite de tentativas de verificação de pedido atingido nesta conversa. "
                    "Para sua segurança, entre em contato com a nossa equipe pelo telefone "
                    "(67) 3341-4444 ou pelo e-mail contato@emporiodamusica.com.br."
                ),
            }

        ref_date = ctx.deps.reference_time.date() if ctx.deps.reference_time else None
        clean_contact = (contact or "").strip()
        auth_email = (
            ctx.deps.user_email.strip().lower()
            if ctx.deps.user_role == "customer" and ctx.deps.user_email
            else None
        )

        if auth_email is not None:
            customer_matches = ctx.deps.orders.count_customers_by_email(auth_email)

            if customer_matches == 0:
                ctx.deps.order_security.record_failure()
                return {
                    "verified": False,
                    "gateway": "ownership_mismatch",
                    "message": (
                        "Não encontramos pedidos vinculados à sua conta autenticada. Por "
                        "segurança (LGPD), cada conta pode consultar apenas seus próprios "
                        "pedidos."
                    ),
                }

            if customer_matches == 1:
                if order_id is not None:
                    order = ctx.deps.orders.verify_and_get_order(
                        order_id=order_id, contact=auth_email
                    )
                    if order is None:
                        ctx.deps.order_security.record_failure()
                        return {
                            "verified": False,
                            "gateway": "ownership_mismatch",
                            "message": (
                                "Este pedido não pertence à sua conta autenticada. Por "
                                "segurança (LGPD), só é possível consultar pedidos vinculados "
                                "ao seu próprio e-mail."
                            ),
                        }
                    if clean_contact and (
                        ctx.deps.orders.verify_and_get_order(
                            order_id=order_id, contact=clean_contact
                        )
                        is None
                    ):
                        ctx.deps.order_security.record_failure()
                        return {
                            "verified": False,
                            "gateway": "ownership_mismatch",
                            "message": (
                                "Os dados de contato informados não coincidem com o cadastro "
                                "deste pedido."
                            ),
                        }
                    return_check = evaluate_return_eligibility(order, reference_date=ref_date)
                    return {
                        "verified": True,
                        "gateway": "authenticated_owner",
                        "order": order.model_dump(),
                        "return_eligibility": return_check.model_dump(),
                    }

                my_orders = ctx.deps.orders.list_orders_for_email(auth_email)
                if not my_orders:
                    return {
                        "verified": True,
                        "gateway": "authenticated_owner",
                        "orders": [],
                        "message": "Não encontramos pedidos cadastrados para a sua conta.",
                    }
                enriched = [
                    {
                        "order": item.model_dump(),
                        "return_eligibility": evaluate_return_eligibility(
                            item, reference_date=ref_date
                        ).model_dump(),
                    }
                    for item in my_orders
                ]
                if len(enriched) == 1:
                    return {
                        "verified": True,
                        "gateway": "authenticated_owner",
                        "order": enriched[0]["order"],
                        "return_eligibility": enriched[0]["return_eligibility"],
                        "orders": enriched,
                    }
                return {
                    "verified": True,
                    "gateway": "authenticated_owner",
                    "orders": enriched,
                }

            phone_digits = (
                normalize_phone_digits(clean_contact)
                if clean_contact and "@" not in clean_contact
                else ""
            )
            if len(phone_digits) < 8:
                return {
                    "verified": False,
                    "gateway": "duplicate_email_step_up",
                    "message": (
                        "Encontramos mais de um cadastro associado a este e-mail. Para "
                        "proteger sua privacidade (LGPD), confirme o telefone cadastrado "
                        "para consultar seus pedidos."
                    ),
                }

            if not ctx.deps.orders.match_customer_email_and_phone(auth_email, clean_contact):
                ctx.deps.order_security.record_failure()
                return {
                    "verified": False,
                    "gateway": "ownership_mismatch",
                    "message": (
                        "O telefone informado não corresponde ao cadastro vinculado à sua "
                        "conta autenticada."
                    ),
                }

            matched_orders = ctx.deps.orders.list_orders_for_email_and_phone(
                auth_email, clean_contact
            )
            if order_id is not None:
                chosen = next((o for o in matched_orders if o.order_id == order_id), None)
                if chosen is None:
                    ctx.deps.order_security.record_failure()
                    return {
                        "verified": False,
                        "gateway": "ownership_mismatch",
                        "message": (
                            "Este pedido não pertence ao cadastro confirmado pelo seu e-mail "
                            "e telefone."
                        ),
                    }
                return_check = evaluate_return_eligibility(chosen, reference_date=ref_date)
                return {
                    "verified": True,
                    "gateway": "step_up_phone_verified",
                    "order": chosen.model_dump(),
                    "return_eligibility": return_check.model_dump(),
                }

            if not matched_orders:
                return {
                    "verified": True,
                    "gateway": "step_up_phone_verified",
                    "orders": [],
                    "message": "Não encontramos pedidos cadastrados para este telefone.",
                }
            enriched = [
                {
                    "order": item.model_dump(),
                    "return_eligibility": evaluate_return_eligibility(
                        item, reference_date=ref_date
                    ).model_dump(),
                }
                for item in matched_orders
            ]
            if len(enriched) == 1:
                return {
                    "verified": True,
                    "gateway": "step_up_phone_verified",
                    "order": enriched[0]["order"],
                    "return_eligibility": enriched[0]["return_eligibility"],
                    "orders": enriched,
                }
            return {
                "verified": True,
                "gateway": "step_up_phone_verified",
                "orders": enriched,
            }

        if order_id is None or not clean_contact:
            ctx.deps.order_security.record_failure()
            return {
                "verified": False,
                "gateway": "missing_2fa",
                "message": (
                    "Para consultar um pedido, informe o número do pedido junto ao e-mail ou "
                    "telefone cadastrado."
                ),
            }

        order = ctx.deps.orders.verify_and_get_order(order_id=order_id, contact=clean_contact)
        if order is None:
            ctx.deps.order_security.record_failure()
            return {
                "verified": False,
                "gateway": "invalid_2fa",
                "message": (
                    "Não foi possível confirmar a titularidade deste pedido com os dados "
                    "informados. Confira o número do pedido e o e-mail ou telefone cadastrado."
                ),
            }

        return_check = evaluate_return_eligibility(order, reference_date=ref_date)
        return {
            "verified": True,
            "gateway": "verified_2fa",
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

    @agent.tool(name="prepare_order_draft", prepare=_prepare_order_draft_tool)
    def prepare_order_draft(
        ctx: RunContext[AgentDeps],
        product_id_or_name: str,
        quantity: int = 1,
        payment_method: str = "pix",
        city: str | None = None,
    ) -> dict[str, Any]:
        """Monta um rascunho de pedido validado para o cliente confirmar no card do chat."""
        status = ctx.deps.knowledge.get_knowledge_status()
        if not status.csvs.loaded:
            return _missing_csvs_payload(ctx.deps.user_role)

        if ctx.deps.drafts is None or not ctx.deps.user_id or not ctx.deps.session_id:
            return {
                "created": False,
                "error": "auth_required",
                "message": "É necessário estar autenticado em uma conversa para montar um pedido.",
            }

        detail = ctx.deps.catalog.get_product_detail(product_id_or_name)
        if detail is None:
            return {
                "created": False,
                "error": "product_not_found",
                "message": f"Produto '{product_id_or_name}' não encontrado no catálogo da loja.",
            }

        if not detail.is_sellable or detail.stock_quantity < quantity:
            alternatives = [
                alt.model_dump()
                for alt in ctx.deps.catalog.find_alternatives(detail.product_id, limit=3)
            ]
            return {
                "created": False,
                "error": "unavailable",
                "product_name": detail.name,
                "status": detail.status,
                "stock_quantity": detail.stock_quantity,
                "alternatives_in_stock": alternatives,
                "message": (
                    f"Não é possível pedir {quantity} unidade(s) de {detail.name} "
                    f"(status: {detail.status}, estoque atual: {detail.stock_quantity})."
                ),
            }

        resolved_city = (
            (city or "").strip()
            or (
                ctx.deps.orders.get_customer_city_by_email(ctx.deps.user_email)
                if ctx.deps.user_email
                else None
            )
            or "Campo Grande"
        )
        discount = detail.active_promotion.discount_percent if detail.active_promotion else 0.0
        large = is_large_instrument(detail.category_name, detail.name)
        try:
            pricing = build_order_pricing(
                list_price_brl=detail.price_brl,
                quantity=quantity,
                active_discount_percent=discount,
                payment_method_raw=payment_method,
                city=resolved_city,
                large_instrument=large,
            )
        except ValueError as exc:
            return {
                "created": False,
                "error": "invalid_order_params",
                "message": str(exc),
            }

        draft = ctx.deps.drafts.create_order_draft(
            session_id=ctx.deps.session_id,
            user_id=ctx.deps.user_id,
            product_id=detail.product_id,
            product_name=detail.name,
            quantity=quantity,
            unit_price_brl=pricing.unit_price_brl,
            discount_percent=pricing.discount_percent,
            subtotal_brl=pricing.subtotal_brl,
            shipping_brl=pricing.shipping_brl,
            shipping_note=pricing.shipping_note,
            total_brl=pricing.total_brl,
            payment_method=pricing.payment_method,
            payment_label=pricing.payment_label,
            city=pricing.city,
        )
        return {
            "created": True,
            "draft": draft.model_dump(),
            "message": (
                "Card de confirmação gerado e exibido ao cliente. Oriente o cliente a revisar "
                "os valores e clicar em Confirmar pedido no card para finalizar a compra."
            ),
        }
