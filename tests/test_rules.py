from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from emporio.domain.models import OrderInfo, OrderItemInfo
from emporio.domain.rules import (
    calculate_shipping,
    check_store_hours,
    evaluate_return_eligibility,
    is_large_instrument,
    simulate_payment,
)

CG_TZ = ZoneInfo("America/Campo_Grande")


def test_simulate_payment_regular_price_applies_pix_and_installment_tiers() -> None:
    sim = simulate_payment(2199.0)
    assert sim.effective_price_brl == 2199.0
    assert sim.pix_discount_applied is True
    assert sim.pix_price_brl == 2089.05
    assert sim.max_installments == 12
    assert sim.installment_options[-1].installment_value_brl == 183.25
    assert sim.allows_combined_payment is True


def test_simulate_payment_promo_blocks_cumulative_pix_discount() -> None:
    sim = simulate_payment(1299.0, active_discount_percent=18.0)
    assert sim.effective_price_brl == 1065.18
    assert sim.pix_discount_applied is False
    assert sim.pix_price_brl == 1065.18
    assert sim.max_installments == 10
    assert sim.allows_combined_payment is False


@pytest.mark.parametrize(
    ("price", "expected_max"),
    [
        (45.0, 1),
        (150.0, 3),
        (480.0, 6),
        (650.0, 6),
        (700.0, 7),
        (1200.0, 12),
    ],
)
def test_installment_minimum_tier_boundaries(price: float, expected_max: int) -> None:
    sim = simulate_payment(price)
    assert sim.max_installments == expected_max


def test_shipping_campo_grande_and_other_cities() -> None:
    free_cg = calculate_shipping("Campo Grande", 500.01)
    assert free_cg.is_campo_grande_metro is True
    assert free_cg.free_shipping is True
    assert free_cg.fixed_cost_brl == 0.0

    paid_cg = calculate_shipping("Campo Grande - MS", 350.0)
    assert paid_cg.free_shipping is False
    assert paid_cg.fixed_cost_brl == 35.0

    external = calculate_shipping("Dourados", 4500.0, large_instrument=True)
    assert external.is_campo_grande_metro is False
    assert external.fixed_cost_brl is None
    assert "grande porte" in external.notes.lower()
    assert is_large_instrument("Baterias e Percussão", "Bateria Acústica Yamaha Kit 1") is True


def test_return_eligibility_within_and_after_7_day_window() -> None:
    delivered = OrderInfo(
        order_id=7,
        customer_name="Cliente Teste",
        customer_city="Campo Grande",
        order_date="2026-02-03",
        status="delivered",
        total_brl=159.9,
        payment_method="credit_3x",
        tracking_code="BRKR1122334BR",
        estimated_delivery="2026-02-17",
        notes="",
        items=[OrderItemInfo(product_id=119, product_name="Shelby SU-21S", quantity=1)],
    )
    in_window = evaluate_return_eligibility(delivered, reference_date=date(2026, 2, 20))
    assert in_window.eligible is True
    assert in_window.deadline_date == "2026-02-24"
    assert in_window.days_remaining == 4

    expired = evaluate_return_eligibility(delivered, reference_date=date(2026, 2, 25))
    assert expired.eligible is False
    assert expired.days_remaining == -1

    cancelled = delivered.model_copy(update={"status": "cancelled"})
    assert not evaluate_return_eligibility(cancelled, reference_date=date(2026, 2, 20)).eligible

    pending = delivered.model_copy(update={"status": "pending"})
    assert not evaluate_return_eligibility(pending, reference_date=date(2026, 2, 20)).eligible


def test_store_hours_weekday_saturday_and_sunday() -> None:
    friday_open = check_store_hours(datetime(2026, 2, 20, 14, 0, tzinfo=CG_TZ))
    assert friday_open.is_open is True
    assert friday_open.next_opening is None

    friday_night = check_store_hours(datetime(2026, 2, 20, 19, 0, tzinfo=CG_TZ))
    assert friday_night.is_open is False
    assert friday_night.next_opening == "sábado às 09:00"

    saturday_open = check_store_hours(datetime(2026, 2, 21, 10, 30, tzinfo=CG_TZ))
    assert saturday_open.is_open is True

    saturday_closed = check_store_hours(datetime(2026, 2, 21, 14, 0, tzinfo=CG_TZ))
    assert saturday_closed.is_open is False
    assert saturday_closed.next_opening == "segunda-feira às 09:00"

    sunday = check_store_hours(datetime(2026, 2, 22, 11, 0, tzinfo=CG_TZ))
    assert sunday.is_open is False
    assert sunday.next_opening == "segunda-feira às 09:00"
