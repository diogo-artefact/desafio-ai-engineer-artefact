from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from emporio.api import AppContainer, create_app
from emporio.config import Settings
from emporio.domain.rules import evaluate_return_eligibility
from emporio.etl.embeddings import l2_normalize
from emporio.etl.loader import load_raw_dir

RAW_DIR = Path("data/raw")


class _StubEmbedder:
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [l2_normalize([1.0, float(i + 1)]) for i, _ in enumerate(texts)]

    def embed_query(self, text: str) -> list[float]:
        return l2_normalize([1.0, 1.0])


def _parse_sse(raw_text: str) -> list[dict]:
    events: list[dict] = []
    for line in raw_text.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line.removeprefix("data: ")))
    return events


def _login_headers(client: TestClient, email: str, password: str = "user123") -> dict[str, str]:
    res = client.post("/api/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['token']}"}


def test_chat_order_draft_confirm_cancel_idor_and_auto_delivery(tmp_path: Path) -> None:
    db_path = tmp_path / "checkout.db"
    embedder = _StubEmbedder()
    load_raw_dir(RAW_DIR, db_path, embedder=embedder)

    async def fake_checkout_stream(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        has_tool_return = any(
            getattr(p, "part_kind", "") == "tool-return" for p in messages[-1].parts
        )
        if not has_tool_return:
            yield {
                0: DeltaToolCall(
                    name="prepare_order_draft",
                    json_args=(
                        '{"product_id_or_name": "Takamine GD20", '
                        '"quantity": 1, "payment_method": "pix"}'
                    ),
                )
            }
            return
        yield "Preparei o resumo do pedido do Takamine GD20 no PIX. Confira e clique em Confirmar."

    container = AppContainer.build(
        db_path=db_path,
        embedder=embedder,
        model=FunctionModel(stream_function=fake_checkout_stream),
        settings=Settings(
            database_path=db_path,
            order_auto_delivery_seconds=300,
        ),
    )
    client = TestClient(create_app(container))
    isa_headers = _login_headers(client, "isabela.moreira@jmail.com")
    leticia_headers = _login_headers(client, "leticia.rocha@jmail.com")

    before_detail = container.repo.get_product_detail("Takamine GD20")
    assert before_detail is not None
    initial_stock = before_detail.stock_quantity

    chat_res = client.post(
        "/api/chat",
        headers=isa_headers,
        json={"message": "Quero comprar um Takamine GD20 no PIX"},
    )
    assert chat_res.status_code == 200
    events = _parse_sse(chat_res.text)
    session_id = events[0]["session_id"]
    draft_events = [e for e in events if e["type"] == "order_draft"]
    assert len(draft_events) == 1
    draft = draft_events[0]["draft"]
    draft_id = draft["draft_id"]
    assert draft["status"] == "pending"
    assert draft["product_name"] == "Takamine GD20 Dreadnought Natural"
    assert draft["subtotal_brl"] == 2089.05
    assert draft["shipping_brl"] == 0.0
    assert draft["total_brl"] == 2089.05
    assert draft["city"] == "Campo Grande"

    after_draft_detail = container.repo.get_product_detail("Takamine GD20")
    assert after_draft_detail is not None
    assert after_draft_detail.stock_quantity == initial_stock

    idor_confirm = client.post(
        f"/api/orders/drafts/{draft_id}/confirm",
        headers=leticia_headers,
    )
    assert idor_confirm.status_code == 404

    confirm_res = client.post(
        f"/api/orders/drafts/{draft_id}/confirm",
        headers=isa_headers,
    )
    assert confirm_res.status_code == 200
    confirm_body = confirm_res.json()
    confirmed = confirm_body["draft"]
    assert confirmed["status"] == "confirmed"
    assert confirmed["order_id"] == 21
    assert confirmed["tracking_code"].startswith("BR")
    assert confirmed["tracking_code"].endswith("BR")
    assert len(confirmed["tracking_code"]) == 13
    assert "Pedido **#21** confirmado" in confirm_body["message"]["content"]
    assert "5 minutos" in confirm_body["message"]["content"]

    after_confirm_detail = container.repo.get_product_detail("Takamine GD20")
    assert after_confirm_detail is not None
    assert after_confirm_detail.stock_quantity == initial_stock - 1

    double_confirm = client.post(
        f"/api/orders/drafts/{draft_id}/confirm",
        headers=isa_headers,
    )
    assert double_confirm.status_code == 400

    early_deliveries = container.repo.finalize_due_deliveries(
        now=datetime.now(UTC) + timedelta(minutes=2)
    )
    assert early_deliveries == []

    delivered = container.repo.finalize_due_deliveries(
        now=datetime.now(UTC) + timedelta(minutes=6)
    )
    assert len(delivered) == 1
    assert delivered[0].status == "delivered"
    assert delivered[0].order_id == 21

    session_res = client.get(f"/api/sessions/{session_id}", headers=isa_headers)
    assert session_res.status_code == 200
    session_body = session_res.json()
    assert session_body["order_drafts"][0]["status"] == "delivered"
    assert any(
        "marcado como **entregue**" in msg["content"] and "#21" in msg["content"]
        for msg in session_body["messages"]
    )

    isa_orders = container.repo.list_orders_for_email("isabela.moreira@jmail.com")
    new_order = next(o for o in isa_orders if o.order_id == 21)
    assert new_order.status == "delivered"
    return_check = evaluate_return_eligibility(new_order)
    assert return_check.eligible is True

    second_chat = client.post(
        "/api/chat",
        headers=isa_headers,
        json={"session_id": session_id, "message": "Quero pedir outro Takamine GD20"},
    )
    second_events = _parse_sse(second_chat.text)
    second_draft_id = next(
        e["draft"]["draft_id"] for e in second_events if e["type"] == "order_draft"
    )

    cancel_res = client.post(
        f"/api/orders/drafts/{second_draft_id}/cancel",
        headers=isa_headers,
    )
    assert cancel_res.status_code == 200
    assert cancel_res.json()["draft"]["status"] == "cancelled"


def test_prepare_order_draft_rejects_discontinued_and_invalid_installments(tmp_path: Path) -> None:
    db_path = tmp_path / "checkout_rules.db"
    embedder = _StubEmbedder()
    load_raw_dir(RAW_DIR, db_path, embedder=embedder)
    tool_outputs: list[dict] = []

    async def call_invalid_drafts(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        if len(messages) == 1:
            yield {
                0: DeltaToolCall(
                    name="prepare_order_draft",
                    json_args='{"product_id_or_name": "Ibanez Bass 2X", "quantity": 1}',
                ),
                1: DeltaToolCall(
                    name="prepare_order_draft",
                    json_args=(
                        '{"product_id_or_name": "Shelby SU-21S", '
                        '"quantity": 1, "payment_method": "credit_12x"}'
                    ),
                ),
            }
            return
        for part in messages[-1].parts:
            if hasattr(part, "content") and isinstance(part.content, dict):
                tool_outputs.append(part.content)
        yield "Esses pedidos não puderam ser montados."

    container = AppContainer.build(
        db_path=db_path,
        embedder=embedder,
        model=FunctionModel(stream_function=call_invalid_drafts),
    )
    client = TestClient(create_app(container))
    isa_headers = _login_headers(client, "isabela.moreira@jmail.com")

    res = client.post(
        "/api/chat",
        headers=isa_headers,
        json={"message": "Quero pedir esses itens"},
    )
    assert res.status_code == 200
    events = _parse_sse(res.text)
    assert not any(e["type"] == "order_draft" for e in events)
    errors = {out["error"] for out in tool_outputs}
    assert errors == {"unavailable", "invalid_order_params"}
