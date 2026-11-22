from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from emporio.domain.models import (
    InstallmentOption,
    OrderInfo,
    OrderPricing,
    PaymentSimulation,
    ReturnEligibility,
    ShippingQuote,
    StoreHoursStatus,
)
from emporio.domain.text import normalize_text

STORE_TZ = ZoneInfo("America/Campo_Grande")
PIX_DISCOUNT_RATE = 0.05
COMBINED_PAYMENT_THRESHOLD_BRL = 2000.0
CAMPO_GRANDE_FREE_SHIPPING_THRESHOLD_BRL = 500.0
CAMPO_GRANDE_FIXED_SHIPPING_BRL = 35.0
RETURN_WINDOW_DAYS = 7

INSTALLMENT_MINIMUM_BY_TIER: tuple[tuple[int, float], ...] = (
    (3, 50.0),
    (6, 80.0),
    (12, 100.0),
)

WEEKDAYS_PT: tuple[str, ...] = (
    "segunda-feira",
    "terça-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sábado",
    "domingo",
)

LARGE_INSTRUMENT_KEYWORDS: tuple[str, ...] = (
    "bateria acustica",
    "piano digital",
    "contrabaixo",
)

CAMPO_GRANDE_METRO_CITIES: frozenset[str] = frozenset(
    {
        "campo grande",
        "campo grande ms",
        "campo grande - ms",
        "campo grande/ms",
        "terenos",
        "sidrolandia",
        "jaraguari",
        "ribas do rio pardo",
        "bandeirantes",
        "rochedo",
        "corguinho",
    }
)


def _minimum_installment_for(count: int) -> float:
    for max_count, minimum in INSTALLMENT_MINIMUM_BY_TIER:
        if count <= max_count:
            return minimum
    return 100.0


def simulate_payment(
    list_price_brl: float,
    active_discount_percent: float = 0.0,
) -> PaymentSimulation:
    if list_price_brl <= 0:
        raise ValueError("Preço do produto deve ser positivo.")
    if active_discount_percent < 0 or active_discount_percent >= 100:
        raise ValueError("Desconto promocional deve estar entre 0 e 100.")

    effective_price = round(list_price_brl * (1.0 - active_discount_percent / 100.0), 2)
    pix_discount_applied = active_discount_percent == 0.0
    if pix_discount_applied:
        pix_price = round(effective_price * (1.0 - PIX_DISCOUNT_RATE), 2)
        pix_note = "5% de desconto à vista sobre o preço de tabela."
    else:
        pix_price = effective_price
        pix_note = (
            "Promoções não são cumulativas: o desconto de 5% no PIX não se aplica sobre "
            f"o preço promocional de {active_discount_percent:g}%."
        )

    options: list[InstallmentOption] = [
        InstallmentOption(
            installments=1,
            installment_value_brl=effective_price,
            total_brl=effective_price,
        )
    ]
    for count in range(2, 13):
        installment_value = round(effective_price / count, 2)
        if installment_value >= _minimum_installment_for(count):
            options.append(
                InstallmentOption(
                    installments=count,
                    installment_value_brl=installment_value,
                    total_brl=effective_price,
                )
            )

    return PaymentSimulation(
        list_price_brl=round(list_price_brl, 2),
        active_discount_percent=active_discount_percent,
        effective_price_brl=effective_price,
        pix_price_brl=pix_price,
        pix_discount_applied=pix_discount_applied,
        pix_note=pix_note,
        max_installments=options[-1].installments,
        installment_options=options,
        allows_combined_payment=effective_price > COMBINED_PAYMENT_THRESHOLD_BRL,
    )


def is_large_instrument(category_name: str, product_name: str) -> bool:
    haystack = normalize_text(f"{category_name} {product_name}")
    return any(keyword in haystack for keyword in LARGE_INSTRUMENT_KEYWORDS)


def calculate_shipping(
    city: str,
    order_total_brl: float,
    large_instrument: bool = False,
) -> ShippingQuote:
    normalized_city = normalize_text(city)
    is_metro = normalized_city in CAMPO_GRANDE_METRO_CITIES or normalized_city.startswith(
        "campo grande"
    )
    if is_metro:
        free = order_total_brl > CAMPO_GRANDE_FREE_SHIPPING_THRESHOLD_BRL
        return ShippingQuote(
            city=city.strip() or "Campo Grande",
            is_campo_grande_metro=True,
            free_shipping=free,
            fixed_cost_brl=0.0 if free else CAMPO_GRANDE_FIXED_SHIPPING_BRL,
            delivery_window="1 a 3 dias úteis",
            carrier="Motoboy próprio",
            notes=(
                "Frete grátis na região metropolitana de Campo Grande para pedidos acima de "
                "R$ 500,00. Contato telefônico prévio antes da entrega."
                if free
                else "Taxa fixa de R$ 35,00 na região metropolitana de Campo Grande para pedidos "
                "até R$ 500,00. Contato telefônico prévio antes da entrega."
            ),
        )

    notes = (
        "Valor calculado conforme CEP, peso e dimensões. Todos os envios incluem rastreamento e "
        "seguro contra extravios e danos."
    )
    if large_instrument:
        notes += (
            " Instrumento de grande porte pode exigir frete especial com cotação individual."
        )
    return ShippingQuote(
        city=city.strip(),
        is_campo_grande_metro=False,
        free_shipping=False,
        fixed_cost_brl=None,
        delivery_window="PAC 5 a 12 dias úteis | SEDEX 2 a 5 dias úteis | Jadlog 3 a 8 dias úteis",
        carrier="Correios (PAC/SEDEX) ou Jadlog (.package)",
        notes=notes,
    )


def evaluate_return_eligibility(
    order: OrderInfo,
    reference_date: date | None = None,
) -> ReturnEligibility:
    today = reference_date or datetime.now(STORE_TZ).date()
    refund_deadline = "Reembolso na mesma forma de pagamento em até 10 dias úteis."

    if order.status == "cancelled":
        return ReturnEligibility(
            order_id=order.order_id,
            eligible=False,
            reason="Este pedido já está cancelado.",
            deadline_date=None,
            days_remaining=None,
            refund_deadline=refund_deadline,
        )

    if order.status != "delivered":
        return ReturnEligibility(
            order_id=order.order_id,
            eligible=False,
            reason=(
                f"O pedido está com status '{order.status}' e ainda não foi entregue. "
                "O prazo de 7 dias corridos do direito de arrependimento começa após o recebimento."
            ),
            deadline_date=None,
            days_remaining=None,
            refund_deadline=refund_deadline,
        )

    delivery_str = order.estimated_delivery or order.order_date
    delivery_date = date.fromisoformat(delivery_str)
    deadline = delivery_date + timedelta(days=RETURN_WINDOW_DAYS)
    days_remaining = (deadline - today).days

    if days_remaining < 0:
        return ReturnEligibility(
            order_id=order.order_id,
            eligible=False,
            reason=(
                f"O prazo legal de 7 dias corridos após a entrega ({delivery_date.isoformat()}) "
                f"encerrou em {deadline.isoformat()}."
            ),
            deadline_date=deadline.isoformat(),
            days_remaining=days_remaining,
            refund_deadline=refund_deadline,
        )

    return ReturnEligibility(
        order_id=order.order_id,
        eligible=True,
        reason=(
            f"Elegível para devolução por arrependimento até {deadline.isoformat()} "
            f"(frete de devolução por conta da loja, com embalagem original e sem sinais de uso)."
        ),
        deadline_date=deadline.isoformat(),
        days_remaining=days_remaining,
        refund_deadline=refund_deadline,
    )


def check_store_hours(now: datetime | None = None) -> StoreHoursStatus:
    local_now = now.astimezone(STORE_TZ) if now is not None else datetime.now(STORE_TZ)
    weekday = local_now.weekday()
    current_t = local_now.time()
    schedule_summary = "Seg a Sex 09:00–18:00 | Sáb 09:00–13:00 | Dom e feriados fechado"

    if weekday < 5:
        is_open = time(9, 0) <= current_t < time(18, 0)
        if is_open:
            next_opening = None
        elif current_t < time(9, 0):
            next_opening = "hoje às 09:00"
        elif weekday == 4:
            next_opening = "sábado às 09:00"
        else:
            next_opening = f"{WEEKDAYS_PT[weekday + 1]} às 09:00"
    elif weekday == 5:
        is_open = time(9, 0) <= current_t < time(13, 0)
        if is_open:
            next_opening = None
        elif current_t < time(9, 0):
            next_opening = "hoje às 09:00"
        else:
            next_opening = "segunda-feira às 09:00"
    else:
        is_open = False
        next_opening = "segunda-feira às 09:00"

    return StoreHoursStatus(
        is_open=is_open,
        current_time_local=local_now.strftime("%Y-%m-%d %H:%M"),
        weekday_pt=WEEKDAYS_PT[weekday],
        schedule_summary=schedule_summary,
        next_opening=next_opening,
    )


def _format_brl(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def build_order_pricing(
    *,
    list_price_brl: float,
    quantity: int,
    active_discount_percent: float,
    payment_method_raw: str,
    city: str,
    large_instrument: bool = False,
) -> OrderPricing:
    if quantity < 1 or quantity > 10:
        raise ValueError("A quantidade deve estar entre 1 e 10 unidades.")

    list_subtotal = round(list_price_brl * quantity, 2)
    sim = simulate_payment(list_subtotal, active_discount_percent=active_discount_percent)

    norm_pay = normalize_text(payment_method_raw or "pix")
    clean_city = city.strip() or "Campo Grande"

    is_combined = "combinad" in norm_pay or (
        "pix" in norm_pay and ("cartao" in norm_pay or "credit" in norm_pay)
    )
    if is_combined:
        if not sim.allows_combined_payment:
            raise ValueError(
                "A combinação de formas de pagamento está disponível apenas para pedidos acima "
                "de R$ 2.000,00."
            )
        payment_code = "combined_pix_credit"
        payment_label = "Combinação (entrada no PIX + saldo no cartão)"
        subtotal_brl = sim.effective_price_brl
        discount_pct = active_discount_percent
    elif "pix" in norm_pay:
        payment_code = "pix"
        subtotal_brl = sim.pix_price_brl
        discount_pct = 5.0 if sim.pix_discount_applied else active_discount_percent
        payment_label = (
            "PIX à vista (5% de desconto)"
            if sim.pix_discount_applied
            else f"PIX à vista (promoção de {active_discount_percent:g}% já aplicada)"
        )
    elif "boleto" in norm_pay:
        payment_code = "boleto"
        payment_label = "Boleto à vista"
        subtotal_brl = sim.effective_price_brl
        discount_pct = active_discount_percent
    elif "debit" in norm_pay:
        payment_code = "debit"
        payment_label = "Cartão de débito"
        subtotal_brl = sim.effective_price_brl
        discount_pct = active_discount_percent
    else:
        match = re.search(r"(\d{1,2})", norm_pay)
        installments = int(match.group(1)) if match else 1
        if installments < 1 or installments > 12:
            raise ValueError("O parcelamento no cartão aceita de 1x até 12x sem juros.")
        option = next(
            (opt for opt in sim.installment_options if opt.installments == installments),
            None,
        )
        if option is None:
            raise ValueError(
                f"Para este valor ({_format_brl(sim.effective_price_brl)}), o parcelamento "
                f"sem juros vai até {sim.max_installments}x."
            )
        payment_code = f"credit_{installments}x"
        installment_fmt = _format_brl(option.installment_value_brl)
        payment_label = (
            "Cartão de crédito à vista"
            if installments == 1
            else f"Cartão em {installments}x sem juros de {installment_fmt}"
        )
        subtotal_brl = sim.effective_price_brl
        discount_pct = active_discount_percent

    shipping = calculate_shipping(clean_city, subtotal_brl, large_instrument=large_instrument)
    if shipping.is_campo_grande_metro:
        shipping_brl = float(shipping.fixed_cost_brl or 0.0)
        if shipping.free_shipping:
            shipping_note = f"{shipping.city} · Frete grátis ({shipping.delivery_window})"
        else:
            shipping_note = (
                f"{shipping.city} · Motoboy {_format_brl(shipping_brl)} "
                f"({shipping.delivery_window})"
            )
    else:
        shipping_brl = 0.0
        shipping_note = f"{shipping.city} · Correios/Jadlog (frete calculado pelo CEP no envio)"

    total_brl = round(subtotal_brl + shipping_brl, 2)
    return OrderPricing(
        unit_price_brl=round(list_price_brl, 2),
        discount_percent=discount_pct,
        subtotal_brl=subtotal_brl,
        shipping_brl=shipping_brl,
        shipping_note=shipping_note,
        total_brl=total_brl,
        payment_method=payment_code,
        payment_label=payment_label,
        city=shipping.city,
    )
